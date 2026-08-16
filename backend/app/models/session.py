import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RefreshSession(Base):
    """One row per issued refresh token, so a token can be rotated and revoked.

    Only the SHA-256 of the token is stored: a database disclosure then yields no usable
    credential. The row id is the token's `jti`, which is what makes reuse detectable —
    a replayed token presents a jti whose row is already revoked.
    """

    __tablename__ = "refresh_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when this token was rotated, purely for forensics on a reuse incident.
    replaced_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
