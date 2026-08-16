"""
Deterministic bench arithmetic for protocol steps.

Nothing in this package consults a model. Every number it returns comes from an explicit
equation over `Decimal` inputs, which is why a calculator field is the one thing on a drafted
protocol that can honestly be labelled as calculated rather than drafted.
"""

from .calculations import (
    recalculate,
    scale_master_mix,
    solution_mass,
    solve_dilution,
    stock_ratio,
)
from .errors import CalculatorError, CalculatorInputError, UnitError, UnitMismatchError
from .models import (
    CalculationEntry,
    CalculationKind,
    CalculationOutcome,
    CalculationResult,
    DilutionRequest,
    DilutionResult,
    DilutionVariable,
    MasterMixComponent,
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
    SIGNIFICANT_FIGURES,
    Concentration,
    ConcentrationUnit,
    Mass,
    MassUnit,
    UnitFamily,
    Volume,
    VolumeUnit,
    concentration_family,
    parse_concentration_unit,
    parse_mass_unit,
    parse_volume_unit,
    significant,
)

__all__ = [
    "SIGNIFICANT_FIGURES",
    "CalculationEntry",
    "CalculationKind",
    "CalculationOutcome",
    "CalculationResult",
    "CalculatorError",
    "CalculatorInputError",
    "Concentration",
    "ConcentrationUnit",
    "DilutionRequest",
    "DilutionResult",
    "DilutionVariable",
    "Mass",
    "MassUnit",
    "MasterMixComponent",
    "MasterMixLine",
    "MasterMixRequest",
    "MasterMixResult",
    "RecalculationRequest",
    "RecalculationResponse",
    "SolutionMassRequest",
    "SolutionMassResult",
    "StockRatioRequest",
    "StockRatioResult",
    "UnitError",
    "UnitFamily",
    "UnitMismatchError",
    "Volume",
    "VolumeUnit",
    "concentration_family",
    "parse_concentration_unit",
    "parse_mass_unit",
    "parse_volume_unit",
    "recalculate",
    "scale_master_mix",
    "significant",
    "solution_mass",
    "solve_dilution",
    "stock_ratio",
]
