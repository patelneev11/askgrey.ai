"""Persistence for the Literature workspace: saved tables and the papers behind them.

Everything here is scoped to one user id. A lookup is always `(user_id, document_id)` — a
document id is a digest of the bytes, so it is guessable by anyone holding the same paper,
and scoping the read is what keeps one tenant's library out of another's.

Three properties this module owns, rather than the caller:

* the stored bytes are encrypted under the owning account (`app.core.crypto`), so nothing
  outside this module ever holds ciphertext and nothing inside the database holds a PDF;
* a stored paper expires, and an expired one is deleted on sight rather than served;
* deleting is real deletion of the row, and clearing the workspace takes the papers with it.

The ciphertext itself may live in the row or in an S3 bucket (`app.core.blobs`), which is why
every deletion here goes through `_forget`: a row deleted on its own would leave the bytes it
owned in the bucket, and "deleted" has to mean the paper is gone, not dereferenced. Object
first, row second, so an interruption leaves a row pointing at nothing (which the next read
cleans up) rather than an object nothing points at.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.blobs import (
    BlobMissingError,
    BlobStoreUnavailableError,
    pointed_key,
    pointer_to,
    store_for,
)
from app.core.config import get_settings
from app.core.crypto import DecryptionError, decrypt_document, encrypt_document
from app.models.literature import LiteratureDocument, LiteratureWorkspace
from app.schemas.literature import WorkspaceRead, WorkspaceWrite
from app.services.pdf_extraction import ExtractionTable

logger = logging.getLogger(__name__)

# Bounds on what one account may keep, so a saved workspace cannot grow without limit.
MAX_DOCUMENTS_PER_USER = 40
MAX_STORED_BYTES_PER_USER = 250 * 1024 * 1024
MAX_TABLE_JSON_BYTES = 4 * 1024 * 1024


class WorkspaceTooLargeError(Exception):
    """The submitted table is larger than a review table is ever expected to be."""


@dataclass(frozen=True)
class StoredDocument:
    """A decrypted stored paper. Callers never see the row, so they never see ciphertext."""

    document_id: str
    filename: str
    source_url: str
    byte_size: int
    content: bytes
    created_at: datetime
    expires_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; comparing those to an aware `now` raises."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def get_workspace(db: Session, user_id: str) -> WorkspaceRead:
    row = db.execute(
        select(LiteratureWorkspace).where(LiteratureWorkspace.user_id == user_id)
    ).scalar_one_or_none()
    if row is None:
        return WorkspaceRead()
    saved = WorkspaceWrite.model_validate(
        {
            "goal": row.goal,
            "sources": json.loads(row.sources_json or "[]"),
            "table": json.loads(row.table_json) if row.table_json else None,
        }
    )
    return WorkspaceRead(
        goal=saved.goal,
        sources=saved.sources,
        table=saved.table,
        updated_at=row.updated_at,
        stored_document_ids=stored_document_ids(db, user_id),
    )


def save_workspace(db: Session, user_id: str, payload: WorkspaceWrite) -> WorkspaceRead:
    table_json = payload.table.model_dump_json() if payload.table is not None else ""
    if len(table_json.encode("utf-8")) > MAX_TABLE_JSON_BYTES:
        raise WorkspaceTooLargeError("the review table is too large to save")
    sources_json = json.dumps([source.model_dump() for source in payload.sources])

    row = db.execute(
        select(LiteratureWorkspace).where(LiteratureWorkspace.user_id == user_id)
    ).scalar_one_or_none()
    if row is None:
        row = LiteratureWorkspace(user_id=user_id)
        db.add(row)
    row.goal = payload.goal
    row.sources_json = sources_json
    row.table_json = table_json
    db.commit()
    db.refresh(row)
    return WorkspaceRead(
        goal=payload.goal,
        sources=payload.sources,
        table=payload.table,
        updated_at=row.updated_at,
        stored_document_ids=stored_document_ids(db, user_id),
    )


def _forget(db: Session, rows: list[LiteratureDocument]) -> int:
    """Delete these rows and whatever bytes they own, wherever those bytes live.

    A store that cannot be reached raises, leaving the row in place: the alternative is a
    deletion that reports success while the object survives in the bucket.
    """
    store = store_for(get_settings())
    for row in rows:
        if store is not None:
            try:
                key = pointed_key(row.content)
            except BlobMissingError:
                key = None
            if key is not None:
                store.delete(key)
        db.delete(row)
    db.commit()
    return len(rows)


def clear_workspace(db: Session, user_id: str) -> int:
    """Forget this user's workspace *and* the papers it referenced.

    Clearing the tab used to leave the stored bytes behind, which made "clear" a claim the
    store did not honour. Returns how many papers were deleted, so the caller can audit it.
    """
    row = db.execute(
        select(LiteratureWorkspace).where(LiteratureWorkspace.user_id == user_id)
    ).scalar_one_or_none()
    if row is not None:
        db.delete(row)
    papers = list(
        db.execute(
            select(LiteratureDocument).where(LiteratureDocument.user_id == user_id)
        ).scalars()
    )
    return _forget(db, papers)


def delete_document(db: Session, user_id: str, document_id: str) -> bool:
    """Delete one of this user's stored papers. False when there was nothing to delete."""
    row = db.execute(
        select(LiteratureDocument).where(
            LiteratureDocument.user_id == user_id,
            LiteratureDocument.document_id == document_id,
        )
    ).scalar_one_or_none()
    return bool(_forget(db, [row] if row is not None else []))


def purge_expired_documents(db: Session) -> int:
    """Delete every stored paper past its retention date, for any user.

    Called on each store and each read rather than from a scheduler: there is no scheduler in
    this deployment, and a retention window nothing enforces is a promise, not a control.
    """
    expired = list(
        db.execute(
            select(LiteratureDocument).where(LiteratureDocument.expires_at <= _now())
        ).scalars()
    )
    return _forget(db, expired)


