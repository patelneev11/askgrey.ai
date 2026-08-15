from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.grants.budget import (
    BudgetCalculator,
    BudgetSection,
    CostCategory,
    GrantBudget,
    load_budget_rules,
)
from app.services.grants.budget.errors import BudgetInputError
from app.services.grants.eligibility import AwardPhase

from .conftest import cost, person, request


def adjustment_ids(budget: GrantBudget) -> list[str]:
    return [entry.rule_id for entry in budget.adjustments]


def section(budget: GrantBudget, code: str) -> BudgetSection:
    found = budget.section(code)
    assert found is not None, f"budget has no section {code}"
    return found


def test_salary_is_base_times_effort_times_months(calculator: BudgetCalculator) -> None:
    budget = calculator.build(request())
    # $120,000 x 50% effort x 6/12 of a year.
    assert section(budget, "A").lines[0].amount == Decimal("30000.00")
    assert budget.total_direct == Decimal("30000.00")


def test_fringe_is_charged_on_the_salary_actually_requested(
    calculator: BudgetCalculator,
) -> None:
    budget = calculator.build(request(personnel=[person(fringe_rate_percent=Decimal("32.5"))]))
    salary, fringe = section(budget, "A").lines
    assert salary.amount == Decimal("30000.00")
    assert fringe.amount == Decimal("9750.00")


def test_fringe_falls_back_to_the_configured_default_rate(calculator: BudgetCalculator) -> None:
    budget = calculator.build(request(personnel=[person(fringe_rate_percent=None)]))
    fringe = section(budget, "A").lines[1]
    rate = load_budget_rules().fringe.default_rate_percent
    assert fringe.amount == Decimal("30000.00") * rate / 100


@pytest.mark.parametrize(
    ("base_salary", "expected_salary", "capped"),
    [
        ("225699", "112849.50", False),
        ("225700", "112850.00", False),
        ("225701", "112850.00", True),
        ("400000", "112850.00", True),
    ],
)
def test_the_salary_cap_bites_only_above_the_cap(
    calculator: BudgetCalculator, base_salary: str, expected_salary: str, capped: bool
) -> None:
    budget = calculator.build(
        request(
            personnel=[
                person(
                    base_salary_annual=Decimal(base_salary),
                    effort_percent=Decimal("100"),
                    months=Decimal("6"),
                )
            ]
        )
    )
    assert section(budget, "A").lines[0].amount == Decimal(expected_salary)
    assert ("salary_cap" in adjustment_ids(budget)) is capped


def test_the_capped_salary_adjustment_states_what_the_company_absorbs(
    calculator: BudgetCalculator,
) -> None:
    budget = calculator.build(
        request(
            personnel=[person(base_salary_annual=Decimal("325700"), effort_percent=Decimal("100"))]
        )
    )
    (capped,) = [a for a in budget.adjustments if a.rule_id == "salary_cap"]
    # $100,000 of over-cap salary, half a year of it.
    assert capped.amount == Decimal("-50000.00")
    assert "absorbs" in capped.message


def test_equipment_and_participant_support_leave_the_indirect_base(
    calculator: BudgetCalculator,
) -> None:
    budget = calculator.build(
        request(
            indirect_rate_percent=Decimal("40"),
            costs=[
                cost(CostCategory.EQUIPMENT, "50000", "Plate reader"),
                cost(CostCategory.PARTICIPANT_SUPPORT, "10000", "Trainee stipends"),
                cost(CostCategory.MATERIALS, "5000", "Reagents"),
            ],
        )
    )
    assert budget.total_direct == Decimal("95000.00")
    assert budget.indirect_base == Decimal("35000.00")  # salary + reagents only
    assert budget.indirect == Decimal("14000.00")
    assert adjustment_ids(budget).count("mtdc_exclusion") == 2


@pytest.mark.parametrize(
    ("subaward", "expected_base", "capped"),
    [
        ("24999", "54999.00", False),
        ("25000", "55000.00", False),
        ("25001", "55000.00", True),
        ("90000", "55000.00", True),
    ],
)
def test_only_the_first_25k_of_a_subaward_sits_in_the_base(
    calculator: BudgetCalculator, subaward: str, expected_base: str, capped: bool
) -> None:
    budget = calculator.build(
        request(costs=[cost(CostCategory.SUBAWARD, subaward, "University lab")])
    )
    assert budget.indirect_base == Decimal(expected_base)
    assert ("subaward_mtdc_cap" in adjustment_ids(budget)) is capped


def test_a_missing_negotiated_rate_falls_back_to_de_minimis_and_says_so(
    calculator: BudgetCalculator,
) -> None:
    budget = calculator.build(request(indirect_rate_percent=None))
    assert budget.indirect_rate_percent == Decimal("15.0")
    assert budget.indirect == Decimal("4500.00")
    assert "de_minimis_indirect_rate" in adjustment_ids(budget)


