from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pubchem"

Body = dict[str, list[str]]
Handler = Callable[[Body], httpx.Response]


def load_json_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


class RecordingTransport(httpx.AsyncBaseTransport):
    """
    Serves recorded PUG-REST responses and records every request that was made.

    Handlers are keyed by the part of the path after `/rest/pug/` and receive the parsed form
    body, so a test can assert on the exact name, SMILES or CID list that was sent.
    """

    def __init__(self, handlers: dict[str, Handler]):
        self.handlers = handlers
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = self._key(request)
        handler = self.handlers.get(key)
        if handler is None:
            raise AssertionError(f"unexpected request to {key} ({request.url})")
        return handler(parse_qs(request.content.decode()))

    @staticmethod
    def _key(request: httpx.Request) -> str:
        return request.url.path.split("/rest/pug/", 1)[-1].lstrip("/")

    def bodies_for(self, key: str) -> list[Body]:
        return [
            parse_qs(request.content.decode())
            for request in self.requests
            if self._key(request) == key
        ]

    def queries_for(self, key: str) -> list[Body]:
        return [
            parse_qs(request.url.query.decode())
            for request in self.requests
            if self._key(request) == key
        ]


def json_response(payload: dict[str, Any], status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


def fixture_response(name: str) -> Handler:
    return lambda _body: json_response(load_json_fixture(name))


def fault_response(code: str, status_code: int) -> Handler:
    """A PUG-REST fault body, which is how PubChem reports both bad input and no match."""
    payload = {"Fault": {"Code": code, "Message": code}}
    return lambda _body: json_response(payload, status_code)


def sequence(*handlers: Handler) -> Handler:
    """Answer successive calls to one endpoint differently; the last handler then repeats."""
    calls = {"count": 0}

    def handle(body: Body) -> httpx.Response:
        index = min(calls["count"], len(handlers) - 1)
        calls["count"] += 1
        return handlers[index](body)

    return handle


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replace asyncio.sleep so backoff and rate limiting are observable but instant."""
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)
    return delays
