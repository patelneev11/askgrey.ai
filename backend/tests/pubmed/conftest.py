from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pubmed"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def load_json_fixture(name: str) -> dict[str, Any]:
    return json.loads(load_fixture(name))


class RecordingTransport(httpx.AsyncBaseTransport):
    """
    Serves recorded NCBI responses and records every request that was made.

    Handlers are keyed by E-utility endpoint name (`esearch.fcgi`, ...) and receive the
    parsed query string, so a test can assert on the exact term or id list that was sent.
    """

    def __init__(self, handlers: dict[str, Callable[[dict[str, list[str]]], httpx.Response]]):
        self.handlers = handlers
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        endpoint = request.url.path.rsplit("/", 1)[-1]
        handler = self.handlers.get(endpoint)
        if handler is None:
            raise AssertionError(f"unexpected request to {request.url}")
        return handler(parse_qs(request.url.query.decode()))

    def params_for(self, endpoint: str) -> list[dict[str, list[str]]]:
        return [
            parse_qs(request.url.query.decode())
            for request in self.requests
            if request.url.path.endswith(endpoint)
        ]


def json_response(payload: dict[str, Any], status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


def xml_response(body: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, text=body, headers={"Content-Type": "text/xml"})


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace asyncio.sleep so backoff and rate limiting are observable but instant."""
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    return delays
