from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.protocols.calculator import (
    CalculatorInputError,
    DilutionRequest,
    DilutionVariable,
    UnitMismatchError,
    VolumeUnit,
    solve_dilution,
)


def request(**kwargs: object) -> DilutionRequest:
    return DilutionRequest.model_validate(kwargs)


def test_solves_stock_volume_across_unit_scales() -> None:
    """10 mM stock to 10 µM in 10 mL is 10 µL of stock — the classic 1:1000."""
    result = solve_dilution(
        request(
            stock_concentration={"value": "10", "unit": "mM"},
            final_concentration={"value": "10", "unit": "uM"},
            final_volume={"value": "10", "unit": "mL"},
        )
    )

    assert result.solved_for is DilutionVariable.STOCK_VOLUME
    assert result.stock_volume.value == Decimal("0.01")
    assert result.stock_volume.unit.value == "mL"
    assert result.diluent_volume.value == Decimal("9.99")
    assert result.fold_dilution == Decimal("1000")
    assert result.basis == "V1 = C2 x V2 / C1 = 10 uM x 10 mL / 10 mM"


def test_mixed_micro_and_milli_units_do_not_drift() -> None:
    """A µL final volume with an M stock still lands on an exact answer."""
    result = solve_dilution(
        request(
            stock_concentration={"value": "1", "unit": "M"},
            final_concentration={"value": "50", "unit": "mM"},
            final_volume={"value": "200", "unit": "uL"},
        )
    )

    assert result.stock_volume.value == Decimal("10")
    assert result.stock_volume.unit.value == "uL"
    assert result.diluent_volume.value == Decimal("190")


def test_solves_final_volume() -> None:
    result = solve_dilution(
        request(
            stock_concentration={"value": "100", "unit": "X"},
            stock_volume={"value": "5", "unit": "mL"},
            final_concentration={"value": "1", "unit": "X"},
        )
    )

    assert result.solved_for is DilutionVariable.FINAL_VOLUME
    assert result.final_volume.value == Decimal("500")
    assert result.diluent_volume.value == Decimal("495")


def test_solves_final_concentration() -> None:
    result = solve_dilution(
        request(
            stock_concentration={"value": "2", "unit": "mg/mL"},
            stock_volume={"value": "100", "unit": "uL"},
            final_volume={"value": "1", "unit": "mL"},
        )
    )

    assert result.solved_for is DilutionVariable.FINAL_CONCENTRATION
    assert result.final_concentration.value == Decimal("0.2")
    assert result.final_concentration.unit.value == "mg/mL"


def test_solves_stock_concentration() -> None:
    result = solve_dilution(
        request(
            stock_volume={"value": "1", "unit": "mL"},
            final_concentration={"value": "10", "unit": "uM"},
            final_volume={"value": "100", "unit": "mL"},
        )
    )

    assert result.solved_for is DilutionVariable.STOCK_CONCENTRATION
    assert result.stock_concentration.value == Decimal("1000")
    assert result.stock_concentration.unit.value == "uM"


def test_unit_family_mismatch_is_refused() -> None:
    with pytest.raises(UnitMismatchError):
        solve_dilution(
            request(
                stock_concentration={"value": "10", "unit": "mM"},
                final_concentration={"value": "10", "unit": "ug/mL"},
                final_volume={"value": "10", "unit": "mL"},
            )
        )


def test_fold_stock_cannot_be_mixed_with_molar() -> None:
    with pytest.raises(UnitMismatchError):
        solve_dilution(
            request(
                stock_concentration={"value": "100", "unit": "X"},
                final_concentration={"value": "1", "unit": "mM"},
                final_volume={"value": "10", "unit": "mL"},
            )
        )


