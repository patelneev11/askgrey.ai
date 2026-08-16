from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.protocols import get_protocol_service
from app.main import app
from app.services.protocols import ClaudeControlReviewer, ProtocolService
from tests.protocols.conftest import RecordingTransport, claude_response
from tests.protocols.test_checklist import fixture_protocol
from tests.protocols.test_validation import REVIEW

CREDENTIALS = {"email": "controls@askgrey.ai", "password": "obsidian-workspace-1"}

Install = Callable[..., None]


@pytest.fixture
def stub_service() -> Iterator[Install]:
    def install(*, payload: Any = None, status_code: int = 200, enabled: bool = True) -> None:
        if not enabled:
            app.dependency_overrides[get_protocol_service] = lambda: ProtocolService()
            return
        body = payload if payload is not None else REVIEW

        def build() -> ProtocolService:
            transport = RecordingTransport(claude_response(body, status_code=status_code))
            reviewer = ClaudeControlReviewer(api_key="k", model="claude-test", transport=transport)
            return ProtocolService(None, reviewer)

        app.dependency_overrides[get_protocol_service] = build

    yield install
    app.dependency_overrides.pop(get_protocol_service, None)


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def request_body() -> dict[str, Any]:
    return {"protocol": fixture_protocol().model_dump(mode="json")}


def test_both_routes_require_authentication(client: TestClient) -> None:
    for path in ("/api/protocols/controls/review", "/api/protocols/checklist"):
        assert client.post(path, json=request_body()).status_code == 401, path


def test_control_review_returns_scoped_findings(client: TestClient, stub_service: Install) -> None:
    stub_service()

    response = client.post(
        "/api/protocols/controls/review", json=request_body(), headers=auth_header(client)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["missing_control_count"] == 1
    assert body["origin"] == "agent_drafted"
    assert "not validation of the protocol" in body["scope_note"]
    assert body["disclaimer"].startswith("Agent-drafted content.")
    assert {finding["status"] for finding in body["controls"]} == {
        "present",
        "missing",
        "unclear",
    }
    assert body["reagent_checklist"]


def test_checklist_route_needs_no_model(client: TestClient, stub_service: Install) -> None:
    """Extraction is deterministic, so the checklist is available even with drafting disabled."""
    stub_service(enabled=False)

    response = client.post(
        "/api/protocols/checklist", json=request_body(), headers=auth_header(client)
    )

    assert response.status_code == 200
    items = response.json()
    assert {item["category"] for item in items} >= {"storage", "spin_speed"}
    assert all(item["quote"] for item in items)


def test_control_review_without_a_model_is_a_503(client: TestClient, stub_service: Install) -> None:
    stub_service(enabled=False)

    response = client.post(
        "/api/protocols/controls/review", json=request_body(), headers=auth_header(client)
    )

    assert response.status_code == 503


def test_an_unusable_reply_is_a_502(client: TestClient, stub_service: Install) -> None:
    stub_service(payload="not json")

    response = client.post(
        "/api/protocols/controls/review", json=request_body(), headers=auth_header(client)
    )

    assert response.status_code == 502


def test_a_protocol_with_no_steps_is_rejected(client: TestClient, stub_service: Install) -> None:
    stub_service()
    body = request_body()
    body["protocol"]["steps"] = []

    response = client.post("/api/protocols/controls/review", json=body, headers=auth_header(client))

    assert response.status_code == 422


def test_control_review_is_rate_limited_by_the_llm_limiter(
    client: TestClient, stub_service: Install, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_service()
    monkeypatch.setattr(deps.llm_limiter, "limit", 2)
    headers = auth_header(client)

    statuses = [
        client.post(
            "/api/protocols/controls/review", json=request_body(), headers=headers
        ).status_code
        for _ in range(4)
    ]

    assert statuses[:2] == [200, 200]
    assert 429 in statuses[2:]
