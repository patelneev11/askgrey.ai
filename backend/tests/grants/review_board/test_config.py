from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.services.grants.review_board import (
    DEFAULT_PERSONAS_PATH,
    ReviewBoard,
    ReviewBoardConfigError,
    load_persona_config,
)


def edited_config(tmp_path: Path, edit: dict[str, Any]) -> Path:
    """The shipped personas with one block replaced, so tests prove the config drives the board."""
    payload = json.loads(DEFAULT_PERSONAS_PATH.read_text())
    payload.update(edit)
    path = tmp_path / "personas.json"
    path.write_text(json.dumps(payload))
    return path


def test_the_shipped_personas_load_and_carry_a_version() -> None:
    config = load_persona_config()

    assert config.version
    assert config.core_criteria == ["Significance", "Innovation", "Approach"]
    assert len(config.enabled_personas) == 3


def test_every_shipped_persona_has_a_prompt_and_its_own_criteria() -> None:
    for persona in load_persona_config().personas:
        assert persona.system_prompt.strip()
        assert persona.criteria
        assert persona.focus


def test_criteria_are_the_core_three_plus_the_persona_additions() -> None:
    config = load_persona_config()
    persona = next(p for p in config.personas if p.id == "strict_biostatistician")

    assert config.criteria_for(persona) == [
        "Significance",
        "Innovation",
        "Approach",
        "Statistical Power and Sample Size",
        "Analysis Plan and Rigor",
    ]


def test_a_persona_criterion_repeating_a_core_one_is_not_scored_twice(tmp_path: Path) -> None:
    path = edited_config(
        tmp_path,
        {
            "personas": [
                {
                    "id": "p",
                    "name": "P",
                    "system_prompt": "You review.",
                    "criteria": ["Approach", "Market Viability"],
                }
            ]
        },
    )
    config = load_persona_config(path)

    assert config.criteria_for(config.personas[0]) == [
        "Significance",
        "Innovation",
        "Approach",
        "Market Viability",
    ]


def test_a_missing_config_is_an_error_not_an_empty_board(tmp_path: Path) -> None:
    with pytest.raises(ReviewBoardConfigError):
        load_persona_config(tmp_path / "absent.json")


def test_unparseable_config_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "personas.json"
    path.write_text("{ not json")

    with pytest.raises(ReviewBoardConfigError):
        load_persona_config(path)


def test_a_persona_without_a_prompt_is_rejected(tmp_path: Path) -> None:
    path = edited_config(tmp_path, {"personas": [{"id": "p", "name": "P", "system_prompt": ""}]})

    with pytest.raises(ReviewBoardConfigError):
        load_persona_config(path)


def test_an_unknown_key_in_a_persona_is_rejected_rather_than_ignored(tmp_path: Path) -> None:
    path = edited_config(
        tmp_path,
        {
            "personas": [
                {"id": "p", "name": "P", "system_prompt": "You review.", "sytem_prompt": "typo"}
            ]
        },
    )

    with pytest.raises(ReviewBoardConfigError):
        load_persona_config(path)


def test_duplicate_persona_ids_are_rejected(tmp_path: Path) -> None:
    persona = {"id": "twice", "name": "P", "system_prompt": "You review."}
    path = edited_config(tmp_path, {"personas": [persona, dict(persona, name="Q")]})

    with pytest.raises(ReviewBoardConfigError, match="twice"):
        load_persona_config(path)


def test_a_config_with_no_core_criteria_is_rejected(tmp_path: Path) -> None:
    path = edited_config(tmp_path, {"core_criteria": []})

    with pytest.raises(ReviewBoardConfigError, match="core_criteria"):
        load_persona_config(path)


def test_a_board_with_every_persona_disabled_is_rejected(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_PERSONAS_PATH.read_text())
    for persona in payload["personas"]:
        persona["enabled"] = False
    path = tmp_path / "personas.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ReviewBoardConfigError, match="enabled"):
        load_persona_config(path)


def test_construction_fails_on_a_bad_config_rather_than_at_review_time(tmp_path: Path) -> None:
    path = tmp_path / "personas.json"
    path.write_text(json.dumps({"version": "test", "personas": "not a list"}))

    with pytest.raises(ReviewBoardConfigError):
        ReviewBoard.from_config_file(path)
