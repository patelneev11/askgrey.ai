"""
The ELN handoff bundle: what a researcher gets when work leaves AskGrey for their notebook.

These tests care about three things a broken export would cost someone: the bench steps arriving
in order, the review notice arriving with them, and a step title containing markup arriving as
text rather than as HTML.
"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

from fastapi.testclient import TestClient

from app.core.terms import TERMS_VERSION
from app.services.eln import (
    DOCUMENT_NAME,
    JSON_NAME,
    MARKDOWN_NAME,
    README_NAME,
    build_bundle,
    record_from_protocol,
    to_html,
    to_markdown,
)
from app.services.protocols.models import REVIEW_DISCLAIMER, ProtocolDraft


def auth_header(client: TestClient, email: str) -> dict[str, str]:
    tokens = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "obsidian-workspace-9",
            "accepted_terms_version": TERMS_VERSION,
        },
    ).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def draft(**overrides: Any) -> ProtocolDraft:
    body: dict[str, Any] = {
        "title": "Ziprasidone hERG patch-clamp screen",
        "goal": "Measure hERG current block across a ziprasidone concentration series",
        "assay_type": "Manual patch clamp",
        "summary": "Whole-cell recordings in HEK293 cells stably expressing hERG.",
        "materials": [
            {"name": "HEK293-hERG cells", "amount": "2 vials", "storage": "-150C"},
            {"name": "Ziprasidone", "amount": "10 mM in DMSO", "vendor_or_catalog": "Sigma S9200"},
        ],
        "steps": [
            {
                "id": "s2",
                "order": 2,
                "title": "Establish whole-cell configuration",
                "instruction": "Form a gigaohm seal, then rupture the membrane.",
                "duration": "5 min",
                "critical_note": "Discard cells with access resistance above 15 MOhm",
            },
            {
                "id": "s1",
                "order": 1,
                "title": "Plate cells",
                "instruction": "Seed at 30% confluence 24 h before recording.",
                "temperature": "37C",
                "equipment": ["incubator"],
            },
        ],
        "total_duration": "2 days",
        "expected_outcomes": ["Concentration-dependent tail-current block"],
        "model": "claude-test",
    }
    body.update(overrides)
    return ProtocolDraft.model_validate(body)


def members(content: bytes) -> dict[str, str]:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


def test_the_bundle_carries_the_record_in_every_form_a_notebook_accepts() -> None:
    files = members(build_bundle(record_from_protocol(draft())).content)
    assert set(files) == {README_NAME, DOCUMENT_NAME, MARKDOWN_NAME, JSON_NAME}


def test_the_steps_arrive_in_bench_order_not_the_order_they_were_stored() -> None:
    record = record_from_protocol(draft())
    method = next(section for section in record.sections if section.heading == "Method")
    assert [block.text.split(":")[0] for block in method.blocks] == [
        "Plate cells",
        "Establish whole-cell configuration",
    ]


def test_every_file_states_that_the_protocol_is_unvalidated() -> None:
    files = members(build_bundle(record_from_protocol(draft())).content)
    for name, text in files.items():
        assert REVIEW_DISCLAIMER in text, name


def test_markup_in_a_step_title_arrives_as_text() -> None:
    hostile = draft(
        title="<script>alert(1)</script>",
        steps=[
            {
                "id": "s1",
                "order": 1,
                "title": "Spin <b>hard</b>",
                "instruction": "Centrifuge at 300 x g & decant.",
            }
        ],
    )
    html = to_html(record_from_protocol(hostile))
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<b>hard</b>" not in html
    assert "300 x g &amp; decant" in html


def test_the_document_pulls_in_nothing_from_the_network() -> None:
    html = to_html(record_from_protocol(draft()))
    for forbidden in ("http://", "https://", "<script", "<img", "<iframe"):
        assert forbidden not in html


def test_markdown_numbers_the_method_and_bullets_the_materials() -> None:
    text = to_markdown(record_from_protocol(draft()))
    assert "1. Plate cells:" in text
    assert "2. Establish whole-cell configuration:" in text
    assert "- HEK293-hERG cells — 2 vials — storage -150C" in text


def test_the_json_member_round_trips_the_record() -> None:
    record = record_from_protocol(draft())
    parsed = json.loads(members(build_bundle(record).content)[JSON_NAME])
    assert parsed["title"] == record.title
    assert parsed["fields"]["Experimental goal"] == draft().goal
    assert parsed["sections"][-1]["blocks"][0]["kind"] == "bullet"


def test_two_exports_of_one_record_are_byte_identical() -> None:
    record = record_from_protocol(draft())
    record.exported_at = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)
    assert build_bundle(record).content == build_bundle(record).content


def test_the_filename_comes_from_the_title_and_survives_a_title_of_punctuation() -> None:
    assert build_bundle(record_from_protocol(draft())).filename == (
        "ziprasidone-herg-patch-clamp-screen-eln.zip"
    )
    assert build_bundle(record_from_protocol(draft(title="!!!"))).filename == "eln-record-eln.zip"


def test_a_protocol_with_no_materials_still_exports_its_method() -> None:
    record = record_from_protocol(draft(materials=[], expected_outcomes=[]))
    assert [section.heading for section in record.sections] == ["Summary", "Method"]


def test_the_endpoint_returns_a_zip_as_an_attachment(client: TestClient) -> None:
    response = client.post(
        "/api/protocols/export/eln/bundle",
        json={"protocol": draft().model_dump(mode="json")},
        headers=auth_header(client, "eln.bundle@example.com"),
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment;" in response.headers["content-disposition"]
    assert DOCUMENT_NAME in members(response.content)


def test_the_endpoint_needs_an_account(client: TestClient) -> None:
    response = client.post(
        "/api/protocols/export/eln/bundle",
        json={"protocol": draft().model_dump(mode="json")},
    )
    assert response.status_code == 401


def test_the_audit_trail_records_the_export_without_the_protocol(client: TestClient) -> None:
    headers = auth_header(client, "eln.audit@example.com")
    client.post(
        "/api/protocols/export/eln/bundle",
        json={"protocol": draft().model_dump(mode="json")},
        headers=headers,
    )
    events = client.get("/api/audit/events", headers=headers).json()["events"]
    exported = [event for event in events if event["event"] == "eln.bundle_exported"]
    assert len(exported) == 1
    assert exported[0]["kind"] == "export"
    assert exported[0]["detail"] == {"steps": 2, "origin": "agent_drafted"}
    assert "Ziprasidone" not in json.dumps(events)
