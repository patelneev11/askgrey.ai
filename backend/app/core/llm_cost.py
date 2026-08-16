"""
LLM spend metering.

The existing daily budget counts *calls*, which bounds the worst case but says nothing about
what the day actually cost: a 40-page extraction and a one-line query translation are one
call each and differ by two orders of magnitude in tokens. This meters real token usage
against published per-model prices, warns once when the day crosses a threshold, and exposes
the running total so a spike is visible before the invoice is.

Prices are USD per million tokens and are configuration, not truth — they are checked against
Anthropic's pricing page at the time of writing and must be updated when it changes.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from app.core.config import get_settings

logger = logging.getLogger("askgrey.cost")

PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    # model: (input, output)
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-opus-4-1": (15.0, 75.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
# An unrecognised model must not silently cost nothing; assume the most expensive tier so an
# unnoticed model change trips the alert early rather than late.
FALLBACK_PRICE_USD_PER_MTOK = (15.0, 75.0)


def price_of(model: str, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = PRICES_USD_PER_MTOK.get(model, FALLBACK_PRICE_USD_PER_MTOK)
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


@dataclass
class DailyUsage:
    day: date
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    by_model: dict[str, float] = field(default_factory=dict)
    alerted: bool = False


class CostMeter:
    """Tracks today's token spend and warns once when it crosses `alert_threshold_usd`."""

    def __init__(self, alert_threshold_usd: float) -> None:
        self.alert_threshold_usd = alert_threshold_usd
        self._usage = DailyUsage(day=date.today())
        self._lock = threading.Lock()

    def record(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        purpose: str,
        today: date | None = None,
    ) -> float:
        """Add one call's usage and return its cost in USD."""
        cost = price_of(model, input_tokens, output_tokens)
        day = today or date.today()
        with self._lock:
            if day != self._usage.day:
                self._usage = DailyUsage(day=day)
            usage = self._usage
            usage.calls += 1
            usage.input_tokens += input_tokens
            usage.output_tokens += output_tokens
            usage.cost_usd += cost
            usage.by_model[model] = round(usage.by_model.get(model, 0.0) + cost, 6)
            crossed = (
                self.alert_threshold_usd > 0
                and not usage.alerted
                and usage.cost_usd >= self.alert_threshold_usd
            )
            if crossed:
                usage.alerted = True
            total = usage.cost_usd
            calls = usage.calls

        logger.info(
            "llm call",
            extra={
                "model": model,
                "purpose": purpose,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost, 6),
                "day_cost_usd": round(total, 4),
            },
        )
        if crossed:
            # One line per day, at WARNING, so an alerting rule can be a log query rather
            # than another service to run.
            logger.warning(
                "llm daily spend threshold crossed",
                extra={
                    "day_cost_usd": round(total, 4),
                    "threshold_usd": self.alert_threshold_usd,
                    "calls": calls,
                },
            )
        return cost

    def snapshot(self) -> DailyUsage:
        with self._lock:
            return DailyUsage(
                day=self._usage.day,
                calls=self._usage.calls,
                input_tokens=self._usage.input_tokens,
                output_tokens=self._usage.output_tokens,
                cost_usd=round(self._usage.cost_usd, 4),
                by_model=dict(self._usage.by_model),
                alerted=self._usage.alerted,
            )

    def reset(self) -> None:
        with self._lock:
            self._usage = DailyUsage(day=date.today())


@lru_cache
def get_meter() -> CostMeter:
    return CostMeter(get_settings().llm_daily_cost_alert_usd)
