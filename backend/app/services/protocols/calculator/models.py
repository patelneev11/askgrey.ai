from __future__ import annotations

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

from .units import Concentration, Mass, Volume


class CalculationKind(str, Enum):
    """Which calculator produced a result. Rendered as the label on an inline field."""

    DILUTION = "dilution"
    MASTER_MIX = "master_mix"
    STOCK_RATIO = "stock_ratio"
    SOLUTION_MASS = "solution_mass"


class DilutionVariable(str, Enum):
    """The unknown in C1V1 = C2V2."""

    STOCK_CONCENTRATION = "c1"
    STOCK_VOLUME = "v1"
    FINAL_CONCENTRATION = "c2"
    FINAL_VOLUME = "v2"


class DilutionRequest(BaseModel):
    """
    Three of the four C1V1 = C2V2 terms; the fourth is left unset and solved for.

    Units are carried on every term rather than assumed, and the two concentrations must belong
    to the same unit family — see `UnitMismatchError`.
    """

    stock_concentration: Concentration | None = None
    stock_volume: Volume | None = None
    final_concentration: Concentration | None = None
    final_volume: Volume | None = None
    label: str = Field(default="", max_length=200)


class DilutionResult(BaseModel):
    """
    A solved dilution, with the arithmetic that produced it.

    `basis` is the substituted equation, so a reviewer can check the number without re-deriving
    it, and `diluent_volume` is what actually gets pipetted alongside the stock.
    """

    kind: CalculationKind = CalculationKind.DILUTION
    solved_for: DilutionVariable
    stock_concentration: Concentration
    stock_volume: Volume
    final_concentration: Concentration
    final_volume: Volume
    diluent_volume: Volume
    fold_dilution: Decimal
    basis: str
    label: str = ""
    notes: list[str] = Field(default_factory=list)


class MasterMixComponent(BaseModel):
    """One reagent in a master mix, at its per-reaction volume."""

    name: str = Field(min_length=1, max_length=200)
    per_reaction_volume: Volume
    note: str = Field(default="", max_length=200)


class MasterMixRequest(BaseModel):
    """
    Per-reaction recipe plus how many reactions to make.

    `overage_percent` is the dead-volume allowance; it defaults to 10%, which is the convention
    most plate protocols use, and is always reported in the result rather than folded silently
    into the volumes.
    """

    components: list[MasterMixComponent] = Field(min_length=1, max_length=40)
    reactions: int = Field(ge=1, le=100_000)
    overage_percent: Decimal = Field(default=Decimal(10), ge=0, le=100)
    replicates: int = Field(default=1, ge=1, le=100)
    label: str = Field(default="", max_length=200)


class MasterMixLine(BaseModel):
    name: str
    per_reaction_volume: Volume
    total_volume: Volume
    basis: str
    note: str = ""


class MasterMixResult(BaseModel):
    kind: CalculationKind = CalculationKind.MASTER_MIX
    reactions: int
    replicates: int
    overage_percent: Decimal
    effective_reactions: Decimal
    lines: list[MasterMixLine]
    per_reaction_volume: Volume
    total_volume: Volume
    label: str = ""
    notes: list[str] = Field(default_factory=list)


class StockRatioRequest(BaseModel):
    """How much stock and diluent make up a target volume at a target working concentration."""

    stock_concentration: Concentration
    final_concentration: Concentration
    final_volume: Volume
    label: str = Field(default="", max_length=200)


class StockRatioResult(BaseModel):
    kind: CalculationKind = CalculationKind.STOCK_RATIO
    stock_volume: Volume
    diluent_volume: Volume
    final_volume: Volume
    fold_dilution: Decimal
    ratio_label: str
    basis: str
    label: str = ""
    notes: list[str] = Field(default_factory=list)


class SolutionMassRequest(BaseModel):
    """Mass of solid needed to make a molar solution: m = C x V x MW."""

    concentration: Concentration
    volume: Volume
    molecular_weight_g_per_mol: Decimal = Field(gt=0, le=Decimal("1E7"))
    label: str = Field(default="", max_length=200)


class SolutionMassResult(BaseModel):
    kind: CalculationKind = CalculationKind.SOLUTION_MASS
    mass: Mass
    concentration: Concentration
    volume: Volume
    molecular_weight_g_per_mol: Decimal
    basis: str
    label: str = ""
    notes: list[str] = Field(default_factory=list)


CalculationResult = DilutionResult | MasterMixResult | StockRatioResult | SolutionMassResult


class CalculationEntry(BaseModel):
    """
    One calculation in a live recalculation batch, keyed by the field id it belongs to.

    Exactly one request is set. The frontend sends the whole set on every edit and re-renders
    from the response, so the ids are what let it put each answer back in the right step.
    """

    id: str = Field(min_length=1, max_length=100)
    step_id: str = Field(default="", max_length=100)
    dilution: DilutionRequest | None = None
    master_mix: MasterMixRequest | None = None
    stock_ratio: StockRatioRequest | None = None
    solution_mass: SolutionMassRequest | None = None


class CalculationOutcome(BaseModel):
    """
    The answer for one entry, or the reason there isn't one.

    A failed entry is reported as `error` rather than failing the batch: mid-edit a user has
    plenty of momentarily-empty fields, and losing the other steps' numbers to a 422 would make
    live recalculation unusable.
    """

    id: str
    step_id: str = ""
    kind: CalculationKind | None = None
    result: CalculationResult | None = None
    error: str | None = None


class RecalculationRequest(BaseModel):
    """
    A protocol's inline calculator fields, recalculated as one batch.

    `batch_scale` overrides the reaction count on every master mix in the set, which is what
    the frontend's "samples" / "wells" control changes.
    """

    entries: list[CalculationEntry] = Field(min_length=1, max_length=100)
    batch_scale: int | None = Field(default=None, ge=1, le=100_000)
    overage_percent: Decimal | None = Field(default=None, ge=0, le=100)


class RecalculationResponse(BaseModel):
    outcomes: list[CalculationOutcome]
    batch_scale: int | None = None
    overage_percent: Decimal | None = None
