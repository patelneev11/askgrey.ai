from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.grants import get_review_board
from app.main import app
from app.services.grants.review_board import (
    MAX_TEXT_CHARS,
    MIN_TEXT_CHARS,
    ReviewBoard,
    ReviewBoardError,
    load_persona_config,
)

from .conftest import APPROACH_TEXT, StubReviewer

CREDENTIALS = {"email": "board@askgrey.ai", "password": "obsidian-workspace-1"}
BIOSTATISTICIAN = "strict_biostatistician"

Install = Callable[..., StubReviewer]


@pytest.fixture
def install() -> Iterator[Install]:
    """Installs a board with the shipped personas and a reviewer that never leaves the box."""

    def _install(*, reviewer: StubReviewer | None = None, with_llm: bool = True) -> StubReviewer:
        stub = reviewer or StubReviewer()
        board = ReviewBoard(load_persona_config(), stub if with_llm else None)
        app.dependency_overrides[get_review_board] = lambda: board
        return stub

    yield _install
    app.dependency_overrides.pop(get_review_board, None)


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def body(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "section_name": "Approach",
        "program": "SBIR",
        "phase": "Phase I",
        "text": APPROACH_TEXT,
    }
    payload.update(overrides)
    return payload


def test_the_review_endpoint_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/grants/review-board", json=body()).status_code == 401


def test_the_personas_endpoint_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/grants/review-board/personas").status_code == 401


def test_the_personas_endpoint_lists_the_board_without_its_prompts(
    client: TestClient, install: Install
) -> None:
    install()

    response = client.get("/api/grants/review-board/personas", headers=auth_header(client))

    assert response.status_code == 200
    listed = response.json()
    assert [entry["id"] for entry in listed] == [
        BIOSTATISTICIAN,
        "commercialization_critic",
        "translational_safety_reviewer",
    ]
    for entry in listed:
        assert set(entry) == {"id", "name", "focus", "criteria"}
        assert entry["criteria"][:3] == ["Significance", "Innovation", "Approach"]


def test_a_review_returns_the_board_report_shape(client: TestClient, install: Install) -> None:
    install()

    response = client.post("/api/grants/review-board", json=body(), headers=auth_header(client))

    assert response.status_code == 200
    report = response.json()
    assert set(report) == {
        "section_name",
        "program",
        "phase",
        "config_version",
        "validation_status",
        "caveat",
        "model",
        "reviews",
        "summary",
    }
    assert report["validation_status"] == "unvalidated"
    assert "not calibrated" in report["caveat"]
    assert report["config_version"] == load_persona_config().version
    assert len(report["reviews"]) == 3
    review = report["reviews"][0]
    assert set(review) == {
        "persona_id",
        "persona_name",
        "focus",
        "scores",
        "overall_score",
        "strengths",
        "weaknesses",
        "comment",
    }
    assert set(review["scores"][0]) == {"criterion", "score", "reasoning"}
    assert 1 <= review["scores"][0]["score"] <= 9


def test_a_caller_can_select_personas(client: TestClient, install: Install) -> None:
    stub = install()

    response = client.post(
        "/api/grants/review-board",
        json=body(personas=[BIOSTATISTICIAN]),
        headers=auth_header(client),
    )

    assert response.status_code == 200
    assert stub.calls == [BIOSTATISTICIAN]


def test_an_unknown_persona_is_rejected(client: TestClient, install: Install) -> None:
    install()

    response = client.post(
        "/api/grants/review-board",
        json=body(personas=["nobel_laureate"]),
        headers=auth_header(client),
    )

    assert response.status_code == 422
    assert "nobel_laureate" in response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {"text": "too short to review"},
        {"text": "x" * (MAX_TEXT_CHARS + 1)},
        {"text": "x" * (MIN_TEXT_CHARS - 1)},
        {"section_name": ""},
        {"section_name": "s" * 201},
        {"program": "p" * 101},
        {"personas": [f"p{index}" for index in range(11)]},
    ],
    ids=[
        "short",
        "over-ceiling",
        "under-floor",
        "no-section",
        "long-section",
        "long-program",
        "many-personas",
    ],
)
def test_input_is_bounded_server_side(
    client: TestClient, install: Install, payload: dict[str, Any]
) -> None:
    install()

    response = client.post(
        "/api/grants/review-board", json=body(**payload), headers=auth_header(client)
    )

    assert response.status_code == 422


def test_a_missing_text_field_is_rejected(client: TestClient, install: Install) -> None:
    install()
    payload = body()
    payload.pop("text")

    response = client.post("/api/grants/review-board", json=payload, headers=auth_header(client))

    assert response.status_code == 422


def test_without_an_llm_key_the_endpoint_is_503_and_invents_nothing(
    client: TestClient, install: Install
) -> None:
    install(with_llm=False)

    response = client.post("/api/grants/review-board", json=body(), headers=auth_header(client))

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "ANTHROPIC_API_KEY" in detail
    assert "score" in detail


def test_a_claude_failure_is_surfaced_rather_than_scored_around(
    client: TestClient, install: Install
) -> None:
    install(reviewer=StubReviewer(error=ReviewBoardError("Claude returned HTTP 529")))

    response = client.post("/api/grants/review-board", json=body(), headers=auth_header(client))

    assert response.status_code == 502
    assert "529" in response.json()["detail"]


def test_the_review_endpoint_counts_against_the_daily_llm_budget(
    client: TestClient, install: Install
) -> None:
    install()
    headers = auth_header(client)
    deps.llm_budget.limit = 1
    try:
        first = client.post("/api/grants/review-board", json=body(), headers=headers)
        blocked = client.post("/api/grants/review-board", json=body(), headers=headers)
    finally:
        deps.llm_budget.limit = deps._settings.llm_daily_call_budget

    assert first.status_code == 200
    assert blocked.status_code == 429
    assert "budget" in blocked.json()["detail"]


def test_the_review_endpoint_is_rate_limited(client: TestClient, install: Install) -> None:
    install()
    headers = auth_header(client)
    deps.llm_limiter.limit = 1
    try:
        first = client.post("/api/grants/review-board", json=body(), headers=headers)
        blocked = client.post("/api/grants/review-board", json=body(), headers=headers)
    finally:
        deps.llm_limiter.limit = deps._settings.llm_rate_limit_per_minute

    assert first.status_code == 200
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_the_personas_endpoint_is_rate_limited(client: TestClient, install: Install) -> None:
    install()
    headers = auth_header(client)
    deps.api_limiter.limit = 1
    try:
        first = client.get("/api/grants/review-board/personas", headers=headers)
        blocked = client.get("/api/grants/review-board/personas", headers=headers)
    finally:
        deps.api_limiter.limit = deps._settings.api_rate_limit_per_minute

    assert first.status_code == 200
    assert blocked.status_code == 429
