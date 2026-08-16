from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.base import Base
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