def stored_document_ids(db: Session, user_id: str) -> list[str]:
    rows = db.execute(
        select(LiteratureDocument.document_id).where(
            LiteratureDocument.user_id == user_id,
            LiteratureDocument.expires_at > _now(),
        )
    ).scalars()
    return list(rows)


def _sealed_bytes(row: LiteratureDocument) -> bytes:
    """The row's ciphertext, fetched from the object store when the row is only a pointer."""
    key = pointed_key(row.content)
    if key is None:
        return row.content
    store = store_for(get_settings())
    if store is None:
        # The bytes went to a bucket this deployment no longer knows about. A configuration
        # regression, not a bad row: `BlobMissingError` would delete it.
        raise BlobStoreUnavailableError(
            "this document's bytes are in an object store but DOCUMENT_S3_BUCKET is not set"
        )
    return store.get(key)


def get_document(db: Session, user_id: str, document_id: str) -> StoredDocument | None:
    """This user's copy of a paper, decrypted, or None if there is nothing to serve.

    None covers all four ways there is nothing: never stored, stored by somebody else, past
    its retention date, or no longer decryptable under the current key. The last two delete the
    row on the way out, so an expired paper stops existing the first time it is asked for.

    A key service or object store that cannot be reached is not one of those four:
    `DocumentKeyUnavailableError` and `BlobStoreUnavailableError` propagate (becoming a 503)
    precisely so a KMS or S3 outage, or a revoked credential, cannot be mistaken for a corrupt
    row and delete the library it could not read.
    """
    row = db.execute(
        select(LiteratureDocument).where(
            LiteratureDocument.user_id == user_id,
            LiteratureDocument.document_id == document_id,
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if _as_utc(row.expires_at) <= _now():
        _forget(db, [row])
        return None
    try:
        sealed = _sealed_bytes(row)
        content = decrypt_document(sealed, user_id=user_id, document_id=document_id)
    except BlobMissingError:
        # The row points into the bucket and the object is not there: an orphan from an
        # interrupted delete or a lifecycle rule, never an outage (that raises instead).
        logger.warning(
            "discarding a stored document whose bytes are no longer in the object store",
            extra={"document_id": document_id},
        )
        _forget(db, [row])
        return None
    except DecryptionError:
        # The key changed (or the row was tampered with). The bytes are a copy of a paper the
        # user can add again, so drop the unreadable row instead of failing every later read.
        logger.warning(
            "discarding an undecryptable stored document",
            extra={"document_id": document_id},
        )
        _forget(db, [row])
        return None
    return StoredDocument(
        document_id=row.document_id,
        filename=row.filename,
        source_url=row.source_url,
        byte_size=row.byte_size,
        content=content,
        created_at=_as_utc(row.created_at),
        expires_at=_as_utc(row.expires_at),
    )


def store_document(
    db: Session,
    user_id: str,
    *,
    document_id: str,
    content: bytes,
    filename: str = "",
    source_url: str = "",
) -> None:
    """Keep a paper's bytes for this user, encrypted, replacing any earlier copy of it.

    Re-storing a paper renews its retention window: it is a paper the user is working with
    now, not one whose clock started the first time they touched it.
    """
    purge_expired_documents(db)
    settings = get_settings()
    expires_at = _now() + timedelta(days=settings.document_retention_days)
    sealed = encrypt_document(content, user_id=user_id, document_id=document_id)

    store = store_for(settings)
    if store is None:
        held = sealed
    else:
        # The object is written before the row, so a row never promises bytes that are not
        # there; a write that fails leaves an unreferenced object the next store overwrites.
        key = store.key_for(user_id, document_id)
        store.put(key, sealed)
        held = pointer_to(key)

    row = db.execute(
        select(LiteratureDocument).where(
            LiteratureDocument.user_id == user_id,
            LiteratureDocument.document_id == document_id,
        )
    ).scalar_one_or_none()
    if row is None:
        row = LiteratureDocument(
            user_id=user_id, document_id=document_id, filename="", source_url=""
        )
        db.add(row)
    row.filename = (filename or row.filename)[:500]
    row.source_url = (source_url or row.source_url)[:2000]
    row.byte_size = len(content)
    row.content = held
    row.expires_at = expires_at
    db.commit()
    _evict_over_quota(db, user_id)


def _evict_over_quota(db: Session, user_id: str) -> None:
    """Drop the oldest papers once an account is over its count or byte allowance."""
    rows = list(
        db.execute(
            select(LiteratureDocument)
            .where(LiteratureDocument.user_id == user_id)
            .order_by(LiteratureDocument.created_at.desc())
        ).scalars()
    )
    total = 0
    over: list[LiteratureDocument] = []
    for index, row in enumerate(rows):
        total += row.byte_size
        if index >= MAX_DOCUMENTS_PER_USER or total > MAX_STORED_BYTES_PER_USER:
            over.append(row)
    _forget(db, over)


def stored_bytes(db: Session, user_id: str) -> int:
    total = db.execute(
        select(func.coalesce(func.sum(LiteratureDocument.byte_size), 0)).where(
            LiteratureDocument.user_id == user_id,
            LiteratureDocument.expires_at > _now(),
        )
    ).scalar_one()
    return int(total)


__all__ = [
    "ExtractionTable",
    "StoredDocument",
    "WorkspaceTooLargeError",
    "clear_workspace",
    "delete_document",
    "get_document",
    "get_workspace",
    "purge_expired_documents",
    "save_workspace",
    "store_document",
    "stored_bytes",
    "stored_document_ids",
]
