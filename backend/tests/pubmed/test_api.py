from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.pubmed import get_pubmed_service
from app.main import app
from app.services.pubmed.client import EntrezClient
from app.services.pubmed.service import PubMedService
from app.services.pubmed.translation import RuleBasedQueryTranslator
from app.services.rate_limit import RateLimiter
from tests.pubmed.conftest import (
    RecordingTransport,
    json_response,
    load_fixture,
    load_json_fixture,
    xml_response,
)

CREDENTIALS = {"email": "researcher@askgrey.ai", "password": "obsidian-workspace-1"}


@pytest.fixture
def stub_service() -> Iterator[None]:
    transport = RecordingTransport(
        {
            "esearch.fcgi": lambda _: json_response(load_json_fixture("esearch_semaglutide.json")),
            "efetch.fcgi": lambda _: xml_response(load_fixture("efetch_semaglutide.xml")),
        }
    )

    def override() -> PubMedService:
        return PubMedService(
            client=EntrezClient(transport=transport, rate_limiter=RateLimiter(1000.0)),
            translator=RuleBasedQueryTranslator(today=date(2024, 6, 1)),
        )

    app.dependency_overrides[get_pubmed_service] = override
    yield
    app.dependency_overrides.pop(get_pubmed_service, None)


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_search_requires_authentication(client: TestClient, stub_service: None) -> None:
    assert client.get("/api/pubmed/search", params={"q": "obesity"}).status_code == 401


def test_search_returns_normalized_payload(client: TestClient, stub_service: None) -> None:
    response = client.get(
        "/api/pubmed/search",
        params={"q": "semaglutide for obesity", "limit": 2},
        headers=auth_header(client),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_results"] == 412
    assert body["query"]["translator"] == "rule-based"
    first = body["articles"][0]
    assert first["pmid"] == "37733246"
    assert first["doi"] == "10.1056/NEJMoa2306963"
    assert first["full_text_url"].endswith("/PMC10685891/")


def test_search_validates_query_parameters(client: TestClient, stub_service: None) -> None:
    headers = auth_header(client)
    assert client.get("/api/pubmed/search", headers=headers).status_code == 422
    assert client.get("/api/pubmed/search", params={"q": ""}, headers=headers).status_code == 422
    assert (
        client.get(
            "/api/pubmed/search", params={"q": "obesity", "limit": 500}, headers=headers
        ).status_code
        == 422
    )
