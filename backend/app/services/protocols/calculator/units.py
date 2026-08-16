from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from .errors import UnitError, UnitMismatchError

# Results are rounded to this many significant figures, once, at the point a quantity is
# built for display. Fixed decimal places cannot serve a calculator that spans litres and
# nanolitres in the same protocol: 0.0005 µL would round to 0.00.
SIGNIFICANT_FIGURES = 6


class UnitFamily(str, Enum):
    """
    Which quantities may be converted into one another.

    Conversions happen inside a family only. mg/mL to M needs a molecular weight, and a fold
    stock (100x) or a % (w/v) has no defined molar equivalent at all, so those crossings raise
    instead of guessing.
    """

    MOLAR = "molar"
    MASS_PER_VOLUME = "mass_per_volume"
    FOLD = "fold"
    PERCENT = "percent"
    VOLUME = "volume"
    MASS = "mass"


class ConcentrationUnit(str, Enum):
    # `str.__str__` keeps `f"{unit}"` rendering as "mM" rather than "ConcentrationUnit.MILLIMOLAR",
    # which is what a str-valued Enum does on Python 3.10.
    __str__ = str.__str__

    MOLAR = "M"
    MILLIMOLAR = "mM"
    MICROMOLAR = "uM"
    NANOMOLAR = "nM"
    PICOMOLAR = "pM"
    MG_PER_ML = "mg/mL"
    UG_PER_ML = "ug/mL"
    NG_PER_ML = "ng/mL"
    FOLD = "X"
    PERCENT_WEIGHT_VOLUME = "% (w/v)"


class VolumeUnit(str, Enum):
    __str__ = str.__str__

    LITRE = "L"
    MILLILITRE = "mL"
    MICROLITRE = "uL"
    NANOLITRE = "nL"


class MassUnit(str, Enum):
    __str__ = str.__str__

    GRAM = "g"
    MILLIGRAM = "mg"
    MICROGRAM = "ug"
    NANOGRAM = "ng"


# Factor to the family's canonical unit (M, mg/mL, X, %, L, g). Written as exact Decimals so a
# µL -> L conversion never picks up binary float error.
_CONCENTRATION_FACTORS: dict[ConcentrationUnit, tuple[UnitFamily, Decimal]] = {
    ConcentrationUnit.MOLAR: (UnitFamily.MOLAR, Decimal(1)),
    ConcentrationUnit.MILLIMOLAR: (UnitFamily.MOLAR, Decimal("1E-3")),
    ConcentrationUnit.MICROMOLAR: (UnitFamily.MOLAR, Decimal("1E-6")),
    ConcentrationUnit.NANOMOLAR: (UnitFamily.MOLAR, Decimal("1E-9")),
    ConcentrationUnit.PICOMOLAR: (UnitFamily.MOLAR, Decimal("1E-12")),
    ConcentrationUnit.MG_PER_ML: (UnitFamily.MASS_PER_VOLUME, Decimal(1)),
    ConcentrationUnit.UG_PER_ML: (UnitFamily.MASS_PER_VOLUME, Decimal("1E-3")),
    ConcentrationUnit.NG_PER_ML: (UnitFamily.MASS_PER_VOLUME, Decimal("1E-6")),
    ConcentrationUnit.FOLD: (UnitFamily.FOLD, Decimal(1)),
    ConcentrationUnit.PERCENT_WEIGHT_VOLUME: (UnitFamily.PERCENT, Decimal(1)),
}

_VOLUME_FACTORS: dict[VolumeUnit, Decimal] = {
    VolumeUnit.LITRE: Decimal(1),
    VolumeUnit.MILLILITRE: Decimal("1E-3"),
    VolumeUnit.MICROLITRE: Decimal("1E-6"),
    VolumeUnit.NANOLITRE: Decimal("1E-9"),
}

_MASS_FACTORS: dict[MassUnit, Decimal] = {
    MassUnit.GRAM: Decimal(1),
    MassUnit.MILLIGRAM: Decimal("1E-3"),
    MassUnit.MICROGRAM: Decimal("1E-6"),
    MassUnit.NANOGRAM: Decimal("1E-9"),
}

# What researchers actually type. µ (U+00B5) and μ (U+03BC) are different characters and both
# reach the API from real keyboards and pasted SOPs.
_ALIASES: dict[str, str] = {
    "µm": "uM",
    "μm": "uM",
    "um": "uM",
    "m": "M",
    "mm": "mM",
    "nm": "nM",
    "pm": "pM",
    "molar": "M",
    "mg/ml": "mg/mL",
    "µg/ml": "ug/mL",
    "μg/ml": "ug/mL",
    "ug/ml": "ug/mL",
    "ng/ml": "ng/mL",
    "x": "X",
    "fold": "X",
    "%": "% (w/v)",
    "% (w/v)": "% (w/v)",
    "%(w/v)": "% (w/v)",
    "% w/v": "% (w/v)",
    "l": "L",
    "ml": "mL",
    "µl": "uL",
    "μl": "uL",
    "ul": "uL",
    "nl": "nL",
    "g": "g",
    "mg": "mg",
    "µg": "ug",
    "μg": "ug",
    "ug": "ug",
    "ng": "ng",
}


def _canonical_token(raw: str) -> str:
    text = " ".join(str(raw).split())
    if not text:
        raise UnitError("a unit is required")
    return _ALIASES.get(text.lower(), text)


