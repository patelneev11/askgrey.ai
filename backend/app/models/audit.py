import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuditEvent(Base):
    """A security-relevant event, kept so the Audit Trails tab can show what actually happened.

    These rows are the queryable half of `app.core.audit`, which keeps writing a structured log
    line for every event whether or not a row is written; the log is what survives the database
    and what an aggregator reads, the table is what a user can be shown.

    `user_id` is the account the event is *about*, and is what scopes a read: an event with no
    account — a failed sign-in for an address that does not exist, a rate limit hit before any
    account is known — is deliberately left null and is never served to anyone, because
    attributing it would mean guessing.

    `detail` holds the same JSON as the log line: provenance only. Never document text, an
    extracted value, a prompt, a token or a credential.
    """

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), default="success", nullable=False)
    # Which workflow produced it: "agent", "human" or "export". Derived from the event name once,
    # on write, so the tab's filters do not depend on re-deriving it the same way.
    kind: Mapped[str] = mapped_column(String(20), default="human", nullable=False)
    client_ip: Mapped[str] = mapped_column(String(64), default="")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True, nullable=False
    )
