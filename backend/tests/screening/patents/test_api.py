from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.screening import get_patents_service
from app.core.config import get_settings
from app.main import app
from app.services.screening.patents import MAX_KEYWORD_LENGTH
from tests.screening.patents.conftest import (
    Handler,
    fixture_handler,
    make_service,
    status_handler,
)

CREDENTIALS = {"email": "chemist@askgrey.ai", "password": "obsidian-workspace-1"}
SEARCH = "/api/screening/patents/search"
ASPIRIN = "CC(=O)OC1=CC=CC=C1C(=O)O"


@pytest.fixture
def stub_service() -> Iterator[Callable[..., None]]:
    """Installs a patents service backed by a recorded transport, so no request leaves the box."""

    def install(handler: Handler, *, api_key: str = "test-odp-key") -> None:
        # A fresh service per request, because the route closes its client when it is done.
        app.dependency_overrides[get_patents_service] = lambda: make_service(
            handler, api_key=api_key
        )[0]

    install(fixture_handler("search_page1.json"))
    yield install
    app.dependency_overrides.pop(get_patents_service, None)


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def search(client: TestClient, payload: dict[str, Any]) -> Any:
    return client.post(SEARCH, json=payload, headers=auth_header(client))


def test_search_requires_authentication(
    client: TestClient, stub_service: Callable[..., None]
) -> None:
    assert client.post(SEARCH, json={"keywords": "salicylate"}).status_code == 401


def test_search_returns_hits_with_the_derived_query(
    client: TestClient, stub_service: Callable[..., None]
) -> None:
    response = search(client, {"keywords": "salicylate prodrug", "page_size": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["source_available"] is True
    assert body["query"]["query_used"] == "salicylate AND prodrug"
    assert body["query"]["derived_from"] == "keywords"
    assert body["returned"] == 2
    assert body["total_found"] == 37
    assert body["hits"][0]["application_number"] == "16123456"
    assert body["page_size"] == 10


def test_a_smiles_search_says_the_structure_itself_was_not_searched(
    client: TestClient, stub_service: Callable[..., None]
) -> None:
    body = search(client, {"smiles": ASPIRIN}).json()

    assert body["query"]["query_used"] == "C9H8O4"
    assert body["query"]["derived_from"] == "structure_formula"
    assert body["query"]["structure"]["searched_by_structure"] is False
    assert body["query"]["structure"]["molecular_formula"] == "C9H8O4"


def test_the_response_always_carries_the_caveat_and_the_unavailable_analyses(
    client: TestClient, stub_service: Callable[..., None]
) -> None:
    body = search(client, {"keywords": "salicylate"}).json()

    assert "not a structural similarity search" in body["caveat"]
    assert "patent attorney" in body["caveat"]
    entries = {entry["key"]: entry for entry in body["unavailable"]}
    assert {"structural_similarity_search", "novelty_score", "freedom_to_operate"} <= set(entries)
    for entry in entries.values():
        assert entry["available"] is False
        assert entry["reason"] and entry["requires"] and entry["label"]
    assert "novelty" not in {key for key in body if key != "unavailable"}


def test_no_matches_is_reported_as_no_matches_not_as_novelty(
    client: TestClient, stub_service: Callable[..., None]
) -> None:
    stub_service(fixture_handler("search_empty.json"))

    body = search(client, {"keywords": "unobtainium widget"}).json()

    assert body["hits"] == []
    assert "not evidence of novelty" in body["no_match_statement"]


def test_an_unconfigured_source_is_reported_as_unavailable_not_as_empty(
    client: TestClient, stub_service: Callable[..., None]
) -> None:
    stub_service(fixture_handler("search_page1.json"), api_key="")

    body = search(client, {"keywords": "salicylate"}).json()

    assert body["source_available"] is False
    assert "API key" in body["source_status"]
    assert body["no_match_statement"] == ""
    assert body["total_found"] is None
    assert "test-odp-key" not in body["source_status"]


@pytest.mark.parametrize("status_code", [401, 500, 503])
def test_upstream_failures_return_200_with_the_source_marked_unavailable(
    client: TestClient, stub_service: Callable[..., None], status_code: int
) -> None:
    stub_service(status_handler(status_code))

    response = search(client, {"keywords": "salicylate"})

    assert response.status_code == 200
    assert response.json()["source_available"] is False


def test_a_query_the_upstream_api_rejects_becomes_a_502(
    client: TestClient, stub_service: Callable[..., None]
) -> None:
    stub_service(status_handler(400))

    response = search(client, {"keywords": "salicylate"})

    assert response.status_code == 502
    assert "key" not in response.json()["detail"].lower()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"keywords": "  "},
        {"smiles": "C1CC"},
        {"smiles": "not a molecule"},
        {"smiles": "C" * 700},
        {"keywords": "x" * (MAX_KEYWORD_LENGTH + 1)},
        {"keywords": 'salicylate" OR *:*'},
        {"keywords": "salicylate", "page_size": 500},
        {"keywords": "salicylate", "page_size": 0},
        {"keywords": "salicylate", "offset": 10000},
        {"keywords": "salicylate", "sort": "whatever_upstream_dsl"},
        {"keywords": "salicylate", "filed_from": "not-a-date"},
        {"keywords": "salicylate", "filed_from": "2021-01-01", "filed_to": "2019-01-01"},
    ],
)
def test_invalid_input_is_rejected_with_422(
    client: TestClient, stub_service: Callable[..., None], payload: dict[str, Any]
) -> None:
    assert search(client, payload).status_code == 422


def test_the_route_is_rate_limited_per_account(
    client: TestClient, stub_service: Callable[..., None]
) -> None:
    headers = auth_header(client)
    payload = {"keywords": "salicylate"}
    limit = get_settings().api_rate_limit_per_minute

    for _ in range(limit):
        assert client.post(SEARCH, json=payload, headers=headers).status_code == 200

    throttled = client.post(SEARCH, json=payload, headers=headers)
    assert throttled.status_code == 429
    assert throttled.headers["retry-after"]
