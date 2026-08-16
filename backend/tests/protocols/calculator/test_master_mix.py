from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.services.protocols.calculator import (
    MasterMixRequest,
    UnitMismatchError,
    scale_master_mix,
    solution_mass,
    stock_ratio,
)
from app.services.protocols.calculator.models import (
    SolutionMassRequest,
    StockRatioRequest,
)


def mix(**kwargs: object) -> MasterMixRequest:
    payload: dict[str, object] = {
        "components": [
            {"name": "2x qPCR master mix", "per_reaction_volume": {"value": "10", "unit": "uL"}},
            {"name": "Primer pair (10 µM)", "per_reaction_volume": {"value": "2", "unit": "uL"}},
            {"name": "Nuclease-free water", "per_reaction_volume": {"value": "6", "unit": "uL"}},
        ],
        "reactions": 96,
    }
    payload.update(kwargs)
    return MasterMixRequest.model_validate(payload)


def test_scales_by_well_count_with_default_overage() -> None:
    result = scale_master_mix(mix())

    assert result.effective_reactions == Decimal("105.6")
    volumes = {line.name: line.total_volume.value for line in result.lines}
    assert volumes["2x qPCR master mix"] == Decimal("1056")
    assert volumes["Primer pair (10 µM)"] == Decimal("211.2")
    assert volumes["Nuclease-free water"] == Decimal("633.6")
    assert result.per_reaction_volume.value == Decimal("18")
    assert result.total_volume.value == Decimal("1900.8")


def test_component_totals_sum_to_the_reported_total() -> None:
    """Each line is rounded once from the unrounded factor, so the printed column adds up."""
    result = scale_master_mix(mix(reactions=7, overage_percent=Decimal("7.5")))

    assert sum(line.total_volume.value for line in result.lines) == result.total_volume.value


def test_replicates_multiply_the_reaction_count() -> None:
    result = scale_master_mix(mix(reactions=8, replicates=3, overage_percent=Decimal(0)))

    assert result.effective_reactions == Decimal("24")
    assert result.total_volume.value == Decimal("432")
    assert "24 wells" in result.notes[0]


def test_zero_overage_is_honoured_rather_than_defaulted() -> None:
    result = scale_master_mix(mix(reactions=10, overage_percent=Decimal(0)))

    assert result.effective_reactions == Decimal("10")
    assert result.total_volume.value == Decimal("180")
    assert "0% overage" in result.notes[0]


def test_overage_is_always_disclosed_in_the_basis() -> None:
    line = scale_master_mix(mix(reactions=48)).lines[0]

    assert line.basis == "10 uL x 52.8 reactions (48 x 1 replicate(s) + 10% overage)"


def test_totals_are_reported_in_the_first_component_unit() -> None:
    """A recipe mixing mL and µL lines still reports one total, in the leading line's unit."""
    result = scale_master_mix(
        MasterMixRequest.model_validate(
            {
                "components": [
                    {"name": "Media", "per_reaction_volume": {"value": "1", "unit": "mL"}},
                    {"name": "Compound", "per_reaction_volume": {"value": "10", "unit": "uL"}},
                ],
                "reactions": 6,
                "overage_percent": "0",
            }
        )
    )

    assert result.total_volume.unit.value == "mL"
    assert result.total_volume.value == Decimal("6.06")


@pytest.mark.parametrize(
    "payload",
    [
        {"reactions": 0},
        {"reactions": -5},
        {"components": []},
        {"overage_percent": Decimal("-1")},
        {"overage_percent": Decimal("101")},
    ],
)
def test_out_of_range_inputs_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        mix(**payload)


def test_stock_ratio_expresses_the_dilution_as_parts() -> None:
    result = stock_ratio(
        StockRatioRequest.model_validate(
            {
                "stock_concentration": {"value": "100", "unit": "X"},
                "final_concentration": {"value": "1", "unit": "X"},
                "final_volume": {"value": "50", "unit": "mL"},
            }
        )
    )

    assert result.stock_volume.value == Decimal("0.5")
    assert result.diluent_volume.value == Decimal("49.5")
    assert result.fold_dilution == Decimal("100")
    assert result.ratio_label == "1:100 (1 part stock in 100 total)"


def test_stock_ratio_handles_a_non_integer_fold() -> None:
    result = stock_ratio(
        StockRatioRequest.model_validate(
            {
                "stock_concentration": {"value": "5", "unit": "mg/mL"},
                "final_concentration": {"value": "1.5", "unit": "mg/mL"},
                "final_volume": {"value": "3", "unit": "mL"},
            }
        )
    )

    assert result.stock_volume.value == Decimal("0.9")
    assert result.diluent_volume.value == Decimal("2.1")
    assert result.fold_dilution == Decimal("3.33333")


def test_solution_mass_from_molarity() -> None:
    """1 L of 1 M NaCl (58.44 g/mol) is 58.44 g."""
    result = solution_mass(
        SolutionMassRequest.model_validate(
            {
                "concentration": {"value": "1", "unit": "M"},
                "volume": {"value": "1", "unit": "L"},
                "molecular_weight_g_per_mol": "58.44",
            }
        )
    )

    assert result.mass.value == Decimal("58.44")
    assert result.mass.unit.value == "g"


def test_solution_mass_picks_a_readable_unit() -> None:
    result = solution_mass(
        SolutionMassRequest.model_validate(
            {
                "concentration": {"value": "10", "unit": "mM"},
                "volume": {"value": "500", "unit": "uL"},
                "molecular_weight_g_per_mol": "381.37",
            }
        )
    )

    # 10 mM x 0.5 mL x 381.37 g/mol = 1.906850 mg
    assert result.mass.value == Decimal("1.90685")
    assert result.mass.unit.value == "mg"


def test_solution_mass_refuses_a_non_molar_concentration() -> None:
    with pytest.raises(UnitMismatchError):
        solution_mass(
            SolutionMassRequest.model_validate(
                {
                    "concentration": {"value": "100", "unit": "X"},
                    "volume": {"value": "1", "unit": "L"},
                    "molecular_weight_g_per_mol": "58.44",
                }
            )
        )