def parse_concentration_unit(raw: str) -> ConcentrationUnit:
    if isinstance(raw, ConcentrationUnit):
        return raw
    try:
        return ConcentrationUnit(_canonical_token(raw))
    except ValueError as exc:
        raise UnitError(f"{raw!r} is not a supported concentration unit") from exc


def parse_volume_unit(raw: str) -> VolumeUnit:
    if isinstance(raw, VolumeUnit):
        return raw
    try:
        return VolumeUnit(_canonical_token(raw))
    except ValueError as exc:
        raise UnitError(f"{raw!r} is not a supported volume unit") from exc


def parse_mass_unit(raw: str) -> MassUnit:
    if isinstance(raw, MassUnit):
        return raw
    try:
        return MassUnit(_canonical_token(raw))
    except ValueError as exc:
        raise UnitError(f"{raw!r} is not a supported mass unit") from exc


def concentration_family(unit: ConcentrationUnit) -> UnitFamily:
    return _CONCENTRATION_FACTORS[unit][0]


def significant(value: Decimal, figures: int = SIGNIFICANT_FIGURES) -> Decimal:
    """
    Round to `figures` significant figures, half up, and drop trailing zeros.

    Applied once per emitted quantity rather than between steps, so the reported number is a
    rounding of the exact answer instead of an accumulation of intermediate roundings.
    """
    if value == 0:
        return Decimal(0)
    exponent = value.adjusted() - figures + 1
    rounded = value.quantize(Decimal(1).scaleb(exponent), rounding=ROUND_HALF_UP)
    normalized = rounded.normalize()
    # normalize() renders 1000 as 1E+3; expanding it keeps API output readable.
    tail = normalized.as_tuple().exponent
    return normalized.quantize(Decimal(1)) if isinstance(tail, int) and tail > 0 else normalized


def _format(value: Decimal, unit: str) -> str:
    figure = f"{significant(value):f}"
    return f"{figure} {unit}" if unit not in {"X", "% (w/v)"} else f"{figure}{unit}"


class Concentration(BaseModel):
    """A concentration with its unit attached. Immutable: conversions return a new instance."""

    model_config = {"frozen": True}

    value: Decimal = Field(ge=0)
    unit: ConcentrationUnit

    @field_validator("unit", mode="before")
    @classmethod
    def _coerce_unit(cls, raw: object) -> object:
        return parse_concentration_unit(raw) if isinstance(raw, str) else raw

    @property
    def family(self) -> UnitFamily:
        return concentration_family(self.unit)

    def canonical(self) -> Decimal:
        """Value in the family's canonical unit (M, mg/mL, X or %). Exact, never rounded."""
        return self.value * _CONCENTRATION_FACTORS[self.unit][1]

    def to(self, unit: ConcentrationUnit) -> Concentration:
        if concentration_family(unit) is not self.family:
            raise UnitMismatchError(
                f"cannot convert {self.unit.value} to {unit.value}: "
                f"{self.family.value} and {concentration_family(unit).value} are different "
                "kinds of concentration"
            )
        return Concentration(
            value=self.canonical() / _CONCENTRATION_FACTORS[unit][1],
            unit=unit,
        )

    def rounded(self) -> Concentration:
        return Concentration(value=significant(self.value), unit=self.unit)

    @property
    def label(self) -> str:
        return _format(self.value, self.unit.value)


class Volume(BaseModel):
    model_config = {"frozen": True}

    value: Decimal = Field(ge=0)
    unit: VolumeUnit

    @field_validator("unit", mode="before")
    @classmethod
    def _coerce_unit(cls, raw: object) -> object:
        return parse_volume_unit(raw) if isinstance(raw, str) else raw

    def canonical(self) -> Decimal:
        """Value in litres. Exact, never rounded."""
        return self.value * _VOLUME_FACTORS[self.unit]

    def to(self, unit: VolumeUnit) -> Volume:
        return Volume(value=self.canonical() / _VOLUME_FACTORS[unit], unit=unit)

    def rounded(self) -> Volume:
        return Volume(value=significant(self.value), unit=self.unit)

    @property
    def label(self) -> str:
        return _format(self.value, self.unit.value)


class Mass(BaseModel):
    model_config = {"frozen": True}

    value: Decimal = Field(ge=0)
    unit: MassUnit

    @field_validator("unit", mode="before")
    @classmethod
    def _coerce_unit(cls, raw: object) -> object:
        return parse_mass_unit(raw) if isinstance(raw, str) else raw

    def canonical(self) -> Decimal:
        """Value in grams. Exact, never rounded."""
        return self.value * _MASS_FACTORS[self.unit]

    def to(self, unit: MassUnit) -> Mass:
        return Mass(value=self.canonical() / _MASS_FACTORS[unit], unit=unit)

    def rounded(self) -> Mass:
        return Mass(value=significant(self.value), unit=self.unit)

    @property
    def label(self) -> str:
        return _format(self.value, self.unit.value)


def volume_from_litres(value: Decimal, unit: VolumeUnit) -> Volume:
    return Volume(value=value / _VOLUME_FACTORS[unit], unit=unit)


def concentration_from_canonical(value: Decimal, unit: ConcentrationUnit) -> Concentration:
    return Concentration(value=value / _CONCENTRATION_FACTORS[unit][1], unit=unit)


def mass_from_grams(value: Decimal, unit: MassUnit) -> Mass:
    return Mass(value=value / _MASS_FACTORS[unit], unit=unit)
