from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.protocols.calculator import (
    Concentration,
    ConcentrationUnit,
    Mass,
    MassUnit,
    UnitError,
    UnitFamily,
    UnitMismatchError,
    Volume,
    VolumeUnit,
    parse_concentration_unit,
    parse_volume_unit,
    significant,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("mM", ConcentrationUnit.MILLIMOLAR),
        ("uM", ConcentrationUnit.MICROMOLAR),
        # µ (U+00B5) and μ (U+03BC) look identical and both arrive from real keyboards.
        ("µM", ConcentrationUnit.MICROMOLAR),
        ("\u03bcM", ConcentrationUnit.MICROMOLAR),
        ("um", ConcentrationUnit.MICROMOLAR),
        ("  nM ", ConcentrationUnit.NANOMOLAR),
        ("M", ConcentrationUnit.MOLAR),
        ("molar", ConcentrationUnit.MOLAR),
        ("mg/ml", ConcentrationUnit.MG_PER_ML),
        ("µg/mL", ConcentrationUnit.UG_PER_ML),
        ("x", ConcentrationUnit.FOLD),
        ("%", ConcentrationUnit.PERCENT_WEIGHT_VOLUME),
    ],
)
def test_concentration_unit_aliases(raw: str, expected: ConcentrationUnit) -> None:
    assert parse_concentration_unit(raw) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("ul", VolumeUnit.MICROLITRE), ("µL", VolumeUnit.MICROLITRE), ("ML", VolumeUnit.MILLILITRE)],
)
def test_volume_unit_aliases(raw: str, expected: VolumeUnit) -> None:
    assert parse_volume_unit(raw) is expected


@pytest.mark.parametrize("raw", ["", "   ", "molarity", "mL/mg", "gallons"])
def test_unparseable_units_raise(raw: str) -> None:
    with pytest.raises(UnitError):
        parse_concentration_unit(raw)


def test_millimolar_to_micromolar_is_exact() -> None:
    # 1 mM is exactly 1000 µM; a float pipeline would land on 999.9999999999999.
    converted = Concentration(value=Decimal("1"), unit=ConcentrationUnit.MILLIMOLAR).to(
        ConcentrationUnit.MICROMOLAR
    )

    assert converted.value == Decimal("1000")
    assert converted.unit is ConcentrationUnit.MICROMOLAR


@pytest.mark.parametrize(
    ("value", "unit", "target", "expected"),
    [
        ("10", "mM", "uM", "10000"),
        ("0.05", "M", "mM", "50"),
        ("2500", "nM", "uM", "2.5"),
        ("1", "pM", "M", "1E-12"),
        ("1", "mg/mL", "ug/mL", "1000"),
    ],
)
def test_concentration_conversions(value: str, unit: str, target: str, expected: str) -> None:
    converted = Concentration(value=Decimal(value), unit=unit).to(parse_concentration_unit(target))

    assert converted.value == Decimal(expected)


@pytest.mark.parametrize(
    ("value", "unit", "target", "expected"),
    [
        ("1", "mL", "uL", "1000"),
        ("500", "uL", "mL", "0.5"),
        ("1", "L", "nL", "1E9"),
        ("250", "nL", "uL", "0.25"),
    ],
)
def test_volume_conversions(value: str, unit: str, target: str, expected: str) -> None:
    converted = Volume(value=Decimal(value), unit=unit).to(parse_volume_unit(target))

    assert converted.value == Decimal(expected)


def test_mass_conversion_round_trips() -> None:
    mass = Mass(value=Decimal("2.5"), unit=MassUnit.MILLIGRAM)

    assert mass.to(MassUnit.MICROGRAM).value == Decimal("2500")
    assert mass.to(MassUnit.MICROGRAM).to(MassUnit.MILLIGRAM).value == Decimal("2.5")


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("mM", "mg/mL"),
        ("mg/mL", "uM"),
        ("X", "mM"),
        ("% (w/v)", "mg/mL"),
    ],
)
def test_crossing_unit_families_raises_rather_than_guessing(source: str, target: str) -> None:
    concentration = Concentration(value=Decimal("1"), unit=source)

    with pytest.raises(UnitMismatchError):
        concentration.to(parse_concentration_unit(target))


def test_families_are_reported() -> None:
    assert Concentration(value=Decimal(1), unit="nM").family is UnitFamily.MOLAR
    assert Concentration(value=Decimal(1), unit="ug/mL").family is UnitFamily.MASS_PER_VOLUME
    assert Concentration(value=Decimal(1), unit="X").family is UnitFamily.FOLD


def test_zero_is_a_valid_quantity_but_negatives_are_not() -> None:
    assert Concentration(value=Decimal(0), unit="mM").canonical() == 0
    with pytest.raises(ValueError):
        Volume(value=Decimal("-1"), unit="mL")


@pytest.mark.parametrize(
    ("value", "figures", "expected"),
    [
        ("1.23456789", 6, "1.23457"),
        ("0.000123456789", 6, "0.000123457"),
        # Half-up, not banker's rounding: 0.5 always goes away from zero.
        ("1.234565", 6, "1.23457"),
        ("1.234575", 6, "1.23458"),
        ("2.5", 1, "3"),
        ("1250", 2, "1300"),
        ("0", 6, "0"),
        # Trailing zeros are dropped, and the result never comes back in E notation.
        ("1000", 6, "1000"),
        ("0.1000", 6, "0.1"),
    ],
)
def test_significant_rounds_half_up_to_significant_figures(
    value: str, figures: int, expected: str
) -> None:
    assert significant(Decimal(value), figures) == Decimal(expected)
    assert "E" not in f"{significant(Decimal(value), figures):f}"


def test_labels_render_the_unit() -> None:
    assert Volume(value=Decimal("0.01"), unit="mL").label == "0.01 mL"
    assert Concentration(value=Decimal("100"), unit="X").label == "100X"
    assert Concentration(value=Decimal("10"), unit="uM").label == "10 uM"
