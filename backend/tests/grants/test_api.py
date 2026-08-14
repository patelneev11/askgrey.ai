from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.grants import get_grants_service
from app.main import app
from tests.grants.conftest import (
    Handler,
    RoutingTransport,
    error_response,
    fixture_response,
    json_response,
    make_service,
)

CREDENTIALS = {"email": "grants@askgrey.ai", "password": "obsidian-workspace-1"}

Install = Callable[..., RoutingTransport]


@pytest.fixture
def stub_service() -> Iterator[Install]:
    """Installs a grants service backed by recorded provider responses for one test."""

    def install(
        *,
        search2: Handler | list[Handler] | None = None,
        solicitations: Handler | list[Handler] | None = None,
        enrich_limit: int = 0,
    ) -> RoutingTransport:
        service, transport = make_service(
            search2=search2, solicitations=solicitations, enrich_limit=enrich_limit
        )
        app.dependency_overrides[get_grants_service] = lambda: service
        return transport

    yield install
    app.dependency_overrides.pop(get_grants_service, None)


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_search_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/grants/search", params={"keyword": "sbir"}).status_code == 401


def test_match_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/grants/match", json={"focus": "mRNA oncology"})
    assert response.status_code == 401


def test_search_returns_a_normalized_page(client: TestClient, stub_service: Install) -> None:
    stub_service(
        search2=fixture_response("search2_nih_sbir.json"),
        solicitations=fixture_response("sbir_solicitations.json"),
    )

    response = client.get(
        "/api/grants/search",
        params={"keyword": "small business", "agency": "HHS", "page_size": 5},
        headers=auth_header(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert {status["source"] for status in body["sources"]} == {"grants_gov", "sbir"}
    first = body["opportunities"][0]
    assert set(first) >= {
        "title",
        "agency",
        "close_date",
        "funding_ceiling",
        "topic_description",
        "url",
    }


def test_search_can_be_restricted_to_one_source(client: TestClient, stub_service: Install) -> None:
    transport = stub_service(search2=fixture_response("search2_nih_sbir.json"))

    response = client.get(
        "/api/grants/search",
        params={"keyword": "sbir", "source": ["grants_gov"]},
        headers=auth_header(client),
    )

    assert response.status_code == 200
    assert transport.queries("solicitations") == []


def test_search_without_any_filter_is_rejected(client: TestClient, stub_service: Install) -> None:
    stub_service()

    response = client.get("/api/grants/search", headers=auth_header(client))

    assert response.status_code == 422


def test_search_reports_a_provider_outage_without_failing(
    client: TestClient, stub_service: Install
) -> None:
    stub_service(search2=error_response(503), solicitations=json_response([]))

    response = client.get(
        "/api/grants/search",
        params={"keyword": "sbir", "agency": "HHS"},
        headers=auth_header(client),
    )

    assert response.status_code == 200
    grants_gov = next(item for item in response.json()["sources"] if item["source"] == "grants_gov")
    assert grants_gov["ok"] is False


def test_match_ranks_candidates(client: TestClient, stub_service: Install) -> None:
    stub_service(solicitations=fixture_response("sbir_solicitations.json"))

    response = client.post(
        "/api/grants/match",
        json={
            "focus": "Automated potency assays for autologous cell therapy release testing",
            "keyword": "sbir",
            "agency": "HHS",
            "sources": ["sbir"],
            "limit": 1,
        },
        headers=auth_header(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matcher"] == "lexical"
    assert len(body["matches"]) == 1
    assert body["matches"][0]["opportunity"]["number"] == "PHS-2027-1"
    assert 0.0 < body["matches"][0]["score"] <= 1.0


def test_match_rejects_an_empty_focus(client: TestClient, stub_service: Install) -> None:
    stub_service()

    response = client.post("/api/grants/match", json={"focus": "   "}, headers=auth_header(client))

    assert response.status_code == 422
