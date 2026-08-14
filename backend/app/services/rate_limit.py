from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class RateLimiter:
    """
    Serializing rate limiter: at most `rate` acquisitions per second across all callers.

    The public data providers this product talks to (NCBI, PubChem) enforce their limits per
    key or per IP rather than per connection, so the spacing is applied globally by holding a
    lock while sleeping out the remainder of the interval.
    """

    def __init__(self, rate: float, *, time_source: Callable[[], float] | None = None) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = rate
        self._min_interval = 1.0 / rate
        self._now = time_source or time.monotonic
        self._lock = asyncio.Lock()
        self._next_available = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = self._now()
            wait_for = self._next_available - now
            if wait_for > 0:
                await asyncio.sleep(wait_for)
                now = self._now()
            self._next_available = max(now, self._next_available) + self._min_interval


async def retry_with_backoff(
    operation: Callable[[], Awaitable[T]],
    *,
    should_retry: Callable[[BaseException], bool],
    max_attempts: int = 4,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
) -> T:
    """
    Retry `operation` with exponential backoff while `should_retry` accepts the failure.

    Providers answer bursts over the limit with HTTP 429 and shed load with 5xx, so the caller
    classifies which exceptions are worth another attempt and this only owns the timing.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return await operation()
        except BaseException as exc:
            if attempt >= max_attempts or not should_retry(exc):
                raise
            await asyncio.sleep(min(base_delay * 2 ** (attempt - 1), max_delay))