@pytest.mark.parametrize(
    "payload",
    [
        # C1 = 0: dividing by it is undefined, and a zero-concentration stock cannot dilute.
        {
            "stock_concentration": {"value": "0", "unit": "mM"},
            "final_concentration": {"value": "0", "unit": "mM"},
            "final_volume": {"value": "10", "unit": "mL"},
        },
        # V1 = 0 when solving for C1.
        {
            "stock_volume": {"value": "0", "unit": "mL"},
            "final_concentration": {"value": "10", "unit": "uM"},
            "final_volume": {"value": "10", "unit": "mL"},
        },
        # V2 = 0 when solving for C2.
        {
            "stock_concentration": {"value": "10", "unit": "mM"},
            "stock_volume": {"value": "1", "unit": "mL"},
            "final_volume": {"value": "0", "unit": "mL"},
        },
        # C2 = 0 when solving for V2: an infinite dilution has no finite volume.
        {
            "stock_concentration": {"value": "10", "unit": "mM"},
            "stock_volume": {"value": "1", "unit": "mL"},
            "final_concentration": {"value": "0", "unit": "mM"},
        },
    ],
)
def test_zero_divisors_are_refused(payload: dict[str, object]) -> None:
    with pytest.raises(CalculatorInputError):
        solve_dilution(request(**payload))


def test_zero_working_concentration_is_refused_as_a_blank() -> None:
    """0 µM is a blank well, not a dilution: its fold dilution is undefined, not zero."""
    with pytest.raises(CalculatorInputError, match="blank"):
        solve_dilution(
            request(
                stock_concentration={"value": "10", "unit": "mM"},
                stock_volume={"value": "1", "unit": "mL"},
                final_concentration={"value": "0", "unit": "mM"},
            )
        )


@pytest.mark.parametrize(
    "payload",
    [
        # Nothing unset.
        {
            "stock_concentration": {"value": "10", "unit": "mM"},
            "stock_volume": {"value": "1", "unit": "mL"},
            "final_concentration": {"value": "10", "unit": "uM"},
            "final_volume": {"value": "10", "unit": "mL"},
        },
        # Two terms unset.
        {
            "stock_concentration": {"value": "10", "unit": "mM"},
            "final_concentration": {"value": "10", "unit": "uM"},
        },
    ],
)
def test_exactly_one_unknown_is_required(payload: dict[str, object]) -> None:
    with pytest.raises(CalculatorInputError):
        solve_dilution(request(**payload))


def test_concentrating_is_refused() -> None:
    with pytest.raises(CalculatorInputError, match="cannot concentrate"):
        solve_dilution(
            request(
                stock_concentration={"value": "1", "unit": "uM"},
                final_concentration={"value": "1", "unit": "mM"},
                final_volume={"value": "10", "unit": "mL"},
            )
        )


def test_stock_volume_above_final_volume_is_refused() -> None:
    """Solving C2 from a stock volume larger than the final volume can only concentrate."""
    with pytest.raises(CalculatorInputError, match="cannot concentrate"):
        solve_dilution(
            request(
                stock_concentration={"value": "10", "unit": "mM"},
                stock_volume={"value": "10", "unit": "mL"},
                final_volume={"value": "1", "unit": "mL"},
            )
        )


def test_impractical_transfers_are_noted_not_refused() -> None:
    result = solve_dilution(
        request(
            stock_concentration={"value": "10", "unit": "mM"},
            final_concentration={"value": "1", "unit": "nM"},
            final_volume={"value": "1", "unit": "mL"},
        )
    )

    assert result.stock_volume.to(VolumeUnit.MICROLITRE).value == Decimal("0.0001")
    assert any("intermediate dilution" in note for note in result.notes)
    assert any("pipettes" in note for note in result.notes)


def test_results_are_rounded_to_six_significant_figures() -> None:
    result = solve_dilution(
        request(
            stock_concentration={"value": "7", "unit": "mM"},
            final_concentration={"value": "3", "unit": "uM"},
            final_volume={"value": "10", "unit": "mL"},
        )
    )

    # 3 uM / 7 mM of 10 mL = 0.00428571428... mL
    assert result.stock_volume.value == Decimal("0.00428571")
    assert result.fold_dilution == Decimal("2333.33")
