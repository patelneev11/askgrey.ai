import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LiteratureWorkspace(Base):
    """The Literature tab's saved state: one row per user.

    The table and the source list are stored as JSON text rather than relational rows: the
    extraction schema is owned by `app.services.pdf_extraction.models` and is validated on
    the way in, so shredding it into columns here would only duplicate that contract.
    """

    __tablename__ = "literature_workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    goal: Mapped[str] = mapped_column(Text, default="")
    sources_json: Mapped[str] = mapped_column(Text, default="[]")
    table_json: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class LiteratureDocument(Base):
    """The bytes of a paper the user added, kept so its cited pages can be re-rendered.

    A paper reached by link is fetched server-side, and an uploaded one is gone as soon as
    the tab reloads, so without this the citation viewer can only ever show a quote. Rows
    are owned by a user and are only ever served back to that user — this is a store of
    already-fetched bytes, never a fetcher of caller-supplied URLs.
    """

    __tablename__ = "literature_documents"
    __table_args__ = (UniqueConstraint("user_id", "document_id", name="uq_literature_document"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # The extraction document id, which is a digest of the bytes themselves.
    document_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(500), default="")
    source_url: Mapped[str] = mapped_column(String(2000), default="")
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
