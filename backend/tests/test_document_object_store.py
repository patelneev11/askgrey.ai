"""Stored papers whose ciphertext lives in an S3 bucket instead of a database column.

There is no AWS account here, so S3 is stood in for by `FakeS3` — an in-process double that
behaves like `PutObject`, `GetObject` and `DeleteObject` in the ways this app depends on: keys
map to bytes, a missing key raises `NoSuchKey`, and the arguments a bucket policy would care
about are recorded so they can be asserted. Durability, versioning and lifecycle rules are
properties of the bucket, not of this code, and no test here pretends to cover them.

The property most of these tests exist for is the split between "the bucket has nothing there"
and "the bucket did not answer". A read that cannot produce bytes deletes the row (see
`app.services.literature`), so an outage that looked like a missing object would delete the
library it failed to reach.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import blobs
from app.core.blobs import (
    POINTER_MAGIC,
    BlobMissingError,
    BlobStoreUnavailableError,
    S3Blobs,
    object_key,
    pointed_key,
    pointer_to,
    store_for,
)
from app.core.config import Settings
from app.models.base import Base
from app.models.literature import LiteratureDocument
from app.models.user import User
from app.services import literature as service

PDF = b"%PDF-1.4 confidential compound series"
BUCKET = "askgrey-documents"


def s3_error(code: str, operation: str = "GetObject") -> ClientError:
    """The real botocore exception, so the error-code handling under test is the real one."""
    return ClientError({"Error": {"Code": code, "Message": code}}, operation)


class FakeS3:
    """The three S3 calls the document store makes, backed by a dict."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[dict[str, Any]] = []
        self.deleted: list[str] = []

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, **extra: str) -> dict[str, Any]:
        assert Bucket == BUCKET
        self.objects[Key] = Body
        self.puts.append({"Key": Key, **extra})
        return {}

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        assert Bucket == BUCKET
        if Key not in self.objects:
            raise s3_error("NoSuchKey")
        return {"Body": _Body(self.objects[Key])}

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        assert Bucket == BUCKET
        self.deleted.append(Key)
        self.objects.pop(Key, None)
        return {}


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class UnreachableS3:
    """A bucket that is simply not answering: no verdict on whether the object is there."""

    def _fail(self) -> None:
        raise EndpointConnectionError(endpoint_url="https://s3.us-east-1.amazonaws.com")

    def put_object(self, **_: Any) -> dict[str, Any]:
        self._fail()
        raise AssertionError("unreachable")

    def get_object(self, **_: Any) -> dict[str, Any]:
        self._fail()
        raise AssertionError("unreachable")

    def delete_object(self, **_: Any) -> dict[str, Any]:
        self._fail()
        raise AssertionError("unreachable")


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


@pytest.fixture
def fake_s3() -> FakeS3:
    return FakeS3()


def use_store(monkeypatch: pytest.MonkeyPatch, client: Any, *, prefix: str = "") -> S3Blobs:
    """Point the literature service at a bucket backed by `client`."""
    store = S3Blobs(BUCKET, prefix=prefix, client=client)
    monkeypatch.setattr(service, "store_for", lambda _settings: store)
    return store


def make_user(db: Session, email: str) -> str:
    user = User(email=email)
    db.add(user)
    db.commit()
    return str(user.id)


def row_for(db: Session, document_id: str) -> LiteratureDocument:
    return db.execute(
        select(LiteratureDocument).where(LiteratureDocument.document_id == document_id)
    ).scalar_one()


def expire(db: Session, document_id: str) -> None:
    row = row_for(db, document_id)
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()


# --- the pointer itself ------------------------------------------------------------------


def test_a_pointer_round_trips_to_its_key() -> None:
    assert pointed_key(pointer_to("documents/u1/d1")) == "documents/u1/d1"


def test_ciphertext_is_never_read_as_a_pointer() -> None:
    """The two are distinguished by the row's own bytes, so they must not collide."""
    assert pointed_key(b"AGD1\x02 sealed bytes") is None
    assert pointed_key(b"") is None


def test_an_unusable_pointer_is_a_bad_row_and_not_an_outage() -> None:
    with pytest.raises(BlobMissingError):
        pointed_key(POINTER_MAGIC + b"\x01")


def test_an_object_key_names_the_owner_and_the_digest_and_nothing_else() -> None:
    key = object_key("u1", "d1")

    assert key == "documents/u1/d1"
    assert object_key("u1", "d1", prefix="/tenant-a/") == "tenant-a/documents/u1/d1"


def test_a_key_is_scoped_to_its_account() -> None:
    # One account cannot construct another's key without knowing the other's user id, and the
    # read is scoped by user id anyway; this keeps the bucket layout auditable per account.
    assert object_key("u1", "d1") != object_key("u2", "d1")


# --- configuration ----------------------------------------------------------------------


