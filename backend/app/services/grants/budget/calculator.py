from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.services.grants.eligibility import AwardPhase

from .config import BudgetRules, load_budget_rules
from .errors import BudgetInputError
from .models import (
    Adjustment,
    BudgetLine,
    BudgetRequest,
    BudgetSection,
    CostCategory,
    CostLine,
    GrantBudget,
    PersonnelLine,
    money,
)

HUNDRED = Decimal(100)
MONTHS_IN_YEAR = Decimal(12)

SECTION_TITLES: dict[str, str] = {
    "A": "Senior/Key Person",
    "B": "Other Personnel",
    "C": "Equipment",
    "D": "Travel",
    "E": "Participant/Trainee Support Costs",
    "F": "Other Direct Costs",
    "H": "Indirect Costs",
    "J": "Fee",
}

# Which SF-424 (R&R) section each direct-cost category prints in.
CATEGORY_SECTIONS: dict[CostCategory, str] = {
    CostCategory.EQUIPMENT: "C",
    CostCategory.TRAVEL: "D",
    CostCategory.PARTICIPANT_SUPPORT: "E",
    CostCategory.MATERIALS: "F",
    CostCategory.CONSULTANT: "F",
    CostCategory.SUBAWARD: "F",
    CostCategory.OTHER: "F",
}


def _dollars(value: Decimal) -> str:
    return f"${money(value):,}"


def _percent(value: Decimal) -> str:
    return f"{value.normalize():f}%"


