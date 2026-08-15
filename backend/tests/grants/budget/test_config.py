from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.grants.budget import (
    DEFAULT_RULES_PATH,
    BudgetCalculator,
    BudgetConfigError,
    CostCategory,
    load_budget_rules,
)
from app.services.grants.eligibility import AwardPhase

from .conftest import cost, person, request


def edited_rules(tmp_path: Path, edit: dict[str, object]) -> Path:
    """The shipped rules with one block replaced, so tests prove the config drives behaviour."""
    payload = json.loads(DEFAULT_RULES_PATH.read_text())
    payload.update(edit)
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(payload))
    return path


def test_the_shipped_rules_load_and_carry_a_version() -> None:
    rules = load_budget_rules()
    assert rules.version
    assert rules.salary_cap.annual_amount > 0
    assert rules.guideline(AwardPhase.PHASE_I) is not None


def test_a_missing_config_is_an_error_not_a_silent_default(tmp_path: Path) -> None:
    with pytest.raises(BudgetConfigError):
        load_budget_rules(tmp_path / "absent.json")


def test_unparseable_config_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text("{ not json")
    with pytest.raises(BudgetConfigError):
        load_budget_rules(path)


def test_a_config_missing_a_rule_block_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(json.dumps({"version": "test"}))
    with pytest.raises(BudgetConfigError):
        load_budget_rules(path)


def test_a_default_fee_above_the_maximum_is_rejected(tmp_path: Path) -> None:
    path = edited_rules(
        tmp_path,
        {"fee": {"default_percent": "9.0", "max_percent": "7.0", "authority": "test"}},
    )
    with pytest.raises(BudgetConfigError):
        load_budget_rules(path)


def test_raising_the_salary_cap_in_config_raises_the_requested_salary(tmp_path: Path) -> None:
    path = edited_rules(tmp_path, {"salary_cap": {"enabled": True, "annual_amount": "400000.00"}})
    profile = request(
        personnel=[person(base_salary_annual=Decimal("300000"), effort_percent=Decimal("100"))]
    )

    shipped = BudgetCalculator.from_config_file().build(profile)
    edited = BudgetCalculator.from_config_file(path).build(profile)

    assert shipped.total_direct == Decimal("112850.00")
    assert edited.total_direct == Decimal("150000.00")
    assert [a.rule_id for a in edited.adjustments] == []


def test_disabling_the_salary_cap_pays_the_full_base(tmp_path: Path) -> None:
    path = edited_rules(tmp_path, {"salary_cap": {"enabled": False, "annual_amount": "225700.00"}})
    budget = BudgetCalculator.from_config_file(path).build(
        request(
            personnel=[person(base_salary_annual=Decimal("300000"), effort_percent=Decimal("100"))]
        )
    )
    assert budget.total_direct == Decimal("150000.00")


def test_widening_the_mtdc_subaward_cap_widens_the_indirect_base(tmp_path: Path) -> None:
    path = edited_rules(
        tmp_path,
        {
            "indirect": {
                "de_minimis_rate_percent": "15.0",
                "subaward_mtdc_cap": "100000.00",
                "excluded_categories": ["participant_support"],
                "authority": "test",
            }
        },
    )
    profile = request(
        costs=[
            cost(CostCategory.SUBAWARD, "60000", "University lab"),
            cost(CostCategory.EQUIPMENT, "20000", "Incubator"),
        ]
    )
    assert BudgetCalculator.from_config_file().build(profile).indirect_base == Decimal("55000.00")
    # Subaward now counts in full and equipment is no longer excluded.
    assert BudgetCalculator.from_config_file(path).build(profile).indirect_base == Decimal(
        "110000.00"
    )