def test_no_bucket_means_the_database_holds_the_bytes() -> None:
    settings = Settings(jwt_secret="x" * 40)

    assert store_for(settings) is None
    assert settings.document_storage == "database"


def test_a_configured_bucket_is_reported_as_the_storage_location() -> None:
    settings = Settings(document_s3_bucket=BUCKET, jwt_secret="x" * 40)

    assert store_for(settings) is not None
    assert settings.document_storage == "s3"


def test_the_bucket_is_asked_to_encrypt_again_under_the_same_kms_key(fake_s3: FakeS3) -> None:
    """Defence in depth: the app's ciphertext, sealed a second time by the bucket."""
    store = S3Blobs(BUCKET, kms_key_id="alias/askgrey-documents", client=fake_s3)

    store.put("documents/u1/d1", b"sealed")

    assert fake_s3.puts == [
        {
            "Key": "documents/u1/d1",
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": "alias/askgrey-documents",
        }
    ]


# --- the store, through the service ------------------------------------------------------


def test_a_stored_paper_round_trips_through_the_bucket(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, fake_s3)
    user_id = make_user(db, "one@askgrey.ai")

    service.store_document(db, user_id, document_id="d1", content=PDF, filename="paper.pdf")
    stored = service.get_document(db, user_id, "d1")

    assert stored is not None
    assert stored.content == PDF
    assert stored.byte_size == len(PDF)


def test_the_bucket_receives_ciphertext_and_the_row_receives_a_pointer(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, fake_s3)
    user_id = make_user(db, "one@askgrey.ai")

    service.store_document(db, user_id, document_id="d1", content=PDF)

    key = object_key(user_id, "d1")
    assert list(fake_s3.objects) == [key]
    # What an object listing would hand over: bytes no reader can open without the app's key.
    assert PDF not in fake_s3.objects[key]
    assert row_for(db, "d1").content == pointer_to(key)


def test_a_prefixed_bucket_keeps_the_documents_under_it(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, fake_s3, prefix="askgrey")
    user_id = make_user(db, "one@askgrey.ai")

    service.store_document(db, user_id, document_id="d1", content=PDF)

    assert list(fake_s3.objects) == [f"askgrey/documents/{user_id}/d1"]


def test_one_account_cannot_read_another_account_s_object(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, fake_s3)
    owner = make_user(db, "owner@askgrey.ai")
    intruder = make_user(db, "intruder@askgrey.ai")
    service.store_document(db, owner, document_id="d1", content=PDF)

    # The digest is guessable by anyone holding the same paper; the scoping is what protects it.
    assert service.get_document(db, intruder, "d1") is None
    assert service.get_document(db, owner, "d1") is not None


def test_storing_a_paper_twice_overwrites_one_object(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, fake_s3)
    user_id = make_user(db, "one@askgrey.ai")

    service.store_document(db, user_id, document_id="d1", content=PDF)
    service.store_document(db, user_id, document_id="d1", content=PDF)

    assert len(fake_s3.objects) == 1


# --- deletion has to reach the bucket ----------------------------------------------------


def test_deleting_a_paper_deletes_its_object(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, fake_s3)
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="d1", content=PDF)

    assert service.delete_document(db, user_id, "d1") is True

    # A row deleted on its own would leave the paper in the bucket for the retention of the
    # bucket, which is not what the tab told the user.
    assert fake_s3.objects == {}
    assert service.stored_document_ids(db, user_id) == []


def test_clearing_the_workspace_deletes_every_object(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, fake_s3)
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="d1", content=PDF)
    service.store_document(db, user_id, document_id="d2", content=PDF + b" two")

    assert service.clear_workspace(db, user_id) == 2

    assert fake_s3.objects == {}


def test_retention_deletes_the_object_and_not_only_the_row(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, fake_s3)
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="d1", content=PDF)
    expire(db, "d1")

    assert service.purge_expired_documents(db) == 1

    assert fake_s3.objects == {}


def test_an_expired_paper_asked_for_directly_takes_its_object_with_it(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, fake_s3)
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="d1", content=PDF)
    expire(db, "d1")

    assert service.get_document(db, user_id, "d1") is None

    assert fake_s3.objects == {}


def test_eviction_over_quota_deletes_the_objects_it_drops(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, fake_s3)
    monkeypatch.setattr(service, "MAX_DOCUMENTS_PER_USER", 1)
    user_id = make_user(db, "one@askgrey.ai")

    service.store_document(db, user_id, document_id="d1", content=PDF)
    service.store_document(db, user_id, document_id="d2", content=PDF + b" two")

    assert len(fake_s3.objects) == 1
    assert service.stored_document_ids(db, user_id) == ["d2"]


# --- the two kinds of failure -----------------------------------------------------------


