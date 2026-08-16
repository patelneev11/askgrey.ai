from __future__ import annotations

from decimal import Decimal, DivisionByZero, InvalidOperation

from .errors import CalculatorError, CalculatorInputError, UnitMismatchError
from .models import (
    CalculationEntry,
    CalculationOutcome,
    CalculationResult,
    DilutionRequest,
    DilutionResult,
    DilutionVariable,
    MasterMixLine,
    MasterMixRequest,
    MasterMixResult,
    RecalculationRequest,
    RecalculationResponse,
    SolutionMassRequest,
    SolutionMassResult,
    StockRatioRequest,
    StockRatioResult,
)
from .units import (
    Concentration,
    ConcentrationUnit,
    MassUnit,
    UnitFamily,
    VolumeUnit,
    concentration_from_canonical,
    mass_from_grams,
    significant,
    volume_from_litres,
)

HUNDRED = Decimal(100)
LITRES_PER_ML = Decimal("1E-3")

# A dilution whose stock volume is this fraction of the final volume or less is hard to pipette
# accurately in one step; the result says so rather than silently prescribing 0.4 µL.
SMALL_TRANSFER_FRACTION = Decimal("0.005")
# Below this volume, a single-channel pipette is out of its accurate range on most benches.
MIN_PRACTICAL_MICROLITRES = Decimal("1")


def _require_same_family(first: Concentration, second: Concentration) -> None:
    if first.family is not second.family:
        raise UnitMismatchError(
            f"{first.unit.value} and {second.unit.value} are different kinds of concentration "
            f"({first.family.value} vs {second.family.value}); C1V1 = C2V2 needs both "
            "concentrations in the same family"
        )


def _divide(numerator: Decimal, denominator: Decimal, *, what: str) -> Decimal:
    if denominator == 0:
        raise CalculatorInputError(f"{what} cannot be zero")
    try:
        return numerator / denominator
    except (DivisionByZero, InvalidOperation) as exc:  # pragma: no cover - guarded above
        raise CalculatorInputError(f"{what} produced an undefined result") from exc


def solve_dilution(request: DilutionRequest) -> DilutionResult:
    """
    Solve C1V1 = C2V2 for whichever single term was left unset.

    The arithmetic runs in each family's canonical unit (M or mg/mL for concentration, litres for
    volume) and the answer is converted back into the unit its counterpart was given in, so a
    stock in mM and a working concentration in µM produce a volume in the unit the user is
    already thinking in rather than litres.
    """
    known = {
        DilutionVariable.STOCK_CONCENTRATION: request.stock_concentration,
        DilutionVariable.STOCK_VOLUME: request.stock_volume,
        DilutionVariable.FINAL_CONCENTRATION: request.final_concentration,
        DilutionVariable.FINAL_VOLUME: request.final_volume,
    }
    missing = [variable for variable, value in known.items() if value is None]
    if len(missing) != 1:
        unset = ", ".join(variable.value for variable in missing) or "none"
        raise CalculatorInputError(
            f"exactly one of C1, V1, C2, V2 must be left unset; {len(missing)} were unset ({unset})"
        )
    unknown = missing[0]

    c1, v1, c2, v2 = (
        request.stock_concentration,
        request.stock_volume,
        request.final_concentration,
        request.final_volume,
    )
    notes: list[str] = []

    for concentration in (c1, c2):
        if concentration is not None and concentration.canonical() == 0:
            # A zero concentration makes the fold dilution undefined. A blank or vehicle well is
            # a real thing, but it is not a dilution of anything, and answering "0-fold" or
            # "0 mL of stock" would be a number the bench could act on.
            raise CalculatorInputError(
                "a concentration of 0 describes a blank rather than a dilution; both the stock "
                "and the working concentration must be above zero"
            )

    if unknown is DilutionVariable.STOCK_VOLUME:
        assert c1 is not None and c2 is not None and v2 is not None
        _require_same_family(c1, c2)
        litres = _divide(c2.canonical() * v2.canonical(), c1.canonical(), what="C1")
        v1 = volume_from_litres(litres, v2.unit)
        basis = f"V1 = C2 x V2 / C1 = {c2.label} x {v2.label} / {c1.label}"
    elif unknown is DilutionVariable.FINAL_VOLUME:
        assert c1 is not None and v1 is not None and c2 is not None
        _require_same_family(c1, c2)
        litres = _divide(c1.canonical() * v1.canonical(), c2.canonical(), what="C2")
        v2 = volume_from_litres(litres, v1.unit)
        basis = f"V2 = C1 x V1 / C2 = {c1.label} x {v1.label} / {c2.label}"
    elif unknown is DilutionVariable.STOCK_CONCENTRATION:
        assert v1 is not None and c2 is not None and v2 is not None
        canonical = _divide(c2.canonical() * v2.canonical(), v1.canonical(), what="V1")
        c1 = concentration_from_canonical(canonical, c2.unit)
        basis = f"C1 = C2 x V2 / V1 = {c2.label} x {v2.label} / {v1.label}"
    else:
        assert c1 is not None and v1 is not None and v2 is not None
        canonical = _divide(c1.canonical() * v1.canonical(), v2.canonical(), what="V2")
        c2 = concentration_from_canonical(canonical, c1.unit)
        basis = f"C2 = C1 x V1 / V2 = {c1.label} x {v1.label} / {v2.label}"

    assert c1 is not None and v1 is not None and c2 is not None and v2 is not None
    _require_same_family(c1, c2)

    if c2.canonical() > c1.canonical():
        raise CalculatorInputError(
            f"the working concentration ({c2.label}) is higher than the stock ({c1.label}); "
            "diluting cannot concentrate a solution"
        )
    if v1.canonical() > v2.canonical():  # defensive: C1V1 = C2V2 with C1 >= C2 implies V1 <= V2
        raise CalculatorInputError(
            f"the stock volume ({v1.label}) exceeds the final volume ({v2.label}), so there is "
            "no room for diluent"
        )

    diluent = volume_from_litres(v2.canonical() - v1.canonical(), v2.unit)
    fold = _divide(c1.canonical(), c2.canonical(), what="the working concentration")

    if v2.canonical() > 0 and v1.canonical() / v2.canonical() <= SMALL_TRANSFER_FRACTION:
        notes.append(
            f"{v1.rounded().label} of stock into {v2.rounded().label} is a "
            f"{significant(fold, 3)}-fold single-step dilution; consider an intermediate dilution "
            "for pipetting accuracy."
        )
    microlitres = v1.to(VolumeUnit.MICROLITRE).value
    if 0 < microlitres < MIN_PRACTICAL_MICROLITRES:
        notes.append(
            f"the stock transfer is {v1.to(VolumeUnit.MICROLITRE).rounded().label}, below the "
            "accurate range of most single-channel pipettes."
        )

    return DilutionResult(
        solved_for=unknown,
        stock_concentration=c1.rounded(),
        stock_volume=v1.rounded(),
        final_concentration=c2.rounded(),
        final_volume=v2.rounded(),
        diluent_volume=diluent.rounded(),
        fold_dilution=significant(fold),
        basis=basis,
        label=request.label,
        notes=notes,
    )


