from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.pubchem import get_pubchem_service
from app.main import app
from app.services.pubchem.client import PugRestClient
from app.services.pubchem.service import PubChemService
from app.services.rate_limit import RateLimiter
from tests.pubchem.conftest import (
    Handler,
    RecordingTransport,
    fault_response,
    fixture_response,
    sequence,
)

CREDENTIALS = {"email": "chemist@askgrey.ai", "password": "obsidian-workspace-1"}

NAME_CIDS = "compound/name/cids/JSON"
PROPERTIES = (
    "compound/cid/property/"
    "Title,MolecularFormula,MolecularWeight,SMILES,ConnectivitySMILES,IUPACName,XLogP/JSON"
)
SYNONYMS = "compound/cid/synonyms/JSON"
SMILES_CIDS = "compound/smiles/cids/JSON"

NOT_FOUND = fault_response("PUGREST.NotFound", 404)


@pytest.fixture
def stub_service() -> Iterator[Callable[[dict[str, Handler]], None]]:
    """Installs a PubChem service backed by recorded responses for the duration of a test."""

    def install(handlers: dict[str, Handler]) -> None:
        transport = RecordingTransport(handlers)
        app.dependency_overrides[get_pubchem_service] = lambda: PubChemService(
            client=PugRestClient(
                transport=transport, rate_limiter=RateLimiter(1000.0), max_attempts=1
            )
        )

    yield install
    app.dependency_overrides.pop(get_pubchem_service, None)


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_compound_requires_authentication(
    client: TestClient, stub_service: Callable[[dict[str, Handler]], None]
) -> None:
    stub_service({})

    assert client.get("/api/pubchem/compound", params={"q": "aspirin"}).status_code == 401


def test_compound_returns_normalized_payload(
    client: TestClient, stub_service: Callable[[dict[str, Handler]], None]
) -> None:
    stub_service(
        {
            NAME_CIDS: fixture_response("cids_name_aspirin.json"),
            PROPERTIES: fixture_response("properties_aspirin.json"),
            SYNONYMS: fixture_response("synonyms_aspirin.json"),
        }
    )

    response = client.get(
        "/api/pubchem/compound", params={"q": "aspirin"}, headers=auth_header(client)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resolved_as"] == "name"
    assert body["ambiguous"] is False
    assert body["match"]["cid"] == 2244
    assert body["match"]["molecular_formula"] == "C9H8O4"
    assert body["candidates"][0]["rank"] == 1


def test_ambiguous_name_returns_candidates_not_an_error(
    client: TestClient, stub_service: Callable[[dict[str, Handler]], None]
) -> None:
    stub_service(
        {
            NAME_CIDS: sequence(NOT_FOUND, fixture_response("cids_name_glucose_word.json")),
            PROPERTIES: fixture_response("properties_glucose_candidates.json"),
            SYNONYMS: fixture_response("synonyms_glucose_candidates.json"),
        }
    )

    response = client.get(
        "/api/pubchem/compound", params={"q": "glucose"}, headers=auth_header(client)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ambiguous"] is True
    assert body["match"]["cid"] == 5793
    assert len(body["candidates"]) == 4


def test_unknown_compound_is_404(
    client: TestClient, stub_service: Callable[[dict[str, Handler]], None]
) -> None:
    stub_service({NAME_CIDS: NOT_FOUND, SMILES_CIDS: NOT_FOUND})

    response = client.get(
        "/api/pubchem/compound", params={"q": "notarealchemicalxyz"}, headers=auth_header(client)
    )

    assert response.status_code == 404


def test_provider_failure_is_502(
    client: TestClient, stub_service: Callable[[dict[str, Handler]], None]
) -> None:
    stub_service({NAME_CIDS: fault_response("PUGREST.ServerError", 500)})

    response = client.get(
        "/api/pubchem/compound",
        params={"q": "aspirin"},
        headers=auth_header(client),
    )

    assert response.status_code == 502


def test_empty_query_is_rejected_by_validation(
    client: TestClient, stub_service: Callable[[dict[str, Handler]], None]
) -> None:
    stub_service({})

    response = client.get("/api/pubchem/compound", params={"q": ""}, headers=auth_header(client))

    assert response.status_code == 422
