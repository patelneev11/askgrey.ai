"""
Per-account spend caps for the assistant, in dollars rather than calls.

The existing daily budget counts calls, which is the wrong unit for a chat: one question can run
six tool steps over 40 kB of results, and the next can be a two-line follow-up. These caps are
metered in USD against the same published prices the cost log uses, persisted per account so a
restart or a second replica cannot hand the budget back, and checked in three places:

- before a turn starts, so an exhausted account is refused for the price of a database read;
- between tool steps, so one runaway turn stops at the ceiling instead of after it;
- after the turn, when the real token usage is known and written down.

A turn can therefore overshoot its cap by at most one model call, which is the price of not
truncating an answer mid-sentence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.llm_cost import price_of
from app.models.spend import LlmSpend

CHAT_PURPOSE = "chat"


@dataclass(frozen=True)
class SpendStatus:
    """What this account has spent and what is left, as the tab shows it."""

    daily_spent_usd: float
    daily_cap_usd: float
    monthly_spent_usd: float
    monthly_cap_usd: float

    @property
    def daily_remaining_usd(self) -> float:
        if self.daily_cap_usd <= 0:
            return 0.0
        return max(self.daily_cap_usd - self.daily_spent_usd, 0.0)

    @property
    def monthly_remaining_usd(self) -> float:
        if self.monthly_cap_usd <= 0:
            return 0.0
        return max(self.monthly_cap_usd - self.monthly_spent_usd, 0.0)

    @property
    def exhausted_cap(self) -> str:
        """Which cap is used up, or an empty string while there is room under both."""
        if self.daily_cap_usd > 0 and self.daily_spent_usd >= self.daily_cap_usd:
            return "daily"
        if self.monthly_cap_usd > 0 and self.monthly_spent_usd >= self.monthly_cap_usd:
            return "monthly"
        return ""

    @property
    def exhausted(self) -> bool:
        return bool(self.exhausted_cap)

    def message(self) -> str:
        if self.exhausted_cap == "daily":
            return (
                f"This account has used its ${self.daily_cap_usd:.2f} daily assistant budget "
                f"(${self.daily_spent_usd:.2f} spent). It resets at 00:00 UTC; the other tabs "
                "still work."
            )
        if self.exhausted_cap == "monthly":
            return (
                f"This account has used its ${self.monthly_cap_usd:.2f} monthly assistant budget "
                f"(${self.monthly_spent_usd:.2f} spent). It resets on the first of next month; "
                "the other tabs still work."
            )
        return ""


class TurnBudget:
    """One turn's view of the caps: what it has spent, and whether it may keep going.

    Holds the request's session, so the ledger write and the cap check are the same numbers the
    next turn will read. Constructed per request; not shared between accounts.
    """

    def __init__(self, db: Session, user_id: str) -> None:
        self.db = db
        self.user_id = user_id

    def status(self) -> SpendStatus:
        return status(self.db, user_id=self.user_id)

    def blocked(self) -> str:
        """The message to show if a cap is used up, or an empty string to continue."""
        return self.status().message()

    def record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        if input_tokens <= 0 and output_tokens <= 0:
            return
        record_usage(
            self.db,
            user_id=self.user_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _total(db: Session, *, user_id: str, since: date, until: date) -> float:
    rows = db.execute(
        select(LlmSpend.cost_usd).where(
            LlmSpend.user_id == user_id,
            LlmSpend.purpose == CHAT_PURPOSE,
            LlmSpend.day >= since,
            LlmSpend.day <= until,
        )
    ).all()
    return float(sum(row[0] for row in rows))


def status(db: Session, *, user_id: str, today: date | None = None) -> SpendStatus:
    settings = get_settings()
    day = today or datetime.now(timezone.utc).date()
    daily = _total(db, user_id=user_id, since=day, until=day)
    monthly = _total(db, user_id=user_id, since=_month_start(day), until=day)
    return SpendStatus(
        daily_spent_usd=round(daily, 6),
        daily_cap_usd=settings.chat_daily_cost_cap_usd,
        monthly_spent_usd=round(monthly, 6),
        monthly_cap_usd=settings.chat_monthly_cost_cap_usd,
    )


def record_usage(
    db: Session,
    *,
    user_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    today: date | None = None,
) -> float:
    """Add one model call's usage to the account's ledger and return its cost in USD."""
    cost = price_of(model, input_tokens, output_tokens)
    day = today or datetime.now(timezone.utc).date()
    row = db.execute(
        select(LlmSpend).where(
            LlmSpend.user_id == user_id,
            LlmSpend.day == day,
            LlmSpend.purpose == CHAT_PURPOSE,
        )
    ).scalar_one_or_none()
    if row is None:
        row = LlmSpend(user_id=user_id, day=day, purpose=CHAT_PURPOSE)
        db.add(row)
        try:
            db.flush()
        except IntegrityError:
            # Two turns for the same account opened the day's row at once; adopt the winner.
            db.rollback()
            row = db.execute(
                select(LlmSpend).where(
                    LlmSpend.user_id == user_id,
                    LlmSpend.day == day,
                    LlmSpend.purpose == CHAT_PURPOSE,
                )
            ).scalar_one()
    row.calls += 1
    row.input_tokens += input_tokens
    row.output_tokens += output_tokens
    row.cost_usd = round(row.cost_usd + cost, 6)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    return cost