class BudgetCalculator:
    """
    Turns internal cost estimates into a costed SF-424 (R&R) budget.

    Every federal rule applied — the salary cap, the MTDC base, the fee ceiling — comes from
    `rules.json`, and every one that changed a requested number leaves an `Adjustment` behind.
    The arithmetic is `Decimal` throughout and rounded to cents exactly once per line, so the
    printed sections add up to the printed total.
    """

    def __init__(self, rules: BudgetRules) -> None:
        self.rules = rules

    @classmethod
    def from_config_file(cls, path: Path | None = None) -> BudgetCalculator:
        return cls(load_budget_rules(path))

    def build(self, request: BudgetRequest) -> GrantBudget:
        if not request.personnel and not request.costs:
            raise BudgetInputError("a budget needs at least one personnel or cost line")

        adjustments: list[Adjustment] = []
        warnings: list[str] = []
        sections: dict[str, BudgetSection] = {
            code: BudgetSection(code=code, title=title) for code, title in SECTION_TITLES.items()
        }

        salary_and_fringe = Decimal(0)
        for person in request.personnel:
            code = "A" if person.key_person else "B"
            salary, fringe = self._personnel_lines(person, request, adjustments, warnings)
            sections[code].lines.extend([salary, fringe])
            salary_and_fringe += salary.amount + fringe.amount

        mtdc = salary_and_fringe
        for cost in request.costs:
            line, in_base = self._cost_line(cost, adjustments)
            sections[CATEGORY_SECTIONS[cost.category]].lines.append(line)
            mtdc += in_base

        rate = self._indirect_rate(request, adjustments)
        indirect = money(mtdc * rate / HUNDRED)
        sections["H"].lines.append(
            BudgetLine(
                label=f"Indirect costs at {_percent(rate)} of modified total direct costs",
                basis=f"{_percent(rate)} x {_dollars(mtdc)} MTDC base",
                amount=indirect,
            )
        )

        budget = GrantBudget(
            program=request.program,
            phase=request.phase,
            period_months=request.period_months,
            organization=request.organization,
            project_title=request.project_title,
            rules_version=self.rules.version,
            sections=[sections[code] for code in ("A", "B", "C", "D", "E", "F", "H")],
            indirect_base=money(mtdc),
            indirect_rate_percent=rate,
        )

        fee_percent = self._fee_percent(request, adjustments)
        fee_base = budget.total_direct_and_indirect
        fee_section = sections["J"]
        fee_section.lines.append(
            BudgetLine(
                label=f"Fee at {_percent(fee_percent)}",
                basis=f"{_percent(fee_percent)} x {_dollars(fee_base)} direct and indirect costs",
                amount=money(fee_base * fee_percent / HUNDRED),
            )
        )
        budget.sections.append(fee_section)
        budget.fee_percent = fee_percent

        budget.adjustments = adjustments
        budget.warnings = warnings + self._guideline_warnings(budget)
        return budget

    def _personnel_lines(
        self,
        person: PersonnelLine,
        request: BudgetRequest,
        adjustments: list[Adjustment],
        warnings: list[str],
    ) -> tuple[BudgetLine, BudgetLine]:
        cap = self.rules.salary_cap
        base = person.base_salary_annual
        capped = min(base, cap.annual_amount) if cap.enabled else base
        who = person.name or person.role

        effort = person.effort_percent * person.months / (HUNDRED * MONTHS_IN_YEAR)
        salary = money(capped * effort)
        if capped < base:
            adjustments.append(
                Adjustment(
                    rule_id="salary_cap",
                    message=(
                        f"{who}'s base salary of {_dollars(base)} is above the "
                        f"{_dollars(cap.annual_amount)} federal cap, so the request is computed "
                        f"on the cap. The company absorbs the difference — "
                        f"{_dollars((base - capped) * effort)} over this period."
                    ),
                    amount=-money((base - capped) * effort),
                    authority=cap.authority,
                )
            )
        if person.months > request.period_months:
            warnings.append(
                f"{who} is budgeted for {person.months.normalize():f} months, longer than the "
                f"{request.period_months}-month project period."
            )

        fringe_rate = (
            person.fringe_rate_percent
            if person.fringe_rate_percent is not None
            else self.rules.fringe.default_rate_percent
        )
        salary_line = BudgetLine(
            label=f"{who} — {person.role}" if person.name else person.role,
            basis=(
                f"{_percent(person.effort_percent)} effort x {person.months.normalize():f} months "
                f"on a {_dollars(capped)} base"
            ),
            amount=salary,
        )
        fringe_line = BudgetLine(
            label=f"{who} — fringe benefits",
            basis=f"{_percent(fringe_rate)} of {_dollars(salary)} salary",
            amount=money(salary * fringe_rate / HUNDRED),
        )
        return salary_line, fringe_line

    def _cost_line(
        self, cost: CostLine, adjustments: list[Adjustment]
    ) -> tuple[BudgetLine, Decimal]:
        """Return the printed line and the part of it that sits in the MTDC base."""
        amount = money(cost.amount)
        basis = (
            f"{cost.quantity.normalize():f} x {_dollars(cost.unit_cost)}"
            if cost.quantity != 1
            else _dollars(cost.unit_cost)
        )
        line = BudgetLine(
            label=cost.description, basis=basis, amount=amount, category=cost.category
        )

        indirect = self.rules.indirect
        if cost.category in indirect.excluded_categories:
            adjustments.append(
                Adjustment(
                    rule_id="mtdc_exclusion",
                    message=(
                        f"{cost.description} ({cost.category.value.replace('_', ' ')}, "
                        f"{_dollars(amount)}) is excluded from the base indirect costs are "
                        "charged on."
                    ),
                    authority=indirect.authority,
                )
            )
            return line, Decimal(0)

        if cost.category is CostCategory.SUBAWARD and amount > indirect.subaward_mtdc_cap:
            adjustments.append(
                Adjustment(
                    rule_id="subaward_mtdc_cap",
                    message=(
                        f"Only the first {_dollars(indirect.subaward_mtdc_cap)} of the "
                        f"{_dollars(amount)} subaward to {cost.description} counts towards the "
                        "MTDC base."
                    ),
                    authority=indirect.authority,
                )
            )
            return line, indirect.subaward_mtdc_cap
        return line, amount

    def _indirect_rate(self, request: BudgetRequest, adjustments: list[Adjustment]) -> Decimal:
        if request.indirect_rate_percent is not None:
            return request.indirect_rate_percent
        de_minimis = self.rules.indirect.de_minimis_rate_percent
        adjustments.append(
            Adjustment(
                rule_id="de_minimis_indirect_rate",
                message=(
                    f"No negotiated indirect cost rate was given, so the de minimis rate of "
                    f"{_percent(de_minimis)} is used. A negotiated rate agreement usually "
                    "recovers more."
                ),
                authority=self.rules.indirect.authority,
            )
        )
        return de_minimis

    def _fee_percent(self, request: BudgetRequest, adjustments: list[Adjustment]) -> Decimal:
        fee = self.rules.fee
        requested = request.fee_percent if request.fee_percent is not None else fee.default_percent
        if requested > fee.max_percent:
            adjustments.append(
                Adjustment(
                    rule_id="fee_cap",
                    message=(
                        f"A fee of {_percent(requested)} was requested; the maximum allowed is "
                        f"{_percent(fee.max_percent)}, so the budget requests that instead."
                    ),
                    authority=fee.authority,
                )
            )
            return fee.max_percent
        return requested

    def _guideline_warnings(self, budget: GrantBudget) -> list[str]:
        guideline = self.rules.guideline(budget.phase)
        if guideline is None:
            return []
        warnings = []
        if budget.total > guideline.ceiling:
            over = money(budget.total - guideline.ceiling)
            warnings.append(
                f"{_dollars(budget.total)} exceeds the {_dollars(guideline.ceiling)} guideline "
                f"for {_phase_label(budget.phase)} by {_dollars(over)}. Agencies can accept a "
                "larger budget, but it needs their prior approval."
            )
        if budget.period_months > guideline.period_months:
            warnings.append(
                f"A {budget.period_months}-month period is longer than the "
                f"{guideline.period_months} months {_phase_label(budget.phase)} normally runs."
            )
        return warnings


PHASE_LABELS: dict[AwardPhase, str] = {
    AwardPhase.PHASE_I: "Phase I",
    AwardPhase.PHASE_II: "Phase II",
    AwardPhase.DIRECT_PHASE_II: "Direct-to-Phase-II",
}


def _phase_label(phase: AwardPhase) -> str:
    return PHASE_LABELS[phase]
