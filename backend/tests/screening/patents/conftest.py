from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from app.services.rate_limit import RateLimiter
from app.services.screening.patents import PatentsService, UsptoOdpClient

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "patents"

Query = dict[str, list[str]]
Handler = Callable[[Query], httpx.Response]

API_KEY = "test-odp-key"


def load_json_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


class RecordingTransport(httpx.AsyncBaseTransport):
    """
    Serves one canned search response and records every request the client made.

    Recording the requests is the point: most of what this module must get right is *what was
    sent* — the derived query string, the paging and the filters — so tests assert on the
    captured query parameters rather than on the response.
    """

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(parse_qs(request.url.query.decode()))

    @property
    def queries(self) -> list[Query]:
        return [parse_qs(request.url.query.decode()) for request in self.requests]

    def last_query(self) -> Query:
        assert self.requests, "no request was made"
        return self.queries[-1]


def fixture_handler(name: str) -> Handler:
    return lambda _query: httpx.Response(200, json=load_json_fixture(name))


def status_handler(status_code: int) -> Handler:
    return lambda _query: httpx.Response(status_code, json={"error": "upstream said no"})


def no_match_handler() -> Handler:
    """Upstream's real answer to a search that matched nothing: 404, not an empty 200."""
    return lambda _query: httpx.Response(404, json=load_json_fixture("search_no_match_404.json"))


def timeout_handler() -> Handler:
    def handle(_query: Query) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out")

    return handle


def json_handler(payload: object) -> Handler:
    return lambda _query: httpx.Response(200, json=payload)


def make_service(
    handler: Handler,
    *,
    api_key: str = API_KEY,
    max_attempts: int = 1,
    rate_limiter: RateLimiter | None = None,
) -> tuple[PatentsService, RecordingTransport]:
    """A patents service wired to a recorded transport, so no test touches the network."""
    transport = RecordingTransport(handler)
    client = UsptoOdpClient(
        api_key=api_key,
        transport=transport,
        rate_limiter=rate_limiter or RateLimiter(1000.0),
        max_attempts=max_attempts,
        base_delay=0.0,
    )
    return PatentsService(client=client), transport


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace asyncio.sleep so backoff and rate limiting are observable but instant."""
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    return delays
