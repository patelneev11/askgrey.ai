"""The assistant's dollar caps: what one account may spend on chat in a day and a month."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.services.chat.spend import SpendStatus, TurnBudget, record_usage, status

TODAY = date(2026, 8, 13)
MONTH_START = date(2026, 8, 1)
LAST_MONTH = date(2026, 7, 31)
MODEL = "claude-sonnet-4-5"


def settings_with(**overrides: float) -> Settings:
    return get_settings().model_copy(update=overrides)


def test_usage_accumulates_into_one_row_per_account_per_day(db: Session) -> None:
    first = record_usage(
        db, user_id="u1", model=MODEL, input_tokens=1000, output_tokens=500, today=TODAY
    )
    second = record_usage(
        db, user_id="u1", model=MODEL, input_tokens=2000, output_tokens=100, today=TODAY
    )

    assert first > 0 and second > 0
    spent = status(db, user_id="u1", today=TODAY)
    assert spent.daily_spent_usd == pytest.approx(first + second, abs=1e-6)
    # Another account's turns are not this account's spend.
    record_usage(db, user_id="u2", model=MODEL, input_tokens=9000, output_tokens=9000, today=TODAY)
    assert status(db, user_id="u1", today=TODAY).daily_spent_usd == pytest.approx(
        first + second, abs=1e-6
    )


def test_a_zero_token_call_is_not_written_down(db: Session) -> None:
    """A turn that failed before the model answered has nothing to charge for."""
    TurnBudget(db, "u1").record(MODEL, 0, 0)

    assert status(db, user_id="u1", today=TODAY).daily_spent_usd == 0.0


def test_the_month_counts_this_month_only(db: Session) -> None:
    record_usage(
        db, user_id="u1", model=MODEL, input_tokens=1000, output_tokens=1000, today=LAST_MONTH
    )
    record_usage(db, user_id="u1", model=MODEL, input_tokens=1000, output_tokens=1000, today=TODAY)

    spent = status(db, user_id="u1", today=TODAY)
    assert spent.monthly_spent_usd == pytest.approx(spent.daily_spent_usd, abs=1e-6)
    assert spent.monthly_spent_usd > 0

    # A day inside the month but before today still counts against the month, not the day.
    record_usage(
        db, user_id="u1", model=MODEL, input_tokens=1000, output_tokens=1000, today=MONTH_START
    )
    later = status(db, user_id="u1", today=TODAY)
    assert later.monthly_spent_usd > later.daily_spent_usd


@pytest.mark.parametrize(
    ("daily_cap", "monthly_cap", "daily", "monthly", "expected"),
    [
        (2.0, 25.0, 1.999, 5.0, ""),
        (2.0, 25.0, 2.0, 5.0, "daily"),
        (2.0, 25.0, 2.5, 5.0, "daily"),
        (2.0, 25.0, 0.5, 25.0, "monthly"),
        # A cap of zero is not enforced: an unmetered deployment must not read as exhausted.
        (0.0, 0.0, 900.0, 900.0, ""),
    ],
)
def test_a_cap_is_reached_at_the_boundary_not_before_it(
    daily_cap: float, monthly_cap: float, daily: float, monthly: float, expected: str
) -> None:
    spent = SpendStatus(
        daily_spent_usd=daily,
        daily_cap_usd=daily_cap,
        monthly_spent_usd=monthly,
        monthly_cap_usd=monthly_cap,
    )

    assert spent.exhausted_cap == expected
    assert spent.exhausted is bool(expected)
    if expected:
        # The message names the cap, the amount and when it comes back.
        assert expected in spent.message()
        assert "resets" in spent.message()
        assert "other tabs still work" in spent.message()
    else:
        assert spent.message() == ""


def test_remaining_is_never_negative() -> None:
    spent = SpendStatus(
        daily_spent_usd=3.0, daily_cap_usd=2.0, monthly_spent_usd=30.0, monthly_cap_usd=25.0
    )

    assert spent.daily_remaining_usd == 0.0
    assert spent.monthly_remaining_usd == 0.0


def test_a_turn_is_blocked_once_the_ledger_passes_the_cap(db: Session, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.chat.spend.get_settings",
        lambda: settings_with(chat_daily_cost_cap_usd=0.01, chat_monthly_cost_cap_usd=1.0),
    )
    budget = TurnBudget(db, "u1")
    assert budget.blocked() == ""

    budget.record(MODEL, 10_000, 10_000)

    blocked = budget.blocked()
    assert "daily assistant budget" in blocked