def test_an_object_that_is_gone_drops_the_row_that_pointed_at_it(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, fake_s3)
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="d1", content=PDF)
    fake_s3.objects.clear()  # an interrupted delete, or a lifecycle rule that ran

    assert service.get_document(db, user_id, "d1") is None

    # Nothing can be served from that row again, so keeping it would only fail every read.
    assert service.stored_document_ids(db, user_id) == []


def test_a_bucket_that_does_not_answer_is_not_reported_as_a_missing_paper(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The distinction the whole library depends on.

    A read that produces no bytes deletes the row. If an S3 outage or a revoked policy looked
    like that, the first blip would delete every stored paper — so it raises instead, and the
    row survives to be read once the bucket answers again.
    """
    use_store(monkeypatch, fake_s3)
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="d1", content=PDF)

    use_store(monkeypatch, UnreachableS3())
    with pytest.raises(BlobStoreUnavailableError):
        service.get_document(db, user_id, "d1")

    use_store(monkeypatch, fake_s3)
    recovered = service.get_document(db, user_id, "d1")
    assert recovered is not None and recovered.content == PDF


@pytest.mark.parametrize("code", ["AccessDenied", "SlowDown", "InternalError"])
def test_a_refused_or_throttled_read_is_an_outage_and_not_a_missing_object(code: str) -> None:
    class Refusing:
        def get_object(self, **_: Any) -> dict[str, Any]:
            raise s3_error(code)

    store = S3Blobs(BUCKET, client=Refusing())

    # AccessDenied is the one that matters: a policy tightened by mistake must not read as
    # "the paper is gone" and delete the library on the next read.
    with pytest.raises(BlobStoreUnavailableError):
        store.get("documents/u1/d1")


def test_a_failed_write_does_not_leave_a_row_promising_bytes(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, UnreachableS3())
    user_id = make_user(db, "one@askgrey.ai")

    with pytest.raises(BlobStoreUnavailableError):
        service.store_document(db, user_id, document_id="d1", content=PDF)

    assert service.stored_document_ids(db, user_id) == []


def test_a_deletion_the_bucket_refuses_does_not_report_success(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, fake_s3)
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="d1", content=PDF)

    use_store(monkeypatch, UnreachableS3())
    with pytest.raises(BlobStoreUnavailableError):
        service.delete_document(db, user_id, "d1")

    # The row survives, so the next attempt (or the retention sweep) tries the object again
    # rather than abandoning it in the bucket.
    use_store(monkeypatch, fake_s3)
    assert service.stored_document_ids(db, user_id) == ["d1"]


def test_an_object_already_gone_is_a_successful_delete(fake_s3: FakeS3) -> None:
    store = S3Blobs(BUCKET, client=fake_s3)

    store.delete("documents/u1/missing")

    assert fake_s3.deleted == ["documents/u1/missing"]


# --- adopting a bucket after the fact ---------------------------------------------------


def test_rows_written_before_the_bucket_are_still_readable_after_it(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turning the bucket on is a configuration change, not a migration of every row."""
    monkeypatch.setattr(service, "store_for", lambda _settings: None)
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="d1", content=PDF)

    use_store(monkeypatch, fake_s3)
    service.store_document(db, user_id, document_id="d2", content=PDF + b" two")

    inline = service.get_document(db, user_id, "d1")
    in_bucket = service.get_document(db, user_id, "d2")
    assert inline is not None and inline.content == PDF
    assert in_bucket is not None and in_bucket.content == PDF + b" two"
    assert list(fake_s3.objects) == [object_key(user_id, "d2")]


def test_a_row_in_a_bucket_this_deployment_forgot_is_an_outage_not_a_bad_row(
    db: Session, fake_s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    use_store(monkeypatch, fake_s3)
    user_id = make_user(db, "one@askgrey.ai")
    service.store_document(db, user_id, document_id="d1", content=PDF)

    # DOCUMENT_S3_BUCKET removed from the environment while rows still point into it.
    monkeypatch.setattr(service, "store_for", lambda _settings: None)
    with pytest.raises(BlobStoreUnavailableError):
        service.get_document(db, user_id, "d1")

    # Deleting the row here would lose a paper over a configuration mistake.
    assert service.stored_document_ids(db, user_id) == ["d1"]


def test_the_client_is_not_built_until_the_bucket_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """boto3 is imported and the client built on first use, not at configuration time.

    So a deployment with no bucket never constructs one, and a process that never serves a
    stored paper never needs AWS credentials to start.
    """

    built: list[str] = []

    def record(region: str) -> Any:
        built.append(region)
        return FakeS3()

    monkeypatch.setattr(blobs, "_build_client", record)
    store = S3Blobs(BUCKET, region="us-east-1")
    assert built == []

    with pytest.raises(BlobMissingError):
        store.get("documents/u1/d1")
    assert built == ["us-east-1"]
