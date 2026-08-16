from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import LlmUser, ThrottledUser
from app.services.protocols import (
    ChecklistItem,
    DrafterError,
    DrafterUnavailableError,
    DraftRequest,
    ProtocolDraft,
    ProtocolReview,
    ProtocolReviewRequest,
    ProtocolService,
)
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


def get_protocol_service() -> ProtocolService:
    return ProtocolService.from_settings()


Service = Annotated[ProtocolService, Depends(get_protocol_service)]


# Drafting spends money at Anthropic, so it rides the LLM limiter and the daily call budget
# rather than the plain API limit.
@router.post("/draft", response_model=ProtocolDraft)
async def draft_protocol(request: DraftRequest, service: Service, _user: LlmUser) -> ProtocolDraft:
    """
    Draft a structured protocol from a natural-language experimental goal.

    The response is model output: it carries `origin="agent_drafted"` and the review
    disclaimer, and nothing in this path validates that the science is correct.
    """
    try:
        return await service.draft(request)
    except DrafterUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except DrafterError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    finally:
        await service.aclose()


@router.post("/controls/review", response_model=ProtocolReview)
async def review_controls(
    request: ProtocolReviewRequest, service: Service, _user: LlmUser
) -> ProtocolReview:
    """
    List the standard controls this protocol appears to be missing, plus the reagent checklist.

    The findings are an agent-drafted opinion scoped by `scope_note`: a protocol with no missing
    control here has not been validated, it has only had its controls looked at.
    """
    try:
        return await service.review_controls(request.protocol)
    except DrafterUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except DrafterError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    finally:
        await service.aclose()


# Extraction only — no model call — so this rides the plain API limit and works without a key.
@router.post("/checklist", response_model=list[ChecklistItem])
def reagent_checklist(
    request: ProtocolReviewRequest, service: Service, _user: ThrottledUser
) -> list[ChecklistItem]:
    """Storage temperatures, spin speeds, handling and timing flags quoted from the protocol."""
    return service.reagent_checklist(request.protocol)


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
