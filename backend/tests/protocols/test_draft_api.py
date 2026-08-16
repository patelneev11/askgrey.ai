from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.protocols import get_protocol_service
from app.main import app
from app.services.protocols import ProtocolService
from tests.protocols.conftest import (
    GOAL,
    claude_response,
    make_drafter,
    protocol_payload,
)

CREDENTIALS = {"email": "drafting@askgrey.ai", "password": "obsidian-workspace-1"}

Install = Callable[..., None]


@pytest.fixture
def stub_service() -> Iterator[Install]:
    """Installs a drafting service backed by a canned Claude reply for one test."""

    def install(
        *, payload: object | None = None, status_code: int = 200, enabled: bool = True
    ) -> None:
        if not enabled:
            app.dependency_overrides[get_protocol_service] = lambda: ProtocolService(drafter=None)
            return
        body = payload if payload is not None else protocol_payload()

        def build() -> ProtocolService:
            # A fresh drafter per request: the route closes its HTTP client when it is done,
            # exactly as the real per-request service does.
            drafter, _ = make_drafter(claude_response(body, status_code=status_code))
            return ProtocolService(drafter)

        app.dependency_overrides[get_protocol_service] = build

    yield install
    app.dependency_overrides.pop(get_protocol_service, None)


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_draft_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/protocols/draft", json={"goal": GOAL}).status_code == 401


def test_draft_returns_ordered_steps_and_the_disclaimer(
    client: TestClient, stub_service: Install
) -> None:
    stub_service()

    response = client.post("/api/protocols/draft", json={"goal": GOAL}, headers=auth_header(client))

    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "agent_drafted"
    assert body["disclaimer"] == (
        "Agent-drafted content. Requires qualified researcher review before lab use."
    )
    assert [step["order"] for step in body["steps"]] == [1, 2, 3]
    assert body["goal"] == GOAL
    assert body["materials"][0]["storage"] == "4 C"


def test_a_short_goal_is_rejected_before_any_model_call(
    client: TestClient, stub_service: Install
) -> None:
    stub_service()

    response = client.post(
        "/api/protocols/draft", json={"goal": "blot"}, headers=auth_header(client)
    )

    assert response.status_code == 422


def test_an_over_long_goal_is_rejected(client: TestClient, stub_service: Install) -> None:
    stub_service()

    response = client.post(
        "/api/protocols/draft", json={"goal": "x" * 2001}, headers=auth_header(client)
    )

    assert response.status_code == 422


def test_drafting_without_a_configured_model_is_a_503_not_a_template(
    client: TestClient, stub_service: Install
) -> None:
    stub_service(enabled=False)

    response = client.post("/api/protocols/draft", json={"goal": GOAL}, headers=auth_header(client))

    assert response.status_code == 503
    assert "no draft was produced" in response.json()["detail"]


def test_an_unusable_model_reply_is_a_502(client: TestClient, stub_service: Install) -> None:
    stub_service(payload="not json")

    response = client.post("/api/protocols/draft", json={"goal": GOAL}, headers=auth_header(client))

    assert response.status_code == 502


def test_drafting_is_rate_limited_by_the_llm_limiter(
    client: TestClient, stub_service: Install, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drafting spends money, so it must exhaust the LLM window rather than the API window."""
    stub_service()
    monkeypatch.setattr(deps.llm_limiter, "limit", 2)
    headers = auth_header(client)

    statuses = [
        client.post("/api/protocols/draft", json={"goal": GOAL}, headers=headers).status_code
        for _ in range(4)
    ]

    assert statuses[:2] == [200, 200]
    assert 429 in statuses[2:]
