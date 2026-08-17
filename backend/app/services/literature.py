"""Persistence for the Literature workspace: saved tables and the papers behind them.

Everything here is scoped to one user id. A lookup is always `(user_id, document_id)` — a
document id is a digest of the bytes, so it is guessable by anyone holding the same paper,
and scoping the read is what keeps one tenant's library out of another's.
"""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.literature import LiteratureDocument, LiteratureWorkspace
from app.schemas.literature import WorkspaceRead, WorkspaceWrite
from app.services.pdf_extraction import ExtractionTable

# Bounds on what one account may keep, so a saved workspace cannot grow without limit.
MAX_DOCUMENTS_PER_USER = 40
MAX_STORED_BYTES_PER_USER = 250 * 1024 * 1024
MAX_TABLE_JSON_BYTES = 4 * 1024 * 1024


class WorkspaceTooLargeError(Exception):
    """The submitted table is larger than a review table is ever expected to be."""


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


def clear_workspace(db: Session, user_id: str) -> None:
    row = db.execute(
        select(LiteratureWorkspace).where(LiteratureWorkspace.user_id == user_id)
    ).scalar_one_or_none()
    if row is not None:
        db.delete(row)
        db.commit()


def stored_document_ids(db: Session, user_id: str) -> list[str]:
    rows = db.execute(
        select(LiteratureDocument.document_id).where(LiteratureDocument.user_id == user_id)
    ).scalars()
    return list(rows)


def get_document(db: Session, user_id: str, document_id: str) -> LiteratureDocument | None:
    return db.execute(
        select(LiteratureDocument).where(
            LiteratureDocument.user_id == user_id,
            LiteratureDocument.document_id == document_id,
        )
    ).scalar_one_or_none()


def store_document(
    db: Session,
    user_id: str,
    *,
    document_id: str,
    content: bytes,
    filename: str = "",
    source_url: str = "",
) -> LiteratureDocument:
    """Keep a paper's bytes for this user, replacing any earlier copy of the same document."""
    existing = get_document(db, user_id, document_id)
    if existing is not None:
        existing.filename = filename or existing.filename
        existing.source_url = source_url or existing.source_url
        db.commit()
        db.refresh(existing)
        return existing

    row = LiteratureDocument(
        user_id=user_id,
        document_id=document_id,
        filename=filename[:500],
        source_url=source_url[:2000],
        byte_size=len(content),
        content=content,
    )
    db.add(row)
    db.commit()
    _evict_over_quota(db, user_id)
    db.refresh(row)
    return row


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
    for index, row in enumerate(rows):
        total += row.byte_size
        if index >= MAX_DOCUMENTS_PER_USER or total > MAX_STORED_BYTES_PER_USER:
            db.delete(row)
    db.commit()


def stored_bytes(db: Session, user_id: str) -> int:
    total = db.execute(
        select(func.coalesce(func.sum(LiteratureDocument.byte_size), 0)).where(
            LiteratureDocument.user_id == user_id
        )
    ).scalar_one()
    return int(total)


__all__ = [
    "ExtractionTable",
    "WorkspaceTooLargeError",
    "clear_workspace",
    "get_document",
    "get_workspace",
    "save_workspace",
    "store_document",
    "stored_bytes",
    "stored_document_ids",
]
