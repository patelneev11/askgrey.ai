from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LlmSpend(Base):
    """
    What one account spent at Anthropic on one day, for one feature.

    The in-process cost meter (`app.core.llm_cost`) totals the whole deployment and forgets it on
    restart, which is right for an alert and useless as a per-account cap: a restart would hand
    every account its budget back, and a second replica would never see the first one's spend.
    One row per account, day and purpose is small enough to write on every call and lets a cap be
    enforced across restarts and replicas.
    """

    __tablename__ = "llm_spend"
    __table_args__ = (UniqueConstraint("user_id", "day", "purpose", name="uq_llm_spend_scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # UTC calendar day, matching the daily call budget's reset at 00:00 UTC.
    day: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="chat")
    calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