def scale_master_mix(request: MasterMixRequest) -> MasterMixResult:
    """
    Scale a per-reaction recipe to a plate.

    Reactions are multiplied by the replicate count and then by the dead-volume overage, and
    each component's total is `per-reaction volume x effective reactions` — computed from the
    unrounded factor and rounded once, so the printed component volumes sum to the printed
    total.
    """
    reactions = Decimal(request.reactions) * Decimal(request.replicates)
    factor = reactions * (HUNDRED + request.overage_percent) / HUNDRED

    lines: list[MasterMixLine] = []
    per_reaction_litres = Decimal(0)
    total_litres = Decimal(0)
    unit = request.components[0].per_reaction_volume.unit
    for component in request.components:
        per_reaction = component.per_reaction_volume
        total = volume_from_litres(per_reaction.canonical() * factor, unit)
        per_reaction_litres += per_reaction.canonical()
        total_litres += total.canonical()
        lines.append(
            MasterMixLine(
                name=component.name,
                per_reaction_volume=per_reaction.rounded(),
                total_volume=total.rounded(),
                basis=(
                    f"{per_reaction.label} x {significant(factor)} reactions "
                    f"({request.reactions} x {request.replicates} replicate(s) "
                    f"+ {request.overage_percent.normalize():f}% overage)"
                ),
                note=component.note,
            )
        )

    notes = [
        f"Volumes include a {request.overage_percent.normalize():f}% overage for dead volume, so "
        f"the mix makes {significant(factor)} reactions' worth for "
        f"{request.reactions * request.replicates} wells."
    ]
    return MasterMixResult(
        reactions=request.reactions,
        replicates=request.replicates,
        overage_percent=request.overage_percent,
        effective_reactions=significant(factor),
        lines=lines,
        per_reaction_volume=volume_from_litres(per_reaction_litres, unit).rounded(),
        total_volume=volume_from_litres(total_litres, unit).rounded(),
        label=request.label,
        notes=notes,
    )


