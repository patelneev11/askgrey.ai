import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SavedArtifact(Base):
    """
    One agent output a researcher chose to keep, owned by exactly one account.

    Nothing lands here unless the researcher asks for it: the tabs render their results from the
    response they already have, and a row appears only on an explicit save. `kind` names which
    output it is, and the payload is the response body of that endpoint, validated against the
    same model on the way in and out so a reopened artifact still carries the caveats that were
    shown when it was produced.
    """

    __tablename__ = "saved_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # JSON text rather than a JSON column: the app targets SQLite in tests and Postgres in
    # production, and the payload is only ever read back whole.
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
