from __future__ import annotations

import httpx
import pytest

from app.core.dependency_health import (
    MIN_CALLS_FOR_STATUS,
    DependencyHealth,
    MonitoredAsyncClient,
    ProviderSnapshot,
    health,
)

pytestmark = pytest.mark.asyncio


def only(tracker: DependencyHealth, provider: str) -> ProviderSnapshot:
    return next(s for s in tracker.snapshot((provider,)) if s.provider == provider)


async def test_a_provider_nobody_called_is_unused_rather_than_healthy() -> None:
    tracker = DependencyHealth()

    assert only(tracker, "pubmed").status == "unused"


async def test_a_handful_of_calls_is_too_little_evidence_to_declare_an_outage() -> None:
    tracker = DependencyHealth()
    tracker.record("pubmed", ok=False, duration_ms=10, error="HTTP 503")

    # One failure out of one call would otherwise read as a 100% error rate.
    assert only(tracker, "pubmed").status == "healthy"


async def test_status_tracks_the_error_rate_once_there_are_enough_calls() -> None:
    tracker = DependencyHealth()
    for index in range(MIN_CALLS_FOR_STATUS * 2):
        tracker.record("pubchem", ok=index % 5 != 0, duration_ms=10, error="HTTP 500")
    assert only(tracker, "pubchem").status == "degraded"

    for _ in range(MIN_CALLS_FOR_STATUS * 2):
        tracker.record("pubchem", ok=False, duration_ms=10, error="HTTP 500")
    snapshot = only(tracker, "pubchem")
    assert snapshot.status == "unhealthy"
    assert snapshot.last_error == "HTTP 500"
    assert snapshot.last_error_age_seconds is not None


async def test_the_window_forgets_an_outage_the_dependency_has_recovered_from() -> None:
    tracker = DependencyHealth(window=10)
    for _ in range(10):
        tracker.record("sbir", ok=False, duration_ms=10, error="HTTP 500")
    for _ in range(10):
        tracker.record("sbir", ok=True, duration_ms=10)

    assert only(tracker, "sbir").status == "healthy"


async def test_latency_is_reported_at_the_tail_not_the_mean() -> None:
    tracker = DependencyHealth()
    for value in [10.0] * 18 + [900.0, 950.0]:
        tracker.record("grants_gov", ok=True, duration_ms=value)

    assert only(tracker, "grants_gov").p95_latency_ms == 900.0


async def test_the_client_counts_server_errors_and_throttling_against_the_provider() -> None:
    health.reset()
    statuses = iter([500, 429, 200])
    transport = httpx.MockTransport(lambda _request: httpx.Response(next(statuses)))

    async with MonitoredAsyncClient("pubmed", transport=transport) as client:
        for _ in range(3):
            await client.get("https://eutils.example/x")

    snapshot = next(s for s in health.snapshot() if s.provider == "pubmed")
    assert (snapshot.calls, snapshot.failures) == (3, 2)
    assert snapshot.last_error == "HTTP 429"


async def test_a_rejected_query_is_our_fault_and_does_not_mark_the_provider_down() -> None:
    health.reset()
    transport = httpx.MockTransport(lambda _request: httpx.Response(400))

    async with MonitoredAsyncClient("pubchem", transport=transport) as client:
        await client.get("https://pubchem.example/x")

    assert next(s for s in health.snapshot() if s.provider == "pubchem").failures == 0


async def test_a_transport_failure_is_recorded_and_still_raised() -> None:
    health.reset()

    def explode(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("no route")

    async with MonitoredAsyncClient("anthropic", transport=httpx.MockTransport(explode)) as client:
        with pytest.raises(httpx.ConnectTimeout):
            await client.get("https://api.anthropic.example/x")

    snapshot = next(s for s in health.snapshot() if s.provider == "anthropic")
    assert snapshot.failures == 1
    assert snapshot.last_error is not None and "ConnectTimeout" in snapshot.last_error
