"""The queryable half of the audit log: writing events to the database and reading them back.

`app.core.audit` writes a structured log line for every security event whether or not a
database session is at hand — that is what an aggregator reads, and it survives the database.
This module keeps the subset that has an account attached, so the account's own Audit Trails
tab can show it. Reads are always scoped to one user id; an event with no account is never
served to anybody, because deciding who it belonged to would mean guessing.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.audit import AuditEvent

logger = logging.getLogger(__name__)

MAX_EVENTS_PER_PAGE = 200

# The three workflows the Audit Trails tab filters by.
Kind = Literal["agent", "human", "export"]

# Which workflow an event belongs to, for the tab's three filters. Anything an agent did on the
# user's behalf is "agent", anything leaving the app as a file is "export", and the rest is the
# person: signing in, opening a paper, deleting one.
AGENT_EVENT_MARKERS = (
    "sent_to_llm",
    "llm.",
    "extraction.",
    "budget_",
    # A chat turn and the tools it ran are the assistant working on the researcher's behalf;
    # deleting a thread is the person, so it is deliberately not matched here.
    "chat.turn",
    "chat.tool_call",
    "chat.message_sent",
)
EXPORT_EVENT_MARKERS = ("export", "_exported", "download")


def classify(event: str) -> Kind:
    if any(marker in event for marker in EXPORT_EVENT_MARKERS):
        return "export"
    if any(marker in event for marker in AGENT_EVENT_MARKERS):
        return "agent"
    return "human"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; the API contract is an aware one."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def record_event(
    db: Session,
    *,
    event: str,
    user_id: str,
    outcome: str = "success",
    client_ip: str | None = None,
    detail: dict[str, object] | None = None,
) -> AuditEvent | None:
    """Persist one event. Never raises: a failed audit write must not fail the user's request.

    The log line has already been written by the caller, so a database problem here degrades
    the tab, not the record.
    """
    try:
        row = AuditEvent(
            user_id=user_id,
            event=event[:100],
            outcome=outcome[:20],
            kind=classify(event),
            client_ip=(client_ip or "")[:64],
            detail_json=json.dumps(detail or {}, default=str),
        )
        db.add(row)
        db.commit()
        _prune(db, user_id)
        return row
    except SQLAlchemyError:
        logger.exception("could not persist an audit event", extra={"event": event})
        db.rollback()
        return None


def _prune(db: Session, user_id: str) -> None:
    """Enforce the retention window, and the ceiling on how many events one account keeps."""
    settings = get_settings()
    cutoff = _now() - timedelta(days=settings.audit_retention_days)
    db.execute(delete(AuditEvent).where(AuditEvent.created_at <= cutoff))
    keep = settings.audit_max_events_per_user
    surplus = list(
        db.execute(
            select(AuditEvent.id)
            .where(AuditEvent.user_id == user_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .offset(keep)
        ).scalars()
    )
    if surplus:
        db.execute(delete(AuditEvent).where(AuditEvent.id.in_(surplus)))
    db.commit()


def recent_events(
    db: Session, user_id: str, *, kind: str | None = None, limit: int = 100
) -> list[AuditEvent]:
    statement = select(AuditEvent).where(AuditEvent.user_id == user_id)
    if kind is not None:
        statement = statement.where(AuditEvent.kind == kind)
    statement = statement.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(
        min(max(limit, 1), MAX_EVENTS_PER_PAGE)
    )
    return list(db.execute(statement).scalars())


def detail_of(row: AuditEvent) -> dict[str, object]:
    try:
        parsed = json.loads(row.detail_json or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def kind_of(row: AuditEvent) -> Kind:
    """The stored kind, narrowed. A row written before a marker changed still reads as one."""
    if row.kind == "agent":
        return "agent"
    if row.kind == "export":
        return "export"
    return "human"


def occurred_at(row: AuditEvent) -> datetime:
    return _as_utc(row.created_at)


__all__ = [
    "MAX_EVENTS_PER_PAGE",
    "Kind",
    "classify",
    "detail_of",
    "kind_of",
    "occurred_at",
    "recent_events",
    "record_event",
]
