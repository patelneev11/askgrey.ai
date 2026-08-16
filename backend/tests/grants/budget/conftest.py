from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.services.grants.budget import (
    BudgetCalculator,
    BudgetRequest,
    CostCategory,
    CostLine,
    PersonnelLine,
)


def person(**overrides: Any) -> PersonnelLine:
    base: dict[str, Any] = {
        "role": "Principal Investigator",
        "name": "A. Grey",
        "base_salary_annual": Decimal("120000"),
        "effort_percent": Decimal("50"),
        "months": Decimal("6"),
        "fringe_rate_percent": Decimal("0"),
    }
    base.update(overrides)
    return PersonnelLine(**base)


def cost(category: CostCategory, amount: str, description: str = "line") -> CostLine:
    return CostLine(category=category, description=description, unit_cost=Decimal(amount))


def request(**overrides: Any) -> BudgetRequest:
    """A minimal one-person budget with no fringe, so tests can do the arithmetic by hand."""
    base: dict[str, Any] = {
        "period_months": 6,
        "organization": "Grey Therapeutics",
        "project_title": "Organoid screen",
        "personnel": [person()],
        "costs": [],
        "indirect_rate_percent": Decimal("0"),
        "fee_percent": Decimal("0"),
    }
    base.update(overrides)
    return BudgetRequest(**base)


@pytest.fixture
def calculator() -> BudgetCalculator:
    return BudgetCalculator.from_config_file()
