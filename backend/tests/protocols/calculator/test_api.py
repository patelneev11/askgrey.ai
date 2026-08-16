from __future__ import annotations

from fastapi.testclient import TestClient

CREDENTIALS = {"email": "protocols@askgrey.ai", "password": "obsidian-workspace-1"}

DILUTION = {
    "stock_concentration": {"value": "10", "unit": "mM"},
    "final_concentration": {"value": "10", "unit": "uM"},
    "final_volume": {"value": "10", "unit": "mL"},
}


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_every_calculator_route_requires_authentication(client: TestClient) -> None:
    for path in (
        "/api/protocols/calculator/dilution",
        "/api/protocols/calculator/master-mix",
        "/api/protocols/calculator/stock-ratio",
        "/api/protocols/calculator/solution-mass",
        "/api/protocols/calculator/recalculate",
    ):
        assert client.post(path, json={}).status_code == 401, path


def test_dilution_returns_the_solved_term_and_its_basis(client: TestClient) -> None:
    response = client.post(
        "/api/protocols/calculator/dilution", json=DILUTION, headers=auth_header(client)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["solved_for"] == "v1"
    assert body["stock_volume"] == {"value": "0.01", "unit": "mL"}
    assert body["diluent_volume"]["value"] == "9.99"
    assert body["fold_dilution"] == "1000"
    assert body["basis"] == "V1 = C2 x V2 / C1 = 10 uM x 10 mL / 10 mM"


def test_master_mix_scales_by_well_count(client: TestClient) -> None:
    response = client.post(
        "/api/protocols/calculator/master-mix",
        json={
            "components": [
                {"name": "2x mix", "per_reaction_volume": {"value": "10", "unit": "uL"}},
                {"name": "Water", "per_reaction_volume": {"value": "8", "unit": "uL"}},
            ],
            "reactions": 96,
        },
        headers=auth_header(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["effective_reactions"] == "105.6"
    assert body["total_volume"] == {"value": "1900.8", "unit": "uL"}
    assert [line["total_volume"]["value"] for line in body["lines"]] == ["1056", "844.8"]


def test_stock_ratio_reports_parts(client: TestClient) -> None:
    response = client.post(
        "/api/protocols/calculator/stock-ratio",
        json={
            "stock_concentration": {"value": "100", "unit": "X"},
            "final_concentration": {"value": "1", "unit": "X"},
            "final_volume": {"value": "50", "unit": "mL"},
        },
        headers=auth_header(client),
    )

    assert response.status_code == 200
    assert response.json()["ratio_label"] == "1:100 (1 part stock in 100 total)"


def test_solution_mass_returns_grams_for_a_molar_target(client: TestClient) -> None:
    response = client.post(
        "/api/protocols/calculator/solution-mass",
        json={
            "concentration": {"value": "1", "unit": "M"},
            "volume": {"value": "1", "unit": "L"},
            "molecular_weight_g_per_mol": "58.44",
        },
        headers=auth_header(client),
    )

    assert response.status_code == 200
    assert response.json()["mass"] == {"value": "58.44", "unit": "g"}


def test_recalculate_applies_a_batch_scale_across_entries(client: TestClient) -> None:
    response = client.post(
        "/api/protocols/calculator/recalculate",
        json={
            "entries": [
                {"id": "a", "step_id": "step-1", "dilution": DILUTION},
                {
                    "id": "b",
                    "step_id": "step-2",
                    "master_mix": {
                        "components": [
                            {"name": "2x mix", "per_reaction_volume": {"value": "10", "unit": "uL"}}
                        ],
                        "reactions": 8,
                        "overage_percent": "0",
                    },
                },
            ],
            "batch_scale": 48,
        },
        headers=auth_header(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["batch_scale"] == 48
    assert body["outcomes"][0]["kind"] == "dilution"
    assert body["outcomes"][1]["result"]["total_volume"]["value"] == "480"


def test_unsupported_unit_is_a_422_not_a_500(client: TestClient) -> None:
    response = client.post(
        "/api/protocols/calculator/dilution",
        json={**DILUTION, "final_concentration": {"value": "10", "unit": "furlongs"}},
        headers=auth_header(client),
    )

    assert response.status_code == 422


def test_incompatible_units_are_refused_with_an_explanation(client: TestClient) -> None:
    response = client.post(
        "/api/protocols/calculator/dilution",
        json={**DILUTION, "final_concentration": {"value": "10", "unit": "ug/mL"}},
        headers=auth_header(client),
    )

    assert response.status_code == 422
    assert "different kinds of concentration" in response.json()["detail"]


def test_out_of_range_reaction_count_is_rejected_by_validation(client: TestClient) -> None:
    response = client.post(
        "/api/protocols/calculator/master-mix",
        json={
            "components": [
                {"name": "2x mix", "per_reaction_volume": {"value": "10", "unit": "uL"}}
            ],
            "reactions": 0,
        },
        headers=auth_header(client),
    )

    assert response.status_code == 422


def test_recalculate_entry_count_is_bounded(client: TestClient) -> None:
    response = client.post(
        "/api/protocols/calculator/recalculate",
        json={"entries": [{"id": str(index), "dilution": DILUTION} for index in range(101)]},
        headers=auth_header(client),
    )

    assert response.status_code == 422
