"""
In-process sliding-window rate limiting and a daily LLM call budget.

Both are deliberately process-local: the deployment runs a single API process today, and a
shared Redis counter is a different ticket. The important property is that the limiters are
module-level singletons, so they survive across requests — the per-provider limiters inside
the service clients do not, because every route builds a fresh service per request.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import date


class SlidingWindowLimiter:
    """Allows `limit` events per `window_seconds` for each key."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def retry_after(self, key: str, *, now: float | None = None) -> float | None:
        """Record the event and return None, or return the seconds to wait if over limit."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            events = self._events[key]
            while events and moment - events[0] >= self.window_seconds:
                events.popleft()
            if len(events) >= self.limit:
                return max(0.0, self.window_seconds - (moment - events[0]))
            events.append(moment)
            if not events:
                del self._events[key]
        return None

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


class DailyBudget:
    """Caps how many billable LLM calls one key may trigger per calendar day (UTC)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._day: date | None = None
        self._used: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def consume(self, key: str, *, today: date | None = None) -> bool:
        """Return True if the call is within budget, having counted it."""
        day = today or date.today()
        with self._lock:
            if day != self._day:
                self._day = day
                self._used.clear()
            if self._used[key] >= self.limit:
                return False
            self._used[key] += 1
            return True

    def remaining(self, key: str) -> int:
        with self._lock:
            return max(0, self.limit - self._used[key])

    def reset(self) -> None:
        with self._lock:
            self._used.clear()
            self._day = None
