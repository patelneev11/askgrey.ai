import logging
from datetime import date

import pytest

from app.core.llm_cost import FALLBACK_PRICE_USD_PER_MTOK, CostMeter, price_of


def test_price_follows_the_published_per_model_rate() -> None:
    # 1M in + 1M out on Sonnet 4.5 at $3/$15.
    assert price_of("claude-sonnet-4-5", 1_000_000, 1_000_000) == pytest.approx(18.0)
    assert price_of("claude-haiku-4-5", 500_000, 0) == pytest.approx(0.5)


def test_an_unknown_model_is_priced_at_the_most_expensive_tier() -> None:
    # Costing an unrecognised model at zero would hide exactly the change worth catching.
    expected = sum(FALLBACK_PRICE_USD_PER_MTOK)
    assert price_of("claude-next", 1_000_000, 1_000_000) == pytest.approx(expected)


def test_usage_accumulates_per_model_across_calls() -> None:
    meter = CostMeter(alert_threshold_usd=0)
    meter.record(model="claude-sonnet-4-5", input_tokens=1000, output_tokens=200, purpose="pdf")
    meter.record(model="claude-haiku-4-5", input_tokens=1000, output_tokens=200, purpose="pubmed")

    usage = meter.snapshot()
    assert usage.calls == 2
    assert usage.input_tokens == 2000
    assert usage.output_tokens == 400
    assert set(usage.by_model) == {"claude-sonnet-4-5", "claude-haiku-4-5"}
    assert usage.cost_usd == pytest.approx(sum(usage.by_model.values()), abs=1e-6)


def test_the_threshold_warns_once_a_day_not_once_a_call(
    caplog: pytest.LogCaptureFixture,
) -> None:
    meter = CostMeter(alert_threshold_usd=0.01)

    with caplog.at_level(logging.WARNING, logger="askgrey.cost"):
        for _ in range(4):
            meter.record(
                model="claude-sonnet-4-5", input_tokens=100_000, output_tokens=0, purpose="pdf"
            )

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert meter.snapshot().alerted is True


def test_a_zero_threshold_disables_the_alert(caplog: pytest.LogCaptureFixture) -> None:
    meter = CostMeter(alert_threshold_usd=0)

    with caplog.at_level(logging.WARNING, logger="askgrey.cost"):
        meter.record(
            model="claude-opus-4-1", input_tokens=1_000_000, output_tokens=1_000_000, purpose="x"
        )

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_the_total_resets_on_a_new_calendar_day() -> None:
    meter = CostMeter(alert_threshold_usd=0.01)
    meter.record(
        model="claude-sonnet-4-5",
        input_tokens=1_000_000,
        output_tokens=0,
        purpose="pdf",
        today=date(2026, 8, 12),
    )
    meter.record(
        model="claude-sonnet-4-5",
        input_tokens=1000,
        output_tokens=0,
        purpose="pdf",
        today=date(2026, 8, 13),
    )

    usage = meter.snapshot()
    assert usage.day == date(2026, 8, 13)
    assert usage.calls == 1
    assert usage.cost_usd == pytest.approx(0.003)
    # A new day is a new budget, so yesterday's alert must not silence today's.
    assert usage.alerted is False


def test_each_call_is_logged_with_the_feature_that_spent_the_money(
    caplog: pytest.LogCaptureFixture,
) -> None:
    meter = CostMeter(alert_threshold_usd=0)

    with caplog.at_level(logging.INFO, logger="askgrey.cost"):
        meter.record(
            model="claude-sonnet-4-5",
            input_tokens=1000,
            output_tokens=100,
            purpose="pdf_extraction",
        )

    line = next(r for r in caplog.records if r.levelno == logging.INFO)
    assert line.__dict__["purpose"] == "pdf_extraction"
    assert line.__dict__["cost_usd"] > 0
