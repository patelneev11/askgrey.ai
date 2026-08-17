from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from pydantic import BaseModel, Field, computed_field

from app.services.grants.eligibility import AwardPhase
from app.services.grants.models import GrantProgram

CENTS = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """
    Round to cents, half up.

    Every amount that reaches a template line is rounded here and only here, so the section
    subtotals are sums of the rounded lines rather than a rounded sum of unrounded ones — the
    printed column always adds up.
    """
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


class CostCategory(str, Enum):
    """
    Direct-cost categories, named for the SF-424 (R&R) section they land in.

    `EQUIPMENT` and `PARTICIPANT_SUPPORT` are separated from the rest because they are excluded
    from the modified total direct cost base that indirect costs are charged on.
    """

    EQUIPMENT = "equipment"
    TRAVEL = "travel"
    PARTICIPANT_SUPPORT = "participant_support"
    MATERIALS = "materials"
    CONSULTANT = "consultant"
    SUBAWARD = "subaward"
    OTHER = "other"


class PersonnelLine(BaseModel):
    """
    One person's salary request.

    `base_salary_annual` is the institutional base salary — what the person is paid for a full
    year of work, before any cap is applied. The cap is applied by the calculator, never by the
    caller, so an over-cap salary is visible in the input and explained in the output.
    """

    role: str = Field(max_length=120)
    name: str = Field(default="", max_length=120)
    key_person: bool = True
    base_salary_annual: Decimal = Field(ge=0)
    effort_percent: Decimal = Field(gt=0, le=100)
    months: Decimal = Field(gt=0, le=60)
    fringe_rate_percent: Decimal | None = Field(default=None, ge=0, le=100)


class CostLine(BaseModel):
    """One non-salary direct cost. `amount` is `quantity * unit_cost`, unrounded."""

    category: CostCategory
    description: str = Field(max_length=200)
    quantity: Decimal = Field(default=Decimal(1), gt=0)
    unit_cost: Decimal = Field(ge=0)

    @property
    def amount(self) -> Decimal:
        return self.quantity * self.unit_cost


class BudgetRequest(BaseModel):
    """
    Internal R&D cost estimates, before any federal rule is applied.

    `indirect_rate_percent` is the organization's negotiated rate. Leaving it unset is not the
    same as zero: the calculator falls back to the de minimis rate and says so.
    """

    program: GrantProgram = GrantProgram.SBIR
    phase: AwardPhase = AwardPhase.PHASE_I
    period_months: int = Field(default=6, gt=0, le=60)
    organization: str = Field(default="", max_length=200)
    project_title: str = Field(default="", max_length=300)
    # Bounded so one request cannot ask for an unbounded amount of arithmetic and response body.
    personnel: list[PersonnelLine] = Field(default_factory=list, max_length=50)
    costs: list[CostLine] = Field(default_factory=list, max_length=200)
    indirect_rate_percent: Decimal | None = Field(default=None, ge=0, le=200)
    fee_percent: Decimal | None = Field(default=None, ge=0, le=100)


class BudgetLine(BaseModel):
    """
    One printed line of the template.

    `basis` is the arithmetic in words — "25% effort x 6.0 months on a $225,700.00 base" — so a
    reviewer can check a number without reopening the calculator.
    """

    label: str
    basis: str
    amount: Decimal
    category: CostCategory | None = None


class BudgetSection(BaseModel):
    """An SF-424 (R&R) section: its letter, its lines, and their subtotal."""

    code: str
    title: str
    lines: list[BudgetLine] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def subtotal(self) -> Decimal:
        return money(sum((line.amount for line in self.lines), Decimal(0)))


class Adjustment(BaseModel):
    """
    A place where a federal rule changed the requested number.

    `amount` is the effect on the request: negative where the rule removed money the company
    still has to spend, zero where the rule only constrains how a number was derived.
    """

    rule_id: str
    message: str
    amount: Decimal = Decimal(0)
    authority: str = ""


class GrantBudget(BaseModel):
    """
    A costed budget in SF-424 (R&R) shape.

    Sections A-F are direct costs, G is their total, H is indirect, I is G+H, J is fee and K is
    the total request. `adjustments` explains every difference between what was asked for and
    what is requested here.
    """

    program: GrantProgram
    phase: AwardPhase
    period_months: int
    organization: str = ""
    project_title: str = ""
    rules_version: str = ""
    sections: list[BudgetSection] = Field(default_factory=list)
    indirect_base: Decimal = Decimal(0)
    indirect_rate_percent: Decimal = Decimal(0)
    fee_percent: Decimal = Decimal(0)
    adjustments: list[Adjustment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def section(self, code: str) -> BudgetSection | None:
        for section in self.sections:
            if section.code == code:
                return section
        return None

    def _subtotal(self, code: str) -> Decimal:
        section = self.section(code)
        return section.subtotal if section else Decimal("0.00")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_direct(self) -> Decimal:
        """Section G: A through F."""
        return money(sum((self._subtotal(code) for code in "ABCDEF"), Decimal(0)))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def indirect(self) -> Decimal:
        return self._subtotal("H")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_direct_and_indirect(self) -> Decimal:
        """Section I."""
        return money(self.total_direct + self.indirect)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fee(self) -> Decimal:
        return self._subtotal("J")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> Decimal:
        """Section K: the number the agency is asked for."""
        return money(self.total_direct_and_indirect + self.fee)
