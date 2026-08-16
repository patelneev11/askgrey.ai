import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SavedProtocol(Base):
    """
    A protocol a researcher has saved, owned by exactly one account.

    The row holds only the pointer to the latest version; the content of every version, including
    the current one, lives in `protocol_versions`, so an edit never overwrites what was there
    before.
    """

    __tablename__ = "saved_protocols"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProtocolVersion(Base):
    """
    One immutable snapshot of a protocol, plus the changelog describing how it differs from the
    version before it.

    Storing the full protocol per version rather than only the diff keeps history readable
    without replaying edits, and keeps a corrupted diff from making an old version unrecoverable.
    """

    __tablename__ = "protocol_versions"
    __table_args__ = (UniqueConstraint("protocol_id", "version", name="uq_protocol_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    protocol_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("saved_protocols.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # JSON text rather than a JSON column: the app targets SQLite in tests and Postgres in
    # production, and the payload is only ever read back whole.
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    changes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    change_summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    author_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
