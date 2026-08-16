from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "clinicaltrials"

Query = dict[str, list[str]]
Handler = Callable[[Query], httpx.Response]


def load_json_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


class RecordingTransport(httpx.AsyncBaseTransport):
    """
    Serves recorded `/studies` responses in order and keeps every request for assertions.

    The v2 API is a single endpoint, so responses are queued rather than keyed by path; the
    last handler repeats once the queue is exhausted.
    """

    def __init__(self, *handlers: Handler):
        self.handlers = list(handlers)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.handlers:
            raise AssertionError(f"unexpected request to {request.url}")
        index = min(len(self.requests) - 1, len(self.handlers) - 1)
        return self.handlers[index](parse_qs(request.url.query.decode()))

    @property
    def queries(self) -> list[Query]:
        return [parse_qs(request.url.query.decode()) for request in self.requests]


def json_response(payload: dict[str, Any], status_code: int = 200) -> Handler:
    return lambda _query: httpx.Response(status_code, json=payload)


def fixture_response(name: str) -> Handler:
    return lambda _query: httpx.Response(200, json=load_json_fixture(name))


def error_response(status_code: int, body: str = "upstream failure") -> Handler:
    return lambda _query: httpx.Response(status_code, text=body)


def transport_error(message: str = "connection reset") -> Handler:
    def handle(_query: Query) -> httpx.Response:
        raise httpx.ConnectError(message)

    return handle


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace asyncio.sleep so backoff and rate limiting are observable but instant."""
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    return delays