def stock_ratio(request: StockRatioRequest) -> StockRatioResult:
    """
    Stock and diluent volumes for a working solution, plus the parts ratio.

    This is `solve_dilution` for the common bench case where the final volume and both
    concentrations are known, with the answer additionally expressed as "1 part stock in N",
    which is how a fold stock (e.g. 100x) is usually written on a bottle.
    """
    dilution = solve_dilution(
        DilutionRequest(
            stock_concentration=request.stock_concentration,
            final_concentration=request.final_concentration,
            final_volume=request.final_volume,
            label=request.label,
        )
    )
    fold = dilution.fold_dilution
    return StockRatioResult(
        stock_volume=dilution.stock_volume,
        diluent_volume=dilution.diluent_volume,
        final_volume=dilution.final_volume,
        fold_dilution=fold,
        ratio_label=f"1:{significant(fold, 4):f} (1 part stock in {significant(fold, 4):f} total)",
        basis=dilution.basis,
        label=request.label,
        notes=dilution.notes,
    )


def solution_mass(request: SolutionMassRequest) -> SolutionMassResult:
    """
    Mass of solid for a molar solution: m = C x V x MW.

    Molar units only. A mg/mL stock needs no molecular weight, and a fold or % (w/v) stock has
    no molar interpretation, so both are refused instead of being coerced.
    """
    if request.concentration.family is not UnitFamily.MOLAR:
        raise UnitMismatchError(
            f"a molar concentration is required to weigh out a solid, not "
            f"{request.concentration.unit.value}"
        )
    moles = request.concentration.canonical() * request.volume.canonical()
    grams = moles * request.molecular_weight_g_per_mol
    mass = mass_from_grams(grams, _mass_unit_for(grams))
    return SolutionMassResult(
        mass=mass.rounded(),
        concentration=request.concentration,
        volume=request.volume,
        molecular_weight_g_per_mol=request.molecular_weight_g_per_mol,
        basis=(
            f"m = C x V x MW = {request.concentration.to(ConcentrationUnit.MOLAR).rounded().label}"
            f" x {request.volume.rounded().label} x "
            f"{significant(request.molecular_weight_g_per_mol):f} g/mol"
        ),
        label=request.label,
    )


def _mass_unit_for(grams: Decimal) -> MassUnit:
    """Pick the unit that puts the answer in a readable range rather than 0.000042 g."""
    if grams >= Decimal("1"):
        return MassUnit.GRAM
    if grams >= Decimal("1E-3"):
        return MassUnit.MILLIGRAM
    if grams >= Decimal("1E-6"):
        return MassUnit.MICROGRAM
    return MassUnit.NANOGRAM


def _run_entry(entry: CalculationEntry) -> CalculationResult:
    requests = [
        entry.dilution,
        entry.master_mix,
        entry.stock_ratio,
        entry.solution_mass,
    ]
    provided = [request for request in requests if request is not None]
    if len(provided) != 1:
        raise CalculatorInputError(
            f"entry {entry.id!r} must carry exactly one calculation, not {len(provided)}"
        )
    request = provided[0]
    if isinstance(request, DilutionRequest):
        return solve_dilution(request)
    if isinstance(request, MasterMixRequest):
        return scale_master_mix(request)
    if isinstance(request, StockRatioRequest):
        return stock_ratio(request)
    return solution_mass(request)


def recalculate(request: RecalculationRequest) -> RecalculationResponse:
    """
    Recompute a whole protocol's inline fields, applying a new batch scale where one is given.

    `batch_scale` and `overage_percent` are applied to every master mix in the set, which is
    what makes the well-count control on the frontend a single round trip. Per-entry failures
    are returned as errors on that entry so the rest of the protocol still recalculates.
    """
    outcomes: list[CalculationOutcome] = []
    for entry in request.entries:
        scaled = entry
        if entry.master_mix is not None and (
            request.batch_scale is not None or request.overage_percent is not None
        ):
            overrides: dict[str, object] = {}
            if request.batch_scale is not None:
                overrides["reactions"] = request.batch_scale
            if request.overage_percent is not None:
                overrides["overage_percent"] = request.overage_percent
            scaled = entry.model_copy(
                update={"master_mix": entry.master_mix.model_copy(update=overrides)}
            )
        try:
            result = _run_entry(scaled)
        except CalculatorError as exc:
            outcomes.append(CalculationOutcome(id=entry.id, step_id=entry.step_id, error=str(exc)))
            continue
        outcomes.append(
            CalculationOutcome(id=entry.id, step_id=entry.step_id, kind=result.kind, result=result)
        )
    return RecalculationResponse(
        outcomes=outcomes,
        batch_scale=request.batch_scale,
        overage_percent=request.overage_percent,
    )
