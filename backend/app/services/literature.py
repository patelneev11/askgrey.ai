"""Persistence for the Literature workspace: saved tables and the papers behind them.

A document id is a digest of the bytes, so it is guessable by anyone holding the same paper:
what keeps one tenant's library out of another's is that every lookup is scoped, never the
id alone. A paper is readable by the account that added it, and — when it was added while
working in a shared workspace — by that workspace's members, who reach it through the `Access`
the workspace service issued rather than by naming a workspace. Nothing else can read it.

Sharing does not re-key anything. The bytes stay sealed under the account that uploaded them
(that account's id is in the KMS encryption context and in the AES-GCM associated data), so a
member's read decrypts under the owner of record and membership is the app's decision, checked
here, on every read. The alternative — re-encrypting a paper when it is shared — would rewrite
ciphertext on a membership change and lose the property that a row can only ever be opened as
the document and owner it was written as.

Four properties this module owns, rather than the caller:

* the stored bytes are encrypted under the account that added them (`app.core.crypto`), so
  nothing outside this module ever holds ciphertext and nothing inside the database holds a PDF;
* a stored paper expires, and an expired one is deleted on sight rather than served;
* deleting is real deletion of the row, and clearing the workspace takes the papers with it;
* only the account that added a paper may delete it — sharing a finding with colleagues is not
  handing them the power to destroy the copy every citation in the shared table renders from.

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

from sqlalchemy import ColumnElement, case, func, or_, select
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
from app.services.workspaces import Access

logger = logging.getLogger(__name__)

# Bounds on what one account may keep, so a saved workspace cannot grow without limit.
MAX_DOCUMENTS_PER_USER = 40
MAX_STORED_BYTES_PER_USER = 250 * 1024 * 1024
MAX_TABLE_JSON_BYTES = 4 * 1024 * 1024


class WorkspaceTooLargeError(Exception):
    """The submitted table is larger than a review table is ever expected to be."""


class DocumentPermissionError(Exception):
    """The caller may read this paper, but it is not theirs to change."""


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
    # Which account added it, and the workspace it is shared with if any: a member reading a
    # colleague's paper is a different event from reading their own, and the audit trail says so.
    owner_user_id: str
    workspace_id: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; comparing those to an aware `now` raises."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _readable(user_id: str, workspace: Access | None) -> ColumnElement[bool]:
    """The stored papers this caller may open: their own, plus the active workspace's shared ones.

    A paper of their own stays readable inside a workspace, the same way their private saved work
    does: switching into a workspace is not filing your own library away.
    """
    own = LiteratureDocument.user_id == user_id
    if workspace is None:
        return own
    return or_(own, LiteratureDocument.workspace_id == workspace.workspace_id)


def get_workspace(db: Session, user_id: str, workspace: Access | None = None) -> WorkspaceRead:
    row = db.execute(
        select(LiteratureWorkspace).where(LiteratureWorkspace.user_id == user_id)
    ).scalar_one_or_none()
    if row is None:
        # Still report what can be opened: a member with nothing saved of their own can be shown
        # a colleague's shared paper the moment they open the workspace's table.
        return WorkspaceRead(stored_document_ids=stored_document_ids(db, user_id, workspace))
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
        stored_document_ids=stored_document_ids(db, user_id, workspace),
    )


def save_workspace(
    db: Session, user_id: str, payload: WorkspaceWrite, workspace: Access | None = None
) -> WorkspaceRead:
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
        stored_document_ids=stored_document_ids(db, user_id, workspace),
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


def delete_document(
    db: Session, user_id: str, document_id: str, workspace: Access | None = None
) -> bool:
    """Delete one of this user's stored papers. False when there was nothing to delete.

    A colleague's paper shared into the active workspace is readable but not deletable: it is
    their upload, on their retention clock and inside their storage quota, and every citation in
    the shared table renders from it. That refusal is a `DocumentPermissionError` rather than a
    "no such document", because the caller can already see the paper — pretending otherwise
    would only make a working button look broken.
    """
    row = db.execute(
        select(LiteratureDocument).where(
            LiteratureDocument.user_id == user_id,
            LiteratureDocument.document_id == document_id,
        )
    ).scalar_one_or_none()
    if row is None and _shared_row(db, user_id, document_id, workspace) is not None:
        raise DocumentPermissionError("only the account that added this paper can delete it")
    return bool(_forget(db, [row] if row is not None else []))


def _shared_row(
    db: Session, user_id: str, document_id: str, workspace: Access | None
) -> LiteratureDocument | None:
    """A readable copy of this paper that somebody else added, if the workspace shares one."""
    if workspace is None:
        return None
    return (
        db.execute(
            select(LiteratureDocument).where(
                LiteratureDocument.workspace_id == workspace.workspace_id,
                LiteratureDocument.document_id == document_id,
                LiteratureDocument.user_id != user_id,
            )
        )
        .scalars()
        .first()
    )


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


def stored_document_ids(db: Session, user_id: str, workspace: Access | None = None) -> list[str]:
    """Every paper this caller can open, so the tab offers a citation view for exactly those."""
    rows = db.execute(
        select(LiteratureDocument.document_id)
        .where(_readable(user_id, workspace), LiteratureDocument.expires_at > _now())
        .distinct()
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


def get_document(
    db: Session, user_id: str, document_id: str, workspace: Access | None = None
) -> StoredDocument | None:
    """A paper this caller may open, decrypted, or None if there is nothing to serve.

    None covers all four ways there is nothing: never stored, stored by somebody who has not
    shared it with a workspace this caller is in, past its retention date, or no longer
    decryptable under the current key. The last two delete the row on the way out, so an expired
    paper stops existing the first time it is asked for.

    A key service or object store that cannot be reached is not one of those four:
    `DocumentKeyUnavailableError` and `BlobStoreUnavailableError` propagate (becoming a 503)
    precisely so a KMS or S3 outage, or a revoked credential, cannot be mistaken for a corrupt
    row and delete the library it could not read.
    """
    # Two accounts that upload the same paper hold two rows under the same document id, since
    # the id is a digest of the bytes. The caller's own copy is preferred: it is sealed under
    # their account, and reading somebody else's is a shared read to be audited as one.
    row = (
        db.execute(
            select(LiteratureDocument)
            .where(_readable(user_id, workspace), LiteratureDocument.document_id == document_id)
            .order_by(case((LiteratureDocument.user_id == user_id, 0), else_=1))
            .limit(1)
        )
        .scalars()
        .first()
    )
    if row is None:
        return None
    owner_user_id = row.user_id
    if _as_utc(row.expires_at) <= _now():
        _forget(db, [row])
        return None
    try:
        sealed = _sealed_bytes(row)
        # Under the account that sealed it, not the account reading it: a shared paper is not
        # re-encrypted per member, so the owner of record is what the envelope authenticates.
        content = decrypt_document(sealed, user_id=owner_user_id, document_id=document_id)
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
        owner_user_id=owner_user_id,
        workspace_id=row.workspace_id,
    )


def store_document(
    db: Session,
    user_id: str,
    *,
    document_id: str,
    content: bytes,
    filename: str = "",
    source_url: str = "",
    workspace: Access | None = None,
) -> None:
    """Keep a paper's bytes for this user, encrypted, replacing any earlier copy of it.

    Re-storing a paper renews its retention window: it is a paper the user is working with
    now, not one whose clock started the first time they touched it.

    A paper added while working in a shared workspace is shared with that workspace's members,
    which is the same rule the saved artifacts follow. A viewer's upload stays private: they may
    not save work into the workspace, so their paper is not contributed to it either. Re-adding
    a paper privately gives it back: the row records where it was last added, so un-sharing is
    dragging the file in again outside the workspace.
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
    row.workspace_id = (
        workspace.workspace_id if workspace is not None and workspace.may_write else None
    )
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
    "DocumentPermissionError",
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
