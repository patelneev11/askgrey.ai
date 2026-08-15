from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.services.grants.eligibility import AwardPhase

from .errors import BudgetConfigError
from .models import CostCategory

DEFAULT_RULES_PATH = Path(__file__).with_name("rules.json")


class SalaryCapRule(BaseModel):
    """The annual salary a federal award will pay against, however much the person earns."""

    enabled: bool = True
    annual_amount: Decimal = Field(ge=0)
    authority: str = ""


class FringeRule(BaseModel):
    default_rate_percent: Decimal = Field(ge=0, le=100)
    authority: str = ""


class IndirectRule(BaseModel):
    """
    Indirect costs and the base they are charged on.

    `excluded_categories` and `subaward_mtdc_cap` define the modified total direct cost base:
    equipment and participant support come out entirely, and only the first `subaward_mtdc_cap`
    of each subaward stays in.
    """

    de_minimis_rate_percent: Decimal = Field(ge=0, le=100)
    subaward_mtdc_cap: Decimal = Field(ge=0)
    excluded_categories: list[CostCategory] = Field(default_factory=list)
    authority: str = ""


class FeeRule(BaseModel):
    """Profit, which SBIR/STTR allows and most other federal research awards do not."""

    default_percent: Decimal = Field(ge=0, le=100)
    max_percent: Decimal = Field(ge=0, le=100)
    authority: str = ""


class AwardGuideline(BaseModel):
    """The published guideline award size for a phase. A ceiling, not a hard rule."""

    phase: AwardPhase
    ceiling: Decimal = Field(ge=0)
    period_months: int = Field(gt=0)


class BudgetRules(BaseModel):
    version: str = ""
    notes: str = ""
    salary_cap: SalaryCapRule
    fringe: FringeRule
    indirect: IndirectRule
    fee: FeeRule
    award_guidelines: list[AwardGuideline] = Field(default_factory=list)

    def guideline(self, phase: AwardPhase) -> AwardGuideline | None:
        for entry in self.award_guidelines:
            if entry.phase is phase:
                return entry
        return None


def load_budget_rules(path: Path | None = None) -> BudgetRules:
    """Load the budget rules. Callers pass `path` to cost a budget against a modified copy."""
    source = path or DEFAULT_RULES_PATH
    try:
        payload = json.loads(source.read_text(), parse_float=Decimal)
    except FileNotFoundError as exc:
        raise BudgetConfigError(f"no budget rules at {source}") from exc
    except json.JSONDecodeError as exc:
        raise BudgetConfigError(f"budget rules at {source} are not valid JSON") from exc

    try:
        rules = BudgetRules.model_validate(payload)
    except ValidationError as exc:
        raise BudgetConfigError(f"budget rules at {source} are malformed: {exc}") from exc

    if rules.fee.default_percent > rules.fee.max_percent:
        raise BudgetConfigError(
            f"default fee {rules.fee.default_percent}% exceeds the maximum "
            f"{rules.fee.max_percent}% in {source}"
        )
    return rules
