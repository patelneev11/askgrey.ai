from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.api.regulatory import get_ind_service
from app.main import app
from app.services.regulatory import REVIEW_NOTICE
from app.services.regulatory.ind import DraftedIndSection, IndDrafterError, IndService
from tests.regulatory.test_ind_service import StubDrafter, as_drafter

CREDENTIALS = {"email": "cmc@askgrey.ai", "password": "obsidian-workspace-1"}
DRAFT_ENDPOINT = "/api/regulatory/ind/draft"
STRUCTURE_ENDPOINT = "/api/regulatory/ind/structure"

REQUEST: dict[str, Any] = {
    "program_name": "AG-4471",
    "substance_name": "agrelizumab",
    "section_ids": ["3.2.S.4.4"],
    "evidence": [
        {"kind": "batch", "label": "Batch AG-4471-01", "value": "1.2", "unit": "kg"},
        {
            "kind": "assay_result",
            "label": "Assay by HPLC",
            "value": "99.2",
            "unit": "%",
            "batch_id": "AG-4471-01",
        },
    ],
}

DRAFTED = DraftedIndSection(
    section_id="3.2.S.4.4", text="Batch AG-4471-01 assayed at 99.2 % by HPLC."
)


@pytest.fixture
def install() -> Iterator[Callable[..., StubDrafter]]:
    def _install(*sections: DraftedIndSection, error: Exception | None = None) -> StubDrafter:
        stub = StubDrafter(*sections, error=error)
        app.dependency_overrides[get_ind_service] = lambda: IndService(as_drafter(stub))
        return stub

    yield _install
    app.dependency_overrides.pop(get_ind_service, None)


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_both_endpoints_require_authentication(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    stub = install(DRAFTED)

    assert client.get(STRUCTURE_ENDPOINT).status_code == 401
    assert client.post(DRAFT_ENDPOINT, json=REQUEST).status_code == 401
    assert stub.calls == []


def test_the_structure_endpoint_states_which_dated_tree_is_in_use(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    install(DRAFTED)

    response = client.get(STRUCTURE_ENDPOINT, headers=auth_header(client))

    assert response.status_code == 200
    body = response.json()
    assert body["review_notice"] == REVIEW_NOTICE
    assert body["reference"]["version"]
    assert {source["id"] for source in body["reference"]["sources"]} >= {"M4Q(R1)", "M4S(R2)"}
    assert any(section["id"] == "4.2.3.2" for section in body["sections"])


def test_a_drafted_section_comes_back_marked_as_a_first_draft(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    install(DRAFTED)

    response = client.post(DRAFT_ENDPOINT, json=REQUEST, headers=auth_header(client))

    assert response.status_code == 200
    body = response.json()
    assert body["review_notice"] == REVIEW_NOTICE
    section = body["sections"][0]
    assert section["status"] == "drafted"
    assert section["requires_expert_completion"] is True
    assert section["review_notice"] == REVIEW_NOTICE
    assert section["source_reference"].startswith("M4Q(R1)")


def test_a_section_with_no_data_behind_it_comes_back_empty_with_a_gap(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    install()

    response = client.post(
        DRAFT_ENDPOINT,
        json={**REQUEST, "section_ids": ["3.2.P.8.1"], "evidence": []},
        headers=auth_header(client),
    )

    assert response.status_code == 200
    section = response.json()["sections"][0]
    assert section["status"] == "not_drafted"
    assert section["text"] == ""
    assert section["gaps"][0]["kind"] == "no_evidence_submitted"


def test_an_unknown_evidence_kind_is_refused_by_validation(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    stub = install(DRAFTED)

    response = client.post(
        DRAFT_ENDPOINT,
        json={**REQUEST, "evidence": [{"kind": "vibes", "label": "x"}]},
        headers=auth_header(client),
    )

    assert response.status_code == 422
    assert stub.calls == []


def test_an_unknown_field_is_refused_rather_than_silently_ignored(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    install(DRAFTED)

    response = client.post(
        DRAFT_ENDPOINT, json={**REQUEST, "submit": True}, headers=auth_header(client)
    )

    assert response.status_code == 422


def test_asking_for_no_sections_is_refused(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    install(DRAFTED)

    response = client.post(
        DRAFT_ENDPOINT, json={**REQUEST, "section_ids": []}, headers=auth_header(client)
    )

    assert response.status_code == 422


def test_asking_only_for_headings_this_service_does_not_draft_is_refused(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    install(DRAFTED)

    response = client.post(
        DRAFT_ENDPOINT,
        json={**REQUEST, "section_ids": ["3.3"], "evidence": []},
        headers=auth_header(client),
    )

    assert response.status_code == 422


def test_a_drafter_failure_does_not_echo_submitted_data_or_upstream_detail(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    install(error=IndDrafterError("anthropic said: AG-4471-01 batch 1.2 kg"))

    response = client.post(DRAFT_ENDPOINT, json=REQUEST, headers=auth_header(client))

    assert response.status_code == 502
    assert "AG-4471-01" not in response.text
    assert "anthropic" not in response.text.lower()


def test_the_drafting_endpoint_is_rate_limited_like_other_llm_endpoints(
    client: TestClient, install: Callable[..., StubDrafter]
) -> None:
    install(DRAFTED)
    headers = auth_header(client)
    limit = deps.llm_limiter.limit

    codes = [
        client.post(DRAFT_ENDPOINT, json=REQUEST, headers=headers).status_code
        for _ in range(limit + 1)
    ]

    assert codes[:limit] == [200] * limit
    assert codes[-1] == 429
