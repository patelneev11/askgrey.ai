"""
Per-dependency call health.

Every outbound call to PubMed, PubChem, ClinicalTrials.gov, grants.gov, SBIR.gov and Claude
is recorded here, so "is it us or is it them?" is answerable without reading logs. The window
is the last N calls rather than a time bucket: a dependency nobody has called in an hour has
no opinion about its own health, and pretending otherwise pages someone at 3am.

Process-local, like the rate limiters — with more than one API process this becomes a shared
counter, which is a separate ticket.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Literal

import httpx
from httpx._client import USE_CLIENT_DEFAULT, UseClientDefault
from httpx._types import AuthTypes

Status = Literal["healthy", "degraded", "unhealthy", "unused"]

WINDOW = 50
# Below this many calls the error rate is noise; one failed call out of two is not an outage.
MIN_CALLS_FOR_STATUS = 5
DEGRADED_ERROR_RATE = 0.2
UNHEALTHY_ERROR_RATE = 0.5


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: str
    status: Status
    calls: int
    failures: int
    error_rate: float
    p95_latency_ms: float | None
    last_error: str | None
    last_error_age_seconds: float | None


class DependencyHealth:
    def __init__(self, window: int = WINDOW) -> None:
        self.window = window
        self._outcomes: dict[str, deque[bool]] = defaultdict(lambda: deque(maxlen=window))
        self._latencies: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=window))
        self._last_error: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def record(
        self, provider: str, *, ok: bool, duration_ms: float, error: str | None = None
    ) -> None:
        with self._lock:
            self._outcomes[provider].append(ok)
            self._latencies[provider].append(duration_ms)
            if not ok and error:
                self._last_error[provider] = (error, time.time())

    def snapshot(self, providers: tuple[str, ...] = ()) -> list[ProviderSnapshot]:
        with self._lock:
            names = sorted(set(providers) | set(self._outcomes))
            return [self._snapshot_of(name) for name in names]

    def reset(self) -> None:
        with self._lock:
            self._outcomes.clear()
            self._latencies.clear()
            self._last_error.clear()

    def _snapshot_of(self, provider: str) -> ProviderSnapshot:
        outcomes = self._outcomes.get(provider, deque())
        latencies = self._latencies.get(provider, deque())
        calls = len(outcomes)
        failures = sum(1 for ok in outcomes if not ok)
        error_rate = failures / calls if calls else 0.0
        error = self._last_error.get(provider)
        return ProviderSnapshot(
            provider=provider,
            status=_status_for(calls, error_rate),
            calls=calls,
            failures=failures,
            error_rate=round(error_rate, 3),
            p95_latency_ms=_percentile(latencies, 0.95),
            last_error=error[0] if error else None,
            last_error_age_seconds=round(time.time() - error[1], 1) if error else None,
        )


def _status_for(calls: int, error_rate: float) -> Status:
    if calls == 0:
        return "unused"
    if calls < MIN_CALLS_FOR_STATUS:
        return "healthy"
    if error_rate >= UNHEALTHY_ERROR_RATE:
        return "unhealthy"
    if error_rate >= DEGRADED_ERROR_RATE:
        return "degraded"
    return "healthy"


def _percentile(values: deque[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return round(ordered[index], 1)


health = DependencyHealth()

# Named here so a provider nobody has called yet still appears in the status response as
# `unused` rather than silently missing.
KNOWN_PROVIDERS = (
    "anthropic",
    "clinicaltrials",
    "grants_gov",
    "pdf_fetch",
    "pubchem",
    "pubmed",
    "sbir",
)


class MonitoredAsyncClient(httpx.AsyncClient):
    """An `httpx.AsyncClient` that reports every call's outcome to `health`.

    5xx and transport failures count against the dependency; 4xx does not, because a rejected
    query is our bug or the user's, not the provider being down. 429 does count, since being
    throttled is an availability problem for the caller either way.
    """

    def __init__(
        self,
        provider: str,
        *,
        timeout: float | httpx.Timeout = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
    ) -> None:
        super().__init__(
            timeout=timeout,
            transport=transport,
            headers=headers,
            follow_redirects=follow_redirects,
        )
        self._provider = provider

    async def send(
        self,
        request: httpx.Request,
        *,
        stream: bool = False,
        auth: AuthTypes | UseClientDefault | None = USE_CLIENT_DEFAULT,
        follow_redirects: bool | UseClientDefault = USE_CLIENT_DEFAULT,
    ) -> httpx.Response:
        started = time.perf_counter()
        try:
            response = await super().send(
                request, stream=stream, auth=auth, follow_redirects=follow_redirects
            )
        except httpx.HTTPError as exc:
            health.record(
                self._provider,
                ok=False,
                duration_ms=(time.perf_counter() - started) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        failed = response.status_code >= 500 or response.status_code == 429
        health.record(
            self._provider,
            ok=not failed,
            duration_ms=(time.perf_counter() - started) * 1000,
            error=f"HTTP {response.status_code}" if failed else None,
        )
        return response
