from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.services.grants.models import GrantProgram

from .errors import EligibilityConfigError

DEFAULT_RULES_PATH = Path(__file__).with_name("rules.json")


class RuleSpec(BaseModel):
    """
    One rule as written in `rules.json`.

    Thresholds live in `parameters` and are always numeric: an eligibility threshold that cannot
    be written as a number is a judgement call, and judgement calls belong in `needs_review`
    rather than in a config file.
    """

    id: str
    title: str
    citation: str = ""
    applies_to: list[GrantProgram] = Field(default_factory=list)
    enabled: bool = True
    parameters: dict[str, float] = Field(default_factory=dict)

    def applies(self, program: GrantProgram) -> bool:
        return self.enabled and program in self.applies_to

    def number(self, name: str) -> float:
        """Read a threshold, failing loudly: a typo in the config must not silently pass a rule."""
        if name not in self.parameters:
            raise EligibilityConfigError(f"rule '{self.id}' is missing parameter '{name}'")
        return self.parameters[name]


class RuleConfig(BaseModel):
    """The editable rule set, versioned so a report can say which thresholds produced it."""

    version: str = ""
    notes: str = ""
    rules: list[RuleSpec] = Field(default_factory=list)

    def for_program(self, program: GrantProgram) -> list[RuleSpec]:
        return [rule for rule in self.rules if rule.applies(program)]


def load_rule_config(path: Path | None = None) -> RuleConfig:
    """Load the rule set from disk. Callers pass `path` to evaluate against a modified copy."""
    source = path or DEFAULT_RULES_PATH
    try:
        payload = json.loads(source.read_text())
    except FileNotFoundError as exc:
        raise EligibilityConfigError(f"no eligibility rules at {source}") from exc
    except json.JSONDecodeError as exc:
        raise EligibilityConfigError(f"eligibility rules at {source} are not valid JSON") from exc

    try:
        config = RuleConfig.model_validate(payload)
    except ValidationError as exc:
        raise EligibilityConfigError(f"eligibility rules at {source} are malformed: {exc}") from exc

    ids = [rule.id for rule in config.rules]
    duplicates = {rule_id for rule_id in ids if ids.count(rule_id) > 1}
    if duplicates:
        listed = ", ".join(sorted(duplicates))
        raise EligibilityConfigError(f"duplicate rule ids in {source}: {listed}")
    return config
