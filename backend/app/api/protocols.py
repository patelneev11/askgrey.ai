from fastapi import APIRouter, HTTPException, status

from app.api.deps import ThrottledUser
from app.services.protocols.calculator import (
    CalculatorError,
    CalculatorInputError,
    DilutionRequest,
    DilutionResult,
    MasterMixRequest,
    MasterMixResult,
    RecalculationRequest,
    RecalculationResponse,
    SolutionMassRequest,
    SolutionMassResult,
    StockRatioRequest,
    StockRatioResult,
    UnitError,
    UnitMismatchError,
    recalculate,
    scale_master_mix,
    solution_mass,
    solve_dilution,
    stock_ratio,
)

router = APIRouter(prefix="/protocols", tags=["protocols"])


def _handle(exc: CalculatorError) -> HTTPException:
    """A bad unit or an unsolvable set of terms is the caller's input, not a server fault."""
    if isinstance(exc, UnitError | UnitMismatchError | CalculatorInputError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


# The calculator endpoints are pure arithmetic — no model call, no outbound request — so they
# ride the standard per-account API limit rather than the LLM limit and daily budget.
@router.post("/calculator/dilution", response_model=DilutionResult)
def dilution(request: DilutionRequest, _user: ThrottledUser) -> DilutionResult:
    """Solve C1V1 = C2V2 for the single term left unset."""
    try:
        return solve_dilution(request)
    except CalculatorError as exc:
        raise _handle(exc) from exc


@router.post("/calculator/master-mix", response_model=MasterMixResult)
def master_mix(request: MasterMixRequest, _user: ThrottledUser) -> MasterMixResult:
    """Scale a per-reaction recipe by well/sample count, including the dead-volume overage."""
    try:
        return scale_master_mix(request)
    except CalculatorError as exc:
        raise _handle(exc) from exc


@router.post("/calculator/stock-ratio", response_model=StockRatioResult)
def stock_ratio_endpoint(request: StockRatioRequest, _user: ThrottledUser) -> StockRatioResult:
    """Stock and diluent volumes for a working solution, plus the parts ratio."""
    try:
        return stock_ratio(request)
    except CalculatorError as exc:
        raise _handle(exc) from exc


@router.post("/calculator/solution-mass", response_model=SolutionMassResult)
def solution_mass_endpoint(
    request: SolutionMassRequest, _user: ThrottledUser
) -> SolutionMassResult:
    """Mass of solid needed for a molar solution: m = C x V x MW."""
    try:
        return solution_mass(request)
    except CalculatorError as exc:
        raise _handle(exc) from exc


@router.post("/calculator/recalculate", response_model=RecalculationResponse)
def recalculate_endpoint(
    request: RecalculationRequest, _user: ThrottledUser
) -> RecalculationResponse:
    """
    Recompute every inline field of a protocol in one call, applying a new batch scale.

    Individual fields that cannot be solved come back with an `error` on their entry, which is
    what lets the frontend recalculate live while a user is still editing.
    """
    return recalculate(request)
