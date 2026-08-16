from __future__ import annotations

from app.services.protocols import ChangeKind, ProtocolDraft, diff_protocols
from tests.protocols.test_checklist import fixture_protocol


def edited(protocol: ProtocolDraft, mutate: object) -> ProtocolDraft:
    payload = protocol.model_dump(mode="json")
    assert callable(mutate)
    mutate(payload)
    return ProtocolDraft.model_validate(payload)


def kinds(changes: object) -> set[str]:
    assert isinstance(changes, list)
    return {str(change.kind) for change in changes}


def test_an_untouched_protocol_has_an_empty_changelog() -> None:
    protocol = fixture_protocol()

    assert diff_protocols(protocol, protocol) == []


def test_editing_a_step_instruction_is_reported_against_that_step() -> None:
    before = fixture_protocol()
    after = edited(before, lambda p: p["steps"][1].update(instruction="Spin at 16000 x g."))

    changes = diff_protocols(before, after)

    assert len(changes) == 1
    change = changes[0]
    assert change.field == "steps.step-2.instruction"
    assert change.kind is ChangeKind.MODIFIED
    assert "14000 x g" in change.before
    assert "16000 x g" in change.after


def test_reordering_is_reported_as_a_move_not_as_rewritten_steps() -> None:
    """A researcher who drags step 3 above step 2 changed no words; the log must say so."""
    before = fixture_protocol()

    def swap(payload: dict[str, object]) -> None:
        steps = payload["steps"]
        assert isinstance(steps, list)
        steps[1], steps[2] = steps[2], steps[1]
        for index, step in enumerate(steps, start=1):
            step["order"] = index

    after = edited(before, swap)
    changes = diff_protocols(before, after)

    assert kinds(changes) == {"reordered"}
    assert {change.field for change in changes} == {
        "steps.step-2.order",
        "steps.step-3.order",
    }


def test_added_and_removed_steps_are_distinguished() -> None:
    before = fixture_protocol()

    def replace_last(payload: dict[str, object]) -> None:
        steps = payload["steps"]
        assert isinstance(steps, list)
        steps[-1] = {
            "id": "step-99",
            "order": len(steps),
            "title": "Strip and reprobe",
            "instruction": "Strip the membrane and reprobe for the loading control.",
        }

    changes = diff_protocols(before, edited(before, replace_last))

    assert kinds(changes) == {"added", "removed"}
    assert any(change.label.startswith("Step added: Strip") for change in changes)
    assert any(change.label.startswith("Step removed: Immunoblot") for change in changes)


def test_material_and_header_edits_are_captured() -> None:
    before = fixture_protocol()

    def mutate(payload: dict[str, object]) -> None:
        payload["title"] = "p53 immunoblot (edited)"
        materials = payload["materials"]
        assert isinstance(materials, list)
        materials.pop()
        materials.append({"name": "Anti-GAPDH antibody", "amount": "1:5000"})
        payload["expected_outcomes"] = ["A 53 kDa band plus a GAPDH loading band"]

    changes = diff_protocols(before, edited(before, mutate))
    labels = [change.label for change in changes]

    assert "Title" in labels
    assert "Material added: Anti-GAPDH antibody" in labels
    assert "Material removed: Anti-p53 primary antibody" in labels
    assert "Expected outcomes edited" in labels
