from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

CREDENTIALS = {"email": "eligibility@askgrey.ai", "password": "obsidian-workspace-1"}


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def profile(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Grey Therapeutics",
        "organization_type": "for_profit",
        "principal_place_of_business_us": True,
        "employee_count": 12,
        "ownership": {
            "us_individuals_percent": 100,
            "other_small_businesses_percent": 0,
            "investment_companies_percent": 0,
            "foreign_percent": 0,
        },
        "pi_primary_employer": "company",
        "pi_company_time_percent": 100,
        "phase": "phase_i",
        "work_by_company_percent": 80,
        "sam_registered": True,
        "sba_company_registry_registered": True,
        "research_focus": "Organoid models of metabolic disease",
    }
    base.update(overrides)
    return base


def test_eligibility_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/grants/eligibility", json={"profile": profile()})

    assert response.status_code == 401


def test_eligibility_returns_a_verdict_per_rule(client: TestClient) -> None:
    response = client.post(
        "/api/grants/eligibility",
        json={"profile": profile(), "program": "SBIR"},
        headers=auth_header(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["program"] == "SBIR"
    assert body["config_version"]
    # The derived verdict and summary have to reach the client: the UI reports them verbatim.
    assert body["verdict"] in {"pass", "fail", "needs_review"}
    assert body["summary"]
    outcome = next(item for item in body["outcomes"] if item["rule_id"] == "size_standard")
    assert outcome["verdict"] == "pass"
    assert outcome["citation"]
    assert outcome["explanation"]


def test_eligibility_fails_a_rule_it_can_decide(client: TestClient) -> None:
    response = client.post(
        "/api/grants/eligibility",
        json={"profile": profile(employee_count=900), "program": "SBIR"},
        headers=auth_header(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "fail"
    failed = {item["rule_id"] for item in body["outcomes"] if item["verdict"] == "fail"}
    assert "size_standard" in failed


def test_eligibility_names_the_facts_it_is_missing(client: TestClient) -> None:
    response = client.post(
        "/api/grants/eligibility",
        json={"profile": profile(employee_count=None), "program": "SBIR"},
        headers=auth_header(client),
    )

    outcome = next(
        item for item in response.json()["outcomes"] if item["rule_id"] == "size_standard"
    )
    assert outcome["verdict"] == "needs_review"
    assert "employee_count" in outcome["missing_fields"]


def test_eligibility_rejects_a_programme_it_has_no_rules_for(client: TestClient) -> None:
    response = client.post(
        "/api/grants/eligibility",
        json={"profile": profile(), "program": "OTHER"},
        headers=auth_header(client),
    )

    assert response.status_code == 422


def test_eligibility_rejects_an_out_of_range_percentage(client: TestClient) -> None:
    response = client.post(
        "/api/grants/eligibility",
        json={"profile": profile(ownership={"us_individuals_percent": 140})},
        headers=auth_header(client),
    )

    assert response.status_code == 422


def test_eligibility_rejects_an_overlong_research_focus(client: TestClient) -> None:
    response = client.post(
        "/api/grants/eligibility",
        json={"profile": profile(research_focus="a" * 2001)},
        headers=auth_header(client),
    )

    assert response.status_code == 422


def test_rules_are_readable_so_a_verdict_can_be_traced(client: TestClient) -> None:
    response = client.get("/api/grants/eligibility/rules", headers=auth_header(client))

    assert response.status_code == 200
    body = response.json()
    assert body["version"]
    size = next(rule for rule in body["rules"] if rule["id"] == "size_standard")
    assert size["parameters"]["max_employees"] == 500


def test_rules_require_authentication(client: TestClient) -> None:
    assert client.get("/api/grants/eligibility/rules").status_code == 401
