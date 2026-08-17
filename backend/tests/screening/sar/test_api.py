from __future__ import annotations

import json
from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.screening import get_sar_service
from app.core.config import get_settings
from app.main import app
from app.services.llm import AnthropicMessagesClient
from app.services.screening import MAX_SMILES_LENGTH
from app.services.screening.sar import LlmSuggester, RuleBasedSuggester, SarService

CREDENTIALS = {"email": "chemist@askgrey.ai", "password": "obsidian-workspace-1"}
DESCRIPTORS = "/api/screening/sar/descriptors"
SUGGESTIONS = "/api/screening/sar/suggestions"
ASPIRIN = "CC(=O)OC1=CC=CC=C1C(=O)O"

SUGGESTION = {
    "title": "Swap the acetyl for a stable amide",
    "site": "Acetyl ester oxygen",
    "transformation": "-OC(=O)CH3 -> -NHC(=O)CH3",
    "rationale": "Esterases hydrolyse the acetate rapidly.",
    "expected_effect": "Typically improves plasma stability.",
    "risk": "Removes the acetylating pharmacology the ester provides.",
}


@pytest.fixture
def stub_service() -> Iterator[Callable[[SarService], None]]:
    """Installs a SAR service for the duration of a test, so no request reaches Anthropic."""

    def install(service: SarService) -> None:
        app.dependency_overrides[get_sar_service] = lambda: service

    install(SarService(suggester=RuleBasedSuggester()))
    yield install
    app.dependency_overrides.pop(get_sar_service, None)


def llm_service(payload: object, *, status_code: int = 200) -> SarService:
    body = payload if isinstance(payload, str) else json.dumps(payload).lstrip("[")
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            status_code, json={"content": [{"type": "text", "text": body}]}
        )
    )
    return SarService(
        suggester=LlmSuggester(
            AnthropicMessagesClient(
                api_key="key",
                model="claude-sonnet-4-5",
                max_tokens=512,
                timeout=5.0,
                transport=transport,
            )
        )
    )


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.mark.parametrize("route", [DESCRIPTORS, SUGGESTIONS])
def test_screening_routes_require_authentication(
    client: TestClient, stub_service: Callable[[SarService], None], route: str
) -> None:
    assert client.post(route, json={"smiles": ASPIRIN}).status_code == 401


def test_descriptors_returns_the_profile_with_its_caveat_and_provenance(
    client: TestClient, stub_service: Callable[[SarService], None]
) -> None:
    response = client.post(DESCRIPTORS, json={"smiles": ASPIRIN}, headers=auth_header(client))

    assert response.status_code == 200
    body = response.json()
    assert body["canonical_smiles"] == "CC(=O)Oc1ccccc1C(=O)O"
    assert body["molecular_formula"] == "C9H8O4"
    assert "RDKit" in body["basis"]
    assert "not measured" in body["caveat"]

    descriptors = {item["key"]: item for item in body["descriptors"]}
    assert descriptors["molecular_weight"]["display"] == "180.16 g/mol"
    assert descriptors["logp"]["method"].startswith("RDKit Crippen.MolLogP")
    assert {item["key"] for item in body["rule_sets"]} == {"lipinski", "veber"}


def test_descriptors_reports_binding_affinity_as_unavailable(
    client: TestClient, stub_service: Callable[[SarService], None]
) -> None:
    body = client.post(DESCRIPTORS, json={"smiles": ASPIRIN}, headers=auth_header(client)).json()

    affinity = next(item for item in body["unavailable"] if item["key"] == "binding_affinity")
    assert affinity["available"] is False
    assert "docking" in affinity["reason"]
    assert not any("affinity" in item["key"] for item in body["descriptors"])


@pytest.mark.parametrize(
    ("smiles", "expected_detail"),
    [
        ("not a molecule", "not valid in SMILES"),
        ("c1ccccc", "not a valid SMILES string"),
        ("C" * 201, "limited to 200-atom"),
    ],
)
def test_malformed_structures_return_422_with_a_readable_reason(
    client: TestClient,
    stub_service: Callable[[SarService], None],
    smiles: str,
    expected_detail: str,
) -> None:
    response = client.post(DESCRIPTORS, json={"smiles": smiles}, headers=auth_header(client))

    assert response.status_code == 422
    assert expected_detail in json.dumps(response.json()["detail"])


def test_overlong_input_is_rejected_by_the_schema_before_the_service(
    client: TestClient, stub_service: Callable[[SarService], None]
) -> None:
    response = client.post(
        DESCRIPTORS,
        json={"smiles": "C" * (MAX_SMILES_LENGTH + 1)},
        headers=auth_header(client),
    )

    assert response.status_code == 422


def test_suggestions_returns_llm_output_labelled_as_unvalidated(
    client: TestClient, stub_service: Callable[[SarService], None]
) -> None:
    stub_service(llm_service([SUGGESTION]))

    body = client.post(SUGGESTIONS, json={"smiles": ASPIRIN}, headers=auth_header(client)).json()

    assert body["source"] == "llm"
    assert body["validated"] is False
    assert "chemist review" in body["caveat"]
    assert [item["title"] for item in body["suggestions"]] == [SUGGESTION["title"]]


def test_suggestions_falls_back_to_heuristics_when_claude_is_unavailable(
    client: TestClient, stub_service: Callable[[SarService], None]
) -> None:
    stub_service(llm_service({}, status_code=529))

    response = client.post(SUGGESTIONS, json={"smiles": ASPIRIN}, headers=auth_header(client))

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "rules"
    assert body["suggestions"]
    assert body["validated"] is False


def test_descriptor_route_is_rate_limited_per_account(
    client: TestClient, stub_service: Callable[[SarService], None]
) -> None:
    headers = auth_header(client)
    limit = get_settings().api_rate_limit_per_minute
    payload = {"smiles": ASPIRIN}

    for _ in range(limit):
        assert client.post(DESCRIPTORS, json=payload, headers=headers).status_code == 200

    throttled = client.post(DESCRIPTORS, json=payload, headers=headers)
    assert throttled.status_code == 429
    assert throttled.headers["retry-after"]


def test_suggestion_route_is_rate_limited_by_the_llm_limiter(
    client: TestClient, stub_service: Callable[[SarService], None]
) -> None:
    headers = auth_header(client)
    payload = {"smiles": ASPIRIN}
    deps.llm_limiter.reset()
    limit = get_settings().llm_rate_limit_per_minute

    for _ in range(limit):
        assert client.post(SUGGESTIONS, json=payload, headers=headers).status_code == 200

    assert client.post(SUGGESTIONS, json=payload, headers=headers).status_code == 429
