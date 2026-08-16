from __future__ import annotations

import pytest

from app.services.protocols import (
    EXPORT_NOTICE,
    INTEGRATION_STATUS,
    ElnExportError,
    ElnExportRequest,
    build_export,
)
from tests.protocols.test_checklist import fixture_protocol


def export(**overrides: object) -> object:
    payload: dict[str, object] = {
        "protocol": fixture_protocol(),
        "folder_id": "lib_A1b2C3",
    }
    payload.update(overrides)
    return build_export(ElnExportRequest.model_validate(payload))


def test_entry_matches_benchlings_documented_creation_fields() -> None:
    payload = export(entry_template_id="tmpl_9", schema_id="assaysch_2", entry_name="p53 blot")

    entry = payload.entry.model_dump()
    assert entry["name"] == "p53 blot"
    assert entry["folderId"] == "lib_A1b2C3"
    assert entry["entryTemplateId"] == "tmpl_9"
    assert entry["schemaId"] == "assaysch_2"
    assert payload.endpoint == "POST /api/v2/entries"
    assert payload.provider == "benchling"


def test_the_entry_is_named_after_the_protocol_when_no_name_is_given() -> None:
    payload = export()

    assert payload.entry.name == fixture_protocol().title
    assert payload.entry.entryTemplateId is None
    assert payload.entry.schemaId is None


def test_the_export_is_marked_untested_against_the_live_api() -> None:
    payload = export()

    assert payload.integration_status == INTEGRATION_STATUS == "schema_ready_untested"
    assert "never exercised against a live" in payload.integration_note
    assert payload.integration_note in payload.warnings


def test_the_first_note_block_is_the_review_notice() -> None:
    """The record must arrive in the ELN visibly unreviewed, before any step is readable."""
    payload = export()

    first = payload.notes[0]
    assert first.text == EXPORT_NOTICE
    assert "Requires qualified researcher review before lab use." in first.text
    assert payload.entry.customFields["AskGrey review status"]["value"].startswith(
        "Agent-drafted content."
    )
    assert payload.entry.customFields["AskGrey content origin"]["value"] == "agent_drafted"


def test_every_step_becomes_one_numbered_block_in_order() -> None:
    protocol = fixture_protocol()
    payload = export(protocol=protocol)

    numbered = [note.text for note in payload.notes if str(note.type) == "list_number"]
    assert len(numbered) == len(protocol.steps)
    for step, text in zip(protocol.steps, numbered, strict=True):
        assert text.startswith(f"{step.title}: {step.instruction}")


def test_step_conditions_and_critical_notes_survive_the_transform() -> None:
    payload = export()

    blot = next(note.text for note in payload.notes if "Centrifuge lysates" in note.text)
    assert "(10 min, 4 C)" in blot
    assert "equipment: refrigerated microcentrifuge" in blot

    harvest = next(note.text for note in payload.notes if "ice-cold PBS" in note.text)
    assert "critical: keep lysates on ice to limit p53 degradation" in harvest


def test_materials_and_outcomes_become_bullets() -> None:
    payload = export()

    bullets = [note.text for note in payload.notes if str(note.type) == "list_bullet"]
    assert any("RIPA lysis buffer" in text and "storage 4 C" in text for text in bullets)
    assert any("clone DO-1" in text for text in bullets)
    assert any("53 kDa band" in text for text in bullets)


def test_a_protocol_without_materials_is_flagged_rather_than_padded() -> None:
    payload = export(protocol=fixture_protocol(materials=[]))

    assert any("no materials" in warning for warning in payload.warnings)
    assert not [
        note for note in payload.notes if str(note.type) == "list_bullet" and "storage" in note.text
    ]


def test_a_schema_without_a_template_is_flagged() -> None:
    payload = export(schema_id="assaysch_2")

    assert any("only validates" in warning for warning in payload.warnings)


@pytest.mark.parametrize("bad", ["lib/../etc", "https://evil.example/x", "lib 1", "a" * 65])
def test_resource_ids_that_are_not_benchling_ids_are_rejected(bad: str) -> None:
    with pytest.raises((ElnExportError, ValueError)):
        export(folder_id=bad)


def test_nothing_credential_shaped_is_present_in_the_payload() -> None:
    """The response is handed to the browser, so it must never carry auth material."""
    payload = export()

    dumped = payload.model_dump_json().lower()
    for token in ("api_key", "apikey", "authorization", "bearer", "secret", "token"):
        assert token not in dumped
