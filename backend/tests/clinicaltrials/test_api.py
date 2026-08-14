from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.clinicaltrials import get_clinicaltrials_service
from app.main import app
from app.services.clinicaltrials.client import ClinicalTrialsClient
from app.services.clinicaltrials.service import ClinicalTrialsService
from app.services.rate_limit import RateLimiter
from tests.clinicaltrials.conftest import (
    Handler,
    RecordingTransport,
    error_response,
    fixture_response,
)

CREDENTIALS = {"email": "trialist@askgrey.ai", "password": "obsidian-workspace-1"}


@pytest.fixture
def stub_service() -> Iterator[Callable[..., RecordingTransport]]:
    """Installs a ClinicalTrials service backed by recorded responses for one test."""

    def install(*handlers: Handler) -> RecordingTransport:
        transport = RecordingTransport(*handlers)
        app.dependency_overrides[get_clinicaltrials_service] = lambda: ClinicalTrialsService(
            ClinicalTrialsClient(
                transport=transport, rate_limiter=RateLimiter(1000.0), max_attempts=1
            )
        )
        return transport

    yield install
    app.dependency_overrides.pop(get_clinicaltrials_service, None)


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_search_requires_authentication(
    client: TestClient, stub_service: Callable[..., RecordingTransport]
) -> None:
    stub_service()

    assert (
        client.get("/api/clinicaltrials/search", params={"condition": "melanoma"}).status_code
        == 401
    )


def test_search_returns_normalized_trials(
    client: TestClient, stub_service: Callable[..., RecordingTransport]
) -> None:
    transport = stub_service(fixture_response("search_page1.json"))

    response = client.get(
        "/api/clinicaltrials/search",
        params={
            "sponsor": "Merck",
            "condition": "melanoma",
            "intervention": "pembrolizumab",
            "phase": "PHASE3",
            "status": "ACTIVE_NOT_RECRUITING",
            "page_size": 2,
        },
        headers=auth_header(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 29
    assert body["next_page_token"]
    trial = body["trials"][0]
    assert trial["nct_id"] == "NCT03553836"
    assert trial["status"] == "ACTIVE_NOT_RECRUITING"
    assert trial["enrollment"] == 976
    assert transport.queries[0]["filter.advanced"] == ["AREA[Phase]PHASE3"]


def test_page_token_is_forwarded(
    client: TestClient, stub_service: Callable[..., RecordingTransport]
) -> None:
    transport = stub_service(fixture_response("search_page2.json"))

    response = client.get(
        "/api/clinicaltrials/search",
        params={"condition": "melanoma", "page_token": "cursor-123"},
        headers=auth_header(client),
    )

    assert response.status_code == 200
    assert transport.queries[0]["pageToken"] == ["cursor-123"]


def test_empty_result_set_is_200_with_no_trials(
    client: TestClient, stub_service: Callable[..., RecordingTransport]
) -> None:
    stub_service(fixture_response("search_empty.json"))

    response = client.get(
        "/api/clinicaltrials/search",
        params={"condition": "zzzznotarealcondition"},
        headers=auth_header(client),
    )

    assert response.status_code == 200
    assert response.json() == {
        **response.json(),
        "trials": [],
        "total_count": 0,
        "next_page_token": None,
    }


def test_no_filters_is_422(
    client: TestClient, stub_service: Callable[..., RecordingTransport]
) -> None:
    stub_service()

    response = client.get("/api/clinicaltrials/search", headers=auth_header(client))

    assert response.status_code == 422


def test_unknown_phase_is_rejected_by_validation(
    client: TestClient, stub_service: Callable[..., RecordingTransport]
) -> None:
    stub_service()

    response = client.get(
        "/api/clinicaltrials/search",
        params={"condition": "melanoma", "phase": "PHASE9"},
        headers=auth_header(client),
    )

    assert response.status_code == 422


def test_upstream_failure_is_502(
    client: TestClient, stub_service: Callable[..., RecordingTransport]
) -> None:
    stub_service(error_response(503))

    response = client.get(
        "/api/clinicaltrials/search",
        params={"condition": "melanoma"},
        headers=auth_header(client),
    )

    assert response.status_code == 502
