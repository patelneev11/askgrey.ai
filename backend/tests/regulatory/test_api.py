from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.regulatory import get_preclinical_service
from app.main import app
from app.services.regulatory import REVIEW_NOTICE
from app.services.regulatory.preclinical import (
    DraftedSection,
    DrafterError,
    PreclinicalService,
    SectionKey,
)
from tests.regulatory.conftest import StubDrafter, as_drafter

CREDENTIALS = {"email": "regaffairs@askgrey.ai", "password": "obsidian-workspace-1"}
ENDPOINT = "/api/regulatory/preclinical/report"

TABLE: dict[str, Any] = {
    "study_id": "TOX-2024-014",
    "species": "Rat",
    "duration": "28 days",
    "glp_status": "compliant",
    "groups": [
        {"label": "Control", "dose": {"value": "0", "unit": "mg/kg/day"}, "animals_per_sex": 10},
        {"label": "High", "dose": {"value": "150", "unit": "mg/kg/day"}, "animals_per_sex": 10},
    ],
    "findings": [
        {
            "group_label": "High",
            "endpoint": "Alanine aminotransferase increase",
            "quantity": {"value": "2.4", "unit": "x"},
            "incidence": {"affected": 7, "examined": 20},
        }
    ],
    "measurements": [{"name": "NOAEL", "quantity": {"value": "25", "unit": "mg/kg/day"}}],
}

DESIGN = DraftedSection(
    key=SectionKey.STUDY_DESIGN, text="Rats were dosed for 28 days at 0 and 150 mg/kg/day."
)
BAD_INTERPRETATION = DraftedSection(
    key=SectionKey.INTERPRETATION, text="The NOAEL was 50 mg/kg/day."
)


@pytest.fixture
def install() -> Iterator[Callable[..., StubDrafter]]:
    def _install(*sections: DraftedSection, error: Exception | None = None) -> StubDrafter:
        stub = StubDrafter(*sections, error=error)
        app.dependency_overrides[get_preclinical_service] = lambda: PreclinicalService(
            as_drafter(stub)
        )
        return stub

    yield _install
    app.dependency_overrides.pop(get_preclinical_service, None)


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_drafting_requires_authentication(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    stub = install(DESIGN)

    assert client.post(ENDPOINT, json=TABLE).status_code == 401
    assert stub.calls == []


def test_a_report_comes_back_with_its_audit_and_review_notice(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    install(DESIGN, BAD_INTERPRETATION)

    response = client.post(ENDPOINT, json=TABLE, headers=auth_header(client))

    assert response.status_code == 200
    body = response.json()
    assert body["requires_expert_review"] is True
    assert body["review_notice"] == REVIEW_NOTICE
    assert [section["key"] for section in body["sections"]] == [
        "study_design",
        "results",
        "interpretation",
    ]
    assert all(section["requires_expert_review"] for section in body["sections"])
    assert [flag["kind"] for flag in body["discrepancies"]] == ["contradicted_value"]
    assert body["discrepancies"][0]["source_value"] == "25 mg/kg/day"
    assert body["audit"]["numbers_flagged"] == 1


def test_an_unparseable_study_table_is_rejected_by_validation(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    stub = install(DESIGN)

    response = client.post(
        ENDPOINT,
        json={**TABLE, "measurements": [{"name": "NOAEL", "quantity": {"value": "high"}}]},
        headers=auth_header(client),
    )

    assert response.status_code == 422
    assert stub.calls == []


def test_an_unknown_field_is_refused_rather_than_silently_ignored(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    install(DESIGN)

    response = client.post(
        ENDPOINT, json={**TABLE, "conclusion": "safe"}, headers=auth_header(client)
    )

    assert response.status_code == 422


def test_a_study_table_with_nothing_in_it_is_rejected(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    install(DESIGN)

    response = client.post(ENDPOINT, json={"study_id": "TOX-9"}, headers=auth_header(client))

    assert response.status_code == 422


def test_a_drafter_failure_does_not_echo_study_data_or_upstream_detail(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    install(error=DrafterError("anthropic said: TOX-2024-014 AG-4471"))

    response = client.post(ENDPOINT, json=TABLE, headers=auth_header(client))

    assert response.status_code == 502
    assert "TOX-2024-014" not in response.text
    assert "anthropic" not in response.text.lower()


def test_the_endpoint_is_rate_limited_like_other_llm_endpoints(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    install(DESIGN)
    headers = auth_header(client)
    limit = deps.llm_limiter.limit

    codes = [
        client.post(ENDPOINT, json=TABLE, headers=headers).status_code for _ in range(limit + 1)
    ]

    assert codes[:limit] == [200] * limit
    assert codes[-1] == 429