def test_a_zero_negotiated_rate_is_not_a_missing_one(calculator: BudgetCalculator) -> None:
    budget = calculator.build(request(indirect_rate_percent=Decimal("0")))
    assert budget.indirect == Decimal("0.00")
    assert "de_minimis_indirect_rate" not in adjustment_ids(budget)


@pytest.mark.parametrize(
    ("requested_fee", "applied_fee", "clipped"),
    [("0", "0", False), ("6.9", "6.9", False), ("7", "7", False), ("7.1", "7", True)],
)
def test_the_fee_is_clipped_at_the_configured_maximum(
    calculator: BudgetCalculator, requested_fee: str, applied_fee: str, clipped: bool
) -> None:
    budget = calculator.build(request(fee_percent=Decimal(requested_fee)))
    assert budget.fee_percent == Decimal(applied_fee)
    assert budget.fee == Decimal("30000.00") * Decimal(applied_fee) / 100
    assert ("fee_cap" in adjustment_ids(budget)) is clipped


def test_the_fee_is_charged_on_direct_and_indirect_costs(calculator: BudgetCalculator) -> None:
    budget = calculator.build(
        request(indirect_rate_percent=Decimal("50"), fee_percent=Decimal("7"))
    )
    assert budget.total_direct == Decimal("30000.00")
    assert budget.indirect == Decimal("15000.00")
    assert budget.total_direct_and_indirect == Decimal("45000.00")
    assert budget.fee == Decimal("3150.00")
    assert budget.total == Decimal("48150.00")


def test_every_printed_section_adds_up_to_the_printed_total(
    calculator: BudgetCalculator,
) -> None:
    budget = calculator.build(
        request(
            indirect_rate_percent=Decimal("37.5"),
            fee_percent=Decimal("7"),
            personnel=[
                person(effort_percent=Decimal("33.33"), fringe_rate_percent=Decimal("28.7")),
                person(name="B. Ash", key_person=False, effort_percent=Decimal("12.5")),
            ],
            costs=[
                cost(CostCategory.TRAVEL, "3333.33", "Conference"),
                cost(CostCategory.MATERIALS, "1111.11", "Reagents"),
                cost(CostCategory.EQUIPMENT, "7777.77", "Incubator"),
            ],
        )
    )
    printed = sum(line.amount for part in budget.sections for line in part.lines)
    assert printed == budget.total
    assert budget.total_direct == sum(
        (section(budget, code).subtotal for code in "ABCDEF"), Decimal(0)
    )
    assert budget.total == budget.total_direct + budget.indirect + budget.fee


def test_amounts_are_rounded_to_cents(calculator: BudgetCalculator) -> None:
    budget = calculator.build(
        request(personnel=[person(base_salary_annual=Decimal("100001"))]),
    )
    salary = section(budget, "A").lines[0].amount
    assert salary == Decimal("25000.25")
    assert salary.as_tuple().exponent == -2


def test_going_over_the_phase_guideline_warns_rather_than_fails(
    calculator: BudgetCalculator,
) -> None:
    budget = calculator.build(
        request(costs=[cost(CostCategory.MATERIALS, "400000", "Manufacturing run")])
    )
    assert budget.total > Decimal("314363")
    assert any("guideline" in warning for warning in budget.warnings)


def test_a_budget_inside_the_guideline_is_quiet(calculator: BudgetCalculator) -> None:
    assert calculator.build(request()).warnings == []


def test_a_period_longer_than_the_phase_normally_runs_warns(
    calculator: BudgetCalculator,
) -> None:
    budget = calculator.build(request(period_months=18))
    assert any("18-month period" in warning for warning in budget.warnings)


def test_effort_beyond_the_project_period_warns(calculator: BudgetCalculator) -> None:
    budget = calculator.build(request(period_months=6, personnel=[person(months=Decimal("9"))]))
    assert any("longer than the 6-month project period" in w for w in budget.warnings)


def test_phase_ii_uses_its_own_guideline(calculator: BudgetCalculator) -> None:
    budget = calculator.build(
        request(
            phase=AwardPhase.PHASE_II,
            period_months=24,
            costs=[cost(CostCategory.MATERIALS, "400000", "Manufacturing run")],
        )
    )
    assert budget.warnings == []


def test_an_empty_request_is_refused_rather_than_costed_at_zero(
    calculator: BudgetCalculator,
) -> None:
    with pytest.raises(BudgetInputError):
        calculator.build(request(personnel=[], costs=[]))


def test_the_rules_version_is_stamped_on_the_budget(calculator: BudgetCalculator) -> None:
    assert calculator.build(request()).rules_version == load_budget_rules().version
