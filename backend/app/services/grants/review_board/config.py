from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import ReviewBoardConfigError

DEFAULT_PERSONAS_PATH = Path(__file__).with_name("personas.json")


class PersonaSpec(BaseModel):
    """
    One reviewer persona as written in `personas.json`.

    `system_prompt` is the whole of what makes a persona: nothing about a reviewer's stance
    lives in code, so a board can be re-cast by editing this file. `criteria` are the criteria
    this persona scores *in addition to* the NIH core three in `core_criteria`, which every
    persona scores. Unknown keys are rejected rather than ignored, so a typo in a persona is a
    config error instead of a silently missing reviewer.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    focus: str = ""
    system_prompt: str = Field(min_length=1)
    criteria: list[str] = Field(default_factory=list)
    enabled: bool = True


class PersonaConfig(BaseModel):
    """The editable board, versioned so a report can say which personas produced it."""

    model_config = ConfigDict(extra="forbid")

    version: str = ""
    notes: str = ""
    core_criteria: list[str] = Field(default_factory=list)
    personas: list[PersonaSpec] = Field(default_factory=list)

    @property
    def enabled_personas(self) -> list[PersonaSpec]:
        return [persona for persona in self.personas if persona.enabled]

    def criteria_for(self, persona: PersonaSpec) -> list[str]:
        """The core NIH criteria first, then whatever this persona adds, deduplicated."""
        return list(dict.fromkeys([*self.core_criteria, *persona.criteria]))


def load_persona_config(path: Path | None = None) -> PersonaConfig:
    """Load the board. Callers pass `path` to review against a modified copy."""
    source = path or DEFAULT_PERSONAS_PATH
    try:
        payload = json.loads(source.read_text())
    except FileNotFoundError as exc:
        raise ReviewBoardConfigError(f"no review personas at {source}") from exc
    except json.JSONDecodeError as exc:
        raise ReviewBoardConfigError(f"review personas at {source} are not valid JSON") from exc

    try:
        config = PersonaConfig.model_validate(payload)
    except ValidationError as exc:
        raise ReviewBoardConfigError(f"review personas at {source} are malformed: {exc}") from exc

    if not config.core_criteria:
        raise ReviewBoardConfigError(f"review personas at {source} define no core_criteria")

    ids = [persona.id for persona in config.personas]
    duplicates = {persona_id for persona_id in ids if ids.count(persona_id) > 1}
    if duplicates:
        listed = ", ".join(sorted(duplicates))
        raise ReviewBoardConfigError(f"duplicate persona ids in {source}: {listed}")

    if not config.enabled_personas:
        raise ReviewBoardConfigError(f"no persona is enabled in {source}")
    return config
