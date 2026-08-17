from __future__ import annotations

from fastapi.testclient import TestClient

CREDENTIALS = {"email": "regulatory@askgrey.ai", "password": "obsidian-workspace-1"}

CHECK = "/api/regulatory/guidelines/check"
REFERENCE = "/api/regulatory/guidelines/reference"

DRAFT = (
    "The drug substance is a small molecule whose physicochemical properties, including "
    "solubility across the physiological pH range and hygroscopicity, are summarised below. "
    "Identity is confirmed by NMR and mass spectrometry. The specification and its analytical "
    "methods control identity, assay, related substances and residual solvents, with acceptance "
    "criteria set on the basis of the batches manufactured to date. The impurity profile of the "
    "batches used in the toxicology studies is representative of the clinical material. Stability "
    "data for three batches at the intended storage condition support the proposed retest period."
)


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_check_requires_authentication(client: TestClient) -> None:
    response = client.post(
        CHECK, json={"section_id": "3.2.S.4", "draft_text": DRAFT, "jurisdictions": ["fda"]}
    )

    assert response.status_code == 401


def test_reference_requires_authentication(client: TestClient) -> None:
    assert client.get(REFERENCE).status_code == 401


def test_check_returns_a_report_with_the_review_marker_and_reference_vintage(
    client: TestClient,
) -> None:
    response = client.post(
        CHECK,
        json={"section_id": "3.2.S.4", "draft_text": DRAFT, "jurisdictions": ["fda", "ema"]},
        headers=auth_header(client),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requires_expert_review"] is True
    assert "qualified regulatory affairs" in body["review_notice"]
    assert "dated snapshot" in body["limitations"]
    assert body["section_id"] == "3.2.S.4"
    assert body["word_count"] > body["min_words_to_judge"]
    assert [block["jurisdiction"] for block in body["jurisdictions"]] == ["fda", "ema"]

    fda = body["jurisdictions"][0]
    assert fda["version"]
    assert fda["retrieved"]
    addressed = next(
        finding
        for finding in fda["findings"]
        if finding["requirement_id"] == "fda.ds.limits_and_methods"
    )
    assert addressed["status"] == "addressed"
    assert addressed["matched_signal"]["phrases"][0]["phrase"]
    assert addressed["citation"]["url"].startswith("https://")
    # Requirements for other sections are not evaluated against this one.
    out_of_scope = fda["out_of_scope_requirement_ids"]
    assert "fda.nonclinical.glp_statement" in out_of_scope
    assert "fda.ds.stability" in out_of_scope


def test_check_reports_indeterminate_for_a_stub_section(client: TestClient) -> None:
    response = client.post(
        CHECK,
        json={
            "section_id": "3.2.S.4",
            "draft_text": "Specification: TBD.",
            "jurisdictions": ["fda"],
        },
        headers=auth_header(client),
    )

    assert response.status_code == 200
    statuses = {finding["status"] for finding in response.json()["jurisdictions"][0]["findings"]}
    assert statuses == {"indeterminate"}


def test_over_long_draft_is_rejected_without_echoing_it(client: TestClient) -> None:
    draft = "a" * 60_001

    response = client.post(
        CHECK,
        json={"section_id": "3.2.S.4", "draft_text": draft, "jurisdictions": ["fda"]},
        headers=auth_header(client),
    )

    assert response.status_code == 422
    assert draft[:200] not in response.text


def test_bad_section_id_and_empty_jurisdictions_are_rejected(client: TestClient) -> None:
    headers = auth_header(client)

    rejected = client.post(
        CHECK,
        json={"section_id": "not a section", "draft_text": DRAFT, "jurisdictions": ["fda"]},
        headers=headers,
    )
    assert rejected.status_code == 422
    # No submitted value comes back, not the draft and not the section id either.
    assert "not a section" not in rejected.text
    assert DRAFT[:60] not in rejected.text
    assert (
        client.post(
            CHECK,
            json={"section_id": "3.2.S.4", "draft_text": DRAFT, "jurisdictions": []},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.post(
            CHECK,
            json={"section_id": "3.2.S.4", "draft_text": DRAFT, "jurisdictions": ["mhra"]},
            headers=headers,
        ).status_code
        == 422
    )


def test_reference_lists_versions_dates_and_citations(client: TestClient) -> None:
    response = client.get(REFERENCE, headers=auth_header(client))

    assert response.status_code == 200
    body = response.json()
    assert body["requires_expert_review"] is True
    assert {block["jurisdiction"] for block in body["jurisdictions"]} == {"fda", "ema", "pmda"}
    for block in body["jurisdictions"]:
        assert block["version"]
        assert block["retrieved"]
        assert block["requirements"]
        for entry in block["requirements"]:
            assert entry["title"]
            assert entry["expectation"]
            assert entry["citation"]["document"]
            assert entry["citation"]["document_date"]
            assert entry["citation"]["url"].startswith("https://")
