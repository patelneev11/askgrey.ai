from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from app.services.grants.grants_gov import GrantsGovClient
from app.services.grants.models import GrantOpportunity, GrantProgram, GrantSource, GrantStatus
from app.services.grants.sbir import SbirClient
from app.services.grants.service import GrantsService
from app.services.rate_limit import RateLimiter

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "grants"

# Every fixture was recorded while the search2 hits below were open, so the suite pins "today"
# instead of letting real time turn open opportunities into closed ones.
TODAY = date(2026, 8, 13)

Handler = Callable[[httpx.Request], httpx.Response]


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def search2_fixture() -> dict[str, Any]:
    payload = load_fixture("search2_nih_sbir.json")
    assert isinstance(payload, dict)
    return payload


class RoutingTransport(httpx.AsyncBaseTransport):
    """
    Dispatches by URL path so one transport can serve both providers.

    grants.gov `fetchOpportunity` is keyed by the requested opportunity id, because the service
    fires those concurrently and their arrival order is not deterministic.
    """

    def __init__(
        self,
        *,
        search2: Handler | list[Handler] | None = None,
        fetch: Handler | None = None,
        solicitations: Handler | list[Handler] | None = None,
    ) -> None:
        self.search2 = search2
        self.fetch = fetch or default_fetch
        self.solicitations = solicitations
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/search2"):
            return self._serve(self.search2, "search2", request)
        if path.endswith("/fetchOpportunity"):
            return self.fetch(request)
        if path.endswith("/solicitations"):
            return self._serve(self.solicitations, "solicitations", request)
        raise AssertionError(f"unexpected request to {request.url}")

    def _serve(
        self, handler: Handler | list[Handler] | None, label: str, request: httpx.Request
    ) -> httpx.Response:
        if handler is None:
            raise AssertionError(f"unexpected {label} request")
        if callable(handler):
            return handler(request)
        index = min(self._count(label), len(handler) - 1)
        return handler[index](request)

    def _count(self, label: str) -> int:
        return sum(1 for request in self.requests[:-1] if request.url.path.endswith(f"/{label}"))

    def payloads(self, path_suffix: str) -> list[dict[str, Any]]:
        return [
            json.loads(request.content.decode())
            for request in self.requests
            if request.url.path.endswith(path_suffix)
        ]

    def queries(self, path_suffix: str) -> list[dict[str, list[str]]]:
        return [
            parse_qs(request.url.query.decode())
            for request in self.requests
            if request.url.path.endswith(path_suffix)
        ]


def json_response(payload: Any, status_code: int = 200) -> Handler:
    return lambda _request: httpx.Response(status_code, json=payload)


def fixture_response(name: str) -> Handler:
    return lambda _request: httpx.Response(200, json=load_fixture(name))


def error_response(status_code: int, body: str = "upstream failure") -> Handler:
    return lambda _request: httpx.Response(status_code, text=body)


def transport_error(message: str = "connection reset") -> Handler:
    def handle(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(message)

    return handle


def default_fetch(request: httpx.Request) -> httpx.Response:
    """Serve the recorded detail for a requested id, or an empty synopsis if none exists."""
    opportunity_id = json.loads(request.content.decode())["opportunityId"]
    path = FIXTURES / f"fetch_opportunity_{opportunity_id}.json"
    if not path.exists():
        return httpx.Response(200, json={"errorcode": 0, "data": {"synopsis": {}}})
    return httpx.Response(200, json=json.loads(path.read_text()))


def make_service(
    *,
    search2: Handler | list[Handler] | None = None,
    fetch: Handler | None = None,
    solicitations: Handler | list[Handler] | None = None,
    max_attempts: int = 1,
    enrich_limit: int = 25,
    ranker: Any = None,
) -> tuple[GrantsService, RoutingTransport]:
    transport = RoutingTransport(search2=search2, fetch=fetch, solicitations=solicitations)
    service = GrantsService(
        grants_gov=GrantsGovClient(
            transport=transport, rate_limiter=RateLimiter(1000.0), max_attempts=max_attempts
        ),
        sbir=SbirClient(
            transport=transport, rate_limiter=RateLimiter(1000.0), max_attempts=max_attempts
        ),
        ranker=ranker,
        enrich_limit=enrich_limit,
        today=TODAY,
    )
    return service, transport


def opportunity(
    title: str,
    *,
    source: GrantSource = GrantSource.GRANTS_GOV,
    opportunity_id: str = "1",
    agency: str = "National Institutes of Health",
    program: GrantProgram | None = GrantProgram.SBIR,
    status: GrantStatus | None = GrantStatus.OPEN,
    close_date: date | None = date(2026, 12, 1),
    topic_description: str = "",
    funding_ceiling: int | None = None,
) -> GrantOpportunity:
    return GrantOpportunity(
        source=source,
        opportunity_id=opportunity_id,
        number=f"NUM-{opportunity_id}",
        title=title,
        agency=agency,
        program=program,
        status=status,
        close_date=close_date,
        topic_description=topic_description,
        funding_ceiling=funding_ceiling,
    )


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace asyncio.sleep so backoff is observable but instant."""
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    return delays
