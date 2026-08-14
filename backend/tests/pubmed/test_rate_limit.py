from __future__ import annotations

import asyncio

import pytest

from app.core.config import Settings
from app.services.pubmed.errors import EntrezRequestError
from app.services.rate_limit import RateLimiter, retry_with_backoff


class FakeClock:
    """Monotonic clock that only advances when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.now += delay


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(asyncio, "sleep", fake.sleep)
    return fake


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_spaces_requests_by_the_configured_interval(self, clock: FakeClock) -> None:
        limiter = RateLimiter(3.0, time_source=clock)
        for _ in range(4):
            await limiter.acquire()

        # The first acquisition is free; the next three each wait out a third of a second.
        assert clock.sleeps == pytest.approx([1 / 3, 1 / 3, 1 / 3])

    @pytest.mark.asyncio
    async def test_api_key_rate_allows_tighter_spacing(self, clock: FakeClock) -> None:
        limiter = RateLimiter(10.0, time_source=clock)
        await limiter.acquire()
        await limiter.acquire()
        assert clock.sleeps == pytest.approx([0.1])

    @pytest.mark.asyncio
    async def test_does_not_sleep_when_caller_is_already_slow(self, clock: FakeClock) -> None:
        limiter = RateLimiter(3.0, time_source=clock)
        await limiter.acquire()
        clock.now += 5.0
        await limiter.acquire()
        assert clock.sleeps == []

    def test_rate_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            RateLimiter(0)

    def test_settings_pick_the_ncbi_documented_rates(self) -> None:
        assert Settings(ncbi_api_key="").entrez_rate_limit == 3.0
        assert Settings(ncbi_api_key="abc123").entrez_rate_limit == 10.0


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_backs_off_exponentially_then_succeeds(self, clock: FakeClock) -> None:
        attempts = 0

        async def operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise EntrezRequestError("throttled", status_code=429)
            return "ok"

        result = await retry_with_backoff(
            operation, should_retry=lambda _: True, base_delay=0.5, max_attempts=4
        )

        assert result == "ok"
        assert attempts == 3
        assert clock.sleeps == pytest.approx([0.5, 1.0])

    @pytest.mark.asyncio
    async def test_gives_up_after_max_attempts(self, clock: FakeClock) -> None:
        attempts = 0

        async def operation() -> str:
            nonlocal attempts
            attempts += 1
            raise EntrezRequestError("throttled", status_code=429)

        with pytest.raises(EntrezRequestError):
            await retry_with_backoff(
                operation, should_retry=lambda _: True, base_delay=0.5, max_attempts=3
            )

        assert attempts == 3
        assert clock.sleeps == pytest.approx([0.5, 1.0])

    @pytest.mark.asyncio
    async def test_delay_is_capped(self, clock: FakeClock) -> None:
        async def operation() -> str:
            raise EntrezRequestError("throttled", status_code=429)

        with pytest.raises(EntrezRequestError):
            await retry_with_backoff(
                operation,
                should_retry=lambda _: True,
                base_delay=4.0,
                max_delay=8.0,
                max_attempts=4,
            )

        assert clock.sleeps == pytest.approx([4.0, 8.0, 8.0])

    @pytest.mark.asyncio
    async def test_non_retryable_failure_propagates_immediately(self, clock: FakeClock) -> None:
        attempts = 0

        async def operation() -> str:
            nonlocal attempts
            attempts += 1
            raise EntrezRequestError("bad request", status_code=400)

        with pytest.raises(EntrezRequestError):
            await retry_with_backoff(operation, should_retry=lambda _: False)

        assert attempts == 1
        assert clock.sleeps == []
