from __future__ import annotations

from pathlib import Path

from app.services.grants.errors import InvalidQueryError
from app.services.grants.models import GrantProgram

from .config import RuleConfig, load_rule_config
from .errors import EligibilityConfigError
from .models import CompanyProfile, EligibilityReport
from .rules import EVALUATORS, evaluate_rule

SUPPORTED_PROGRAMS = (GrantProgram.SBIR, GrantProgram.STTR)


class EligibilityChecker:
    """
    Evaluates a company profile against the rules in `rules.json`.

    Every verdict comes from an explicit threshold in that config: no model is consulted, so the
    same profile always produces the same report. What the rules cannot decide is returned as
    `needs_review` rather than guessed at.
    """

    def __init__(self, config: RuleConfig) -> None:
        unknown = [rule.id for rule in config.rules if rule.id not in EVALUATORS]
        if unknown:
            raise EligibilityConfigError(
                "no evaluator implements rule(s): " + ", ".join(sorted(unknown))
            )
        self.config = config

    @classmethod
    def from_config_file(cls, path: Path | None = None) -> EligibilityChecker:
        return cls(load_rule_config(path))

    def check(self, profile: CompanyProfile, program: GrantProgram) -> EligibilityReport:
        if program not in SUPPORTED_PROGRAMS:
            raise InvalidQueryError(
                f"eligibility rules are defined for SBIR and STTR, not {program.value}"
            )
        outcomes = [
            evaluate_rule(rule, profile, program, EVALUATORS[rule.id])
            for rule in self.config.for_program(program)
        ]
        return EligibilityReport(
            program=program,
            phase=profile.phase,
            config_version=self.config.version,
            outcomes=outcomes,
        )

    def check_all(self, profile: CompanyProfile) -> dict[GrantProgram, EligibilityReport]:
        """Both programmes at once: a concern that fails SBIR often still qualifies for STTR."""
        return {program: self.check(profile, program) for program in SUPPORTED_PROGRAMS}
