"""
When to stop paying the scope classifier for an account that keeps asking for other things.

The classifier is cheap per message and unbounded per account: a script that sends a thousand
off-topic questions is refused a thousand times, and every refusal the patterns did not catch
costs a model call. The per-account spend caps do not help, because a refused turn never reaches
the chat budget they meter.

So the refusals themselves are the signal. They are already written to the audit trail, which
makes the count a single indexed read: past the threshold, the classifier is withheld for the
rest of the window and the gate falls back to the research vocabulary, which refuses a message
with no research term in it for free. An account doing research work never sees this — it has to
be refused repeatedly first — and the window expires on its own.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.audit import AuditEvent

OUT_OF_SCOPE_EVENT = "chat.out_of_scope"


def recent_refusals(db: Session, user_id: str, *, window: timedelta) -> int:
    since = datetime.now(timezone.utc) - window
    total = db.execute(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.user_id == user_id,
            AuditEvent.event == OUT_OF_SCOPE_EVENT,
            AuditEvent.created_at >= since,
        )
    ).scalar_one()
    return int(total)


def classifier_available(db: Session, user_id: str) -> bool:
    """Whether this account's next message is worth a classifier call."""
    settings = get_settings()
    threshold = settings.chat_scope_refusals_before_cooldown
    if threshold <= 0:
        return True
    window = timedelta(minutes=settings.chat_scope_cooldown_minutes)
    return recent_refusals(db, user_id, window=window) < threshold
