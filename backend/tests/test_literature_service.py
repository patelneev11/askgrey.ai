from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
from app.models.literature import LiteratureDocument
from app.models.user import User
from app.services import literature as service


@pytest.fixture
def db() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.close()


def make_user(db: Session, email: str) -> str:
    user = User(email=email)
    db.add(user)
    db.commit()
    return str(user.id)


def expire(db: Session, document_id: str) -> None:
    """Move a stored paper's retention date into the past, as waiting 90 days would."""
    row = db.execute(
        select(LiteratureDocument).where(LiteratureDocument.document_id == document_id)
    ).scalar_one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()


def test_storing_the_same_document_twice_keeps_one_copy(db: Session) -> None:
    user_id = make_user(db, "one@askgrey.ai")

    service.store_document(db, user_id, document_id="abc123ff", content=b"%PDF-1.4 body")
    service.store_document(db, user_id, document_id="abc123ff", content=b"%PDF-1.4 body")

    assert service.stored_document_ids(db, user_id) == ["abc123ff"]
    assert service.stored_bytes(db, user_id) == len(b"%PDF-1.4 body")


def test_two_users_can_each_hold_the_same_paper(db: Session) -> None:
    first = make_user(db, "one@askgrey.ai")
    second = make_user(db, "two@askgrey.ai")

    service.store_document(db, first, document_id="abc123ff", content=b"%PDF-1.4 a")
    service.store_document(db, second, document_id="abc123ff", content=b"%PDF-1.4 a")

    assert service.get_document(db, first, "abc123ff") is not None
    assert service.get_document(db, second, "abc123ff") is not None


def test_the_oldest_papers_are_evicted_once_an_account_is_over_quota(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "MAX_DOCUMENTS_PER_USER", 3)
    user_id = make_user(db, "one@askgrey.ai")

    for index in range(5):
        service.store_document(db, user_id, document_id=f"doc{index:05d}", content=b"%PDF-1.4")

    kept = service.stored_document_ids(db, user_id)
    assert len(kept) == 3
    assert "doc00000" not in kept
    assert "doc00004" in kept


def test_the_row_holds_ciphertext_not_the_paper(db: Session) -> None:
    user_id = make_user(db, "one@askgrey.ai")
    paper = b"%PDF-1.4 unpublished compound series"

    service.store_document(db, user_id, document_id="abc123ff", content=paper)

    row = db.execute(select(LiteratureDocument)).scalar_one()
    # What a database dump would show.
    assert paper not in row.content
    assert not row.content.startswith(b"%PDF")
    # And the owner still gets the paper back.
    stored = service.get_document(db, user_id, "abc123ff")
    assert stored is not None
    assert stored.content == paper


def test_a_stranger_cannot_read_a_document_id_they_guessed(db: Session) -> None:
    owner = make_user(db, "one@askgrey.ai")
    stranger = make_user(db, "two@askgrey.ai")
    service.store_document(db, owner, document_id="abc123ff", content=b"%PDF-1.4 body")

    # The id is a digest of the bytes, so it is guessable by design; the scoping is the control.
    assert service.get_document(db, stranger, "abc123ff") is None
    # And the miss is indistinguishable from a document that was never stored.
    assert service.get_document(db, stranger, "0" * 8) is None


def test_a_stranger_cannot_delete_a_document_they_guessed(db: Session) -> None:
    owner = make_user(db, "one@askgrey.ai")
    stranger = make_user(db, "two@askgrey.ai")
    service.store_document(db, owner, document_id="abc123ff", content=b"%PDF-1.4 body")

    assert service.delete_document(db, stranger, "abc123ff") is False
    assert service.get_document(db, owner, "abc123ff") is not None


def test_deleting_a_document_removes_the_row(db: Session) -> None:
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="abc123ff", content=b"%PDF-1.4 body")

    assert service.delete_document(db, user_id, "abc123ff") is True

    assert service.stored_document_ids(db, user_id) == []
    assert db.execute(select(LiteratureDocument)).scalar_one_or_none() is None
    assert service.delete_document(db, user_id, "abc123ff") is False


def test_clearing_the_workspace_deletes_the_papers_with_it(db: Session) -> None:
    user_id = make_user(db, "one@askgrey.ai")
    other = make_user(db, "two@askgrey.ai")
    service.store_document(db, user_id, document_id="abc123ff", content=b"%PDF-1.4 body")
    service.store_document(db, user_id, document_id="abc123fe", content=b"%PDF-1.4 body 2")
    service.store_document(db, other, document_id="abc123ff", content=b"%PDF-1.4 body")

    assert service.clear_workspace(db, user_id) == 2

    assert service.stored_document_ids(db, user_id) == []
    assert service.stored_bytes(db, user_id) == 0
    # One tenant clearing their tab does not touch another's copy of the same paper.
    assert service.get_document(db, other, "abc123ff") is not None


def test_a_paper_past_its_retention_date_is_gone_rather_than_served(db: Session) -> None:
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="abc123ff", content=b"%PDF-1.4 body")
    expire(db, "abc123ff")

    assert service.get_document(db, user_id, "abc123ff") is None

    assert service.stored_document_ids(db, user_id) == []
    assert service.stored_bytes(db, user_id) == 0
    # The read deleted it, so the bytes are not merely hidden from the listing.
    assert db.execute(select(LiteratureDocument)).scalar_one_or_none() is None


def test_expired_papers_are_purged_when_another_is_stored(db: Session) -> None:
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="abc123ff", content=b"%PDF-1.4 body")
    expire(db, "abc123ff")

    service.store_document(db, user_id, document_id="abc123fe", content=b"%PDF-1.4 other")

    assert service.stored_document_ids(db, user_id) == ["abc123fe"]


def test_re_adding_a_paper_renews_its_retention_window(db: Session) -> None:
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="abc123ff", content=b"%PDF-1.4 body")
    first = db.execute(select(LiteratureDocument.expires_at)).scalar_one()
    expire(db, "abc123ff")

    service.store_document(db, user_id, document_id="abc123ff", content=b"%PDF-1.4 body")

    stored = service.get_document(db, user_id, "abc123ff")
    assert stored is not None
    assert stored.expires_at > first.replace(tzinfo=timezone.utc)


def test_a_paper_no_longer_decryptable_is_dropped_rather_than_raising(db: Session) -> None:
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="abc123ff", content=b"%PDF-1.4 body")
    row = db.execute(select(LiteratureDocument)).scalar_one()
    # What a rotated key looks like from here: bytes that no longer authenticate.
    row.content = row.content[:-1] + bytes([row.content[-1] ^ 0x01])
    db.commit()

    assert service.get_document(db, user_id, "abc123ff") is None

    assert db.execute(select(LiteratureDocument)).scalar_one_or_none() is None
