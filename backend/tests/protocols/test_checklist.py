from __future__ import annotations

from app.services.protocols import ChecklistCategory, ProtocolDraft, build_checklist
from tests.protocols.conftest import GOAL, protocol_payload


def fixture_protocol(**overrides: object) -> ProtocolDraft:
    payload = protocol_payload(**overrides)
    payload["goal"] = GOAL
    payload["steps"] = [
        {**step, "id": f"step-{index}", "order": index}
        for index, step in enumerate(payload["steps"], start=1)
    ]
    return ProtocolDraft.model_validate(payload)


def details(items: object, category: ChecklistCategory) -> list[str]:
    assert isinstance(items, list)
    return [item.detail for item in items if item.category is category]


def test_storage_temperatures_come_from_materials_and_steps() -> None:
    items = build_checklist(fixture_protocol())

    storage = details(items, ChecklistCategory.STORAGE)
    assert "4 C" in storage
    assert "-20 C" in storage


def test_spin_speed_is_flagged_with_the_phrase_it_came_from() -> None:
    items = build_checklist(fixture_protocol())

    spin = [item for item in items if item.category is ChecklistCategory.SPIN_SPEED]
    assert spin
    assert spin[0].detail.replace(" ", "").lower().startswith("14000x")
    assert "14000" in spin[0].quote
    assert spin[0].step_id == "step-2"
    assert spin[0].step_order == 2


def test_handling_sensitive_wording_is_flagged() -> None:
    protocol = fixture_protocol(
        materials=[
            {
                "name": "ECL substrate",
                "storage": "4 C",
                "note": "light-sensitive; do not vortex, prepare fresh",
            }
        ]
    )

    handling = details(build_checklist(protocol), ChecklistCategory.HANDLING)

    assert "Light-sensitive" in handling
    assert "Do not vortex" in handling
    assert "Prepare fresh" in handling


def test_timing_sensitive_steps_are_flagged() -> None:
    protocol = fixture_protocol(
        steps=[
            {
                "title": "Primary antibody",
                "instruction": "Incubate overnight, then image immediately.",
                "duration": "overnight",
            }
        ]
    )

    timing = details(build_checklist(protocol), ChecklistCategory.TIMING)

    assert "Overnight" in timing
    assert "Immediately" in timing


def test_nothing_is_invented_for_a_protocol_that_states_nothing() -> None:
    """A checklist entry must be traceable to text; a silent protocol yields no flags."""
    protocol = fixture_protocol(
        materials=[{"name": "Plain buffer"}],
        steps=[{"title": "Mix", "instruction": "Combine the reagents and mix by pipetting."}],
    )

    assert build_checklist(protocol) == []


def test_every_item_quotes_its_source_text() -> None:
    for item in build_checklist(fixture_protocol()):
        assert item.quote
        assert item.subject
        assert item.detail


def test_repeated_values_in_one_step_are_not_listed_twice() -> None:
    protocol = fixture_protocol(
        materials=[{"name": "Plain buffer"}],
        steps=[
            {
                "title": "Spin",
                "instruction": "Spin at 300 x g, decant, then spin again at 300 x g.",
                "temperature": "4 C",
                "critical_note": "keep at 4 C throughout",
            }
        ],
    )

    items = build_checklist(protocol)

    assert details(items, ChecklistCategory.SPIN_SPEED) == ["300 x g"]
    assert details(items, ChecklistCategory.STORAGE) == ["4 C"]


def test_item_count_is_capped() -> None:
    protocol = fixture_protocol(
        steps=[
            {"instruction": f"Spin at {index}00 x g at 4 C for 5 min.", "title": f"Spin {index}"}
            for index in range(1, 40)
        ]
    )

    assert len(build_checklist(protocol)) == 80
