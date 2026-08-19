from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.services.screening import MAX_SMILES_LENGTH

from .reference import ASPIRIN, TERFENADINE

CREDENTIALS = {"email": "chemist@askgrey.ai", "password": "obsidian-workspace-1"}
ADMET = "/api/screening/admet"


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_the_admet_route_requires_authentication(client: TestClient) -> None:
    assert client.post(ADMET, json={"smiles": ASPIRIN.smiles}).status_code == 401


def test_the_response_carries_every_estimate_with_its_model_basis(client: TestClient) -> None:
    response = client.post(ADMET, json={"smiles": TERFENADINE.smiles}, headers=auth_header(client))

    assert response.status_code == 200
    body = response.json()
    assert body["molecular_formula"] == "C32H41NO2"
    assert "Nothing here is measured on this compound" in body["caveat"]

    estimates = {item["key"]: item for item in body["estimates"]}
    assert estimates.keys() >= {"gi_absorption", "bbb_penetration", "herg", "cyp_alerts"}
    for estimate in estimates.values():
        assert estimate["model_basis"].strip(), estimate["key"]
    assert "(predicted" in estimates["herg"]["verdict"]
    assert estimates["herg"]["outcome"] == "unfavourable"


def test_the_trained_models_are_returned_with_their_provenance(client: TestClient) -> None:
    body = client.post(
        ADMET, json={"smiles": TERFENADINE.smiles}, headers=auth_header(client)
    ).json()
    estimates = {item["key"]: item for item in body["estimates"]}

    for key in (
        "herg_blockade",
        "plasma_protein_binding",
        "cyp3a4_inhibition",
        "cyp2d6_inhibition",
        "cyp2c9_inhibition",
    ):
        estimate = estimates[key]
        assert estimate["available"] is True, key
        assert estimate["verdict"]
        assert "Gradient-boosted decision trees" in estimate["model_basis"]
        assert "not a measurement" in estimate["model_basis"]
        assert "Therapeutics Data Commons" in estimate["citation"]
        assert [item["label"] for item in estimate["inputs"]][-1] == "Applicability domain"

    assert "% bound" in estimates["plasma_protein_binding"]["verdict"]
    assert "calibrated probability" in estimates["herg_blockade"]["verdict"]


def test_a_structure_outside_the_training_space_is_refused_rather_than_extrapolated(
    client: TestClient,
) -> None:
    body = client.post(ADMET, json={"smiles": "CCO"}, headers=auth_header(client)).json()
    estimates = {item["key"]: item for item in body["estimates"]}

    for key in ("herg_blockade", "plasma_protein_binding", "cyp3a4_inhibition"):
        estimate = estimates[key]
        assert estimate["available"] is False, key
        assert estimate["outcome"] == "unavailable"
        assert "applicability domain" in estimate["reason"]


def test_unavailable_properties_are_returned_as_such_rather_than_omitted(
    client: TestClient,
) -> None:
    body = client.post(ADMET, json={"smiles": ASPIRIN.smiles}, headers=auth_header(client)).json()
    estimates = {item["key"]: item for item in body["estimates"]}

    for key in ("cyp_inhibition_other_isoforms",):
        estimate = estimates[key]
        assert estimate["available"] is False
        assert estimate["outcome"] == "unavailable"
        assert estimate["verdict"] == ""
        assert estimate["reason"]
        assert estimate["requires"]
        assert estimate["model_basis"]


def test_alerts_are_returned_with_the_alert_caveat(client: TestClient) -> None:
    body = client.post(
        ADMET, json={"smiles": TERFENADINE.smiles}, headers=auth_header(client)
    ).json()

    assert body["alerts"]
    assert all(alert["citation"] for alert in body["alerts"])
    assert "no match is not evidence of safety" in body["alert_caveat"]


@pytest.mark.parametrize(
    ("smiles", "expected_detail"),
    [
        ("not a molecule", "not valid in SMILES"),
        ("c1ccccc", "not a valid SMILES string"),
        ("C" * 201, "limited to 200-atom"),
    ],
)
def test_malformed_structures_return_422_with_a_readable_reason(
    client: TestClient, smiles: str, expected_detail: str
) -> None:
    response = client.post(ADMET, json={"smiles": smiles}, headers=auth_header(client))

    assert response.status_code == 422
    assert expected_detail in json.dumps(response.json()["detail"])


def test_overlong_input_is_rejected_by_the_schema(client: TestClient) -> None:
    response = client.post(
        ADMET,
        json={"smiles": "C" * (MAX_SMILES_LENGTH + 1)},
        headers=auth_header(client),
    )

    assert response.status_code == 422


def test_the_route_is_rate_limited_per_account(client: TestClient) -> None:
    headers = auth_header(client)
    limit = get_settings().api_rate_limit_per_minute
    payload = {"smiles": ASPIRIN.smiles}

    for _ in range(limit):
        assert client.post(ADMET, json=payload, headers=headers).status_code == 200

    throttled = client.post(ADMET, json=payload, headers=headers)
    assert throttled.status_code == 429
    assert throttled.headers["retry-after"]
