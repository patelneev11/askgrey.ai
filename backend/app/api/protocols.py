from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession, LlmUser, ThrottledUser
from app.services.protocols import (
    ChecklistItem,
    DrafterError,
    DrafterUnavailableError,
    DraftRequest,
    ProtocolDraft,
    ProtocolHistoryResponse,
    ProtocolRequestError,
    ProtocolReview,
    ProtocolReviewRequest,
    ProtocolService,
    SavedProtocolResponse,
    SavedProtocolSummary,
    SaveProtocolRequest,
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
from app.services.protocols.eln_export import (
    ElnExportError,
    ElnExportPayload,
    ElnExportRequest,
    build_export,
)
from app.services.protocols.history import (
    create_protocol,
    get_history,
    get_protocol,
    get_version,
    list_protocols,
    update_protocol,
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


@router.post("", response_model=SavedProtocolResponse, status_code=status.HTTP_201_CREATED)
def save_protocol(
    request: SaveProtocolRequest, db: DbSession, user: ThrottledUser
) -> SavedProtocolResponse:
    """Save a protocol as version 1, owned by the calling account."""
    return create_protocol(
        db, user_id=str(user.id), protocol=request.protocol, change_summary=request.change_summary
    )


# Registered before the `/{protocol_id}` route so the empty path cannot be read as an id.
@router.get("", response_model=list[SavedProtocolSummary])
def list_saved_protocols(db: DbSession, user: ThrottledUser) -> list[SavedProtocolSummary]:
    """The caller's saved protocols, newest edit first, so a save survives a page reload."""
    return list_protocols(db, user_id=str(user.id))


@router.get("/{protocol_id}", response_model=SavedProtocolResponse)
def read_protocol(protocol_id: str, db: DbSession, user: ThrottledUser) -> SavedProtocolResponse:
    try:
        return get_protocol(db, protocol_id=protocol_id, user_id=str(user.id))
    except ProtocolRequestError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.put("/{protocol_id}", response_model=SavedProtocolResponse)
def edit_protocol(
    protocol_id: str, request: SaveProtocolRequest, db: DbSession, user: ThrottledUser
) -> SavedProtocolResponse:
    """Store an edited protocol as the next version, with a changelog against the previous one."""
    try:
        return update_protocol(
            db,
            protocol_id=protocol_id,
            user_id=str(user.id),
            protocol=request.protocol,
            change_summary=request.change_summary,
        )
    except ProtocolRequestError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/{protocol_id}/history", response_model=ProtocolHistoryResponse)
def read_history(protocol_id: str, db: DbSession, user: ThrottledUser) -> ProtocolHistoryResponse:
    """Every version of the protocol, newest first, each with what changed."""
    try:
        return get_history(db, protocol_id=protocol_id, user_id=str(user.id))
    except ProtocolRequestError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/{protocol_id}/versions/{version}", response_model=SavedProtocolResponse)
def read_version(
    protocol_id: str, version: int, db: DbSession, user: ThrottledUser
) -> SavedProtocolResponse:
    try:
        return get_version(db, protocol_id=protocol_id, user_id=str(user.id), version=version)
    except ProtocolRequestError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


# Pure transformation: this builds the payload a Benchling client would send and performs no
# outbound request, so there is no credential in this path and nothing to leak to the browser.
@router.post("/export/eln", response_model=ElnExportPayload)
def export_eln(request: ElnExportRequest, _user: ThrottledUser) -> ElnExportPayload:
    """
    Transform a protocol into Benchling's documented entry format.

    Schema-ready and untested against the live API: the response carries
    `integration_status="schema_ready_untested"` so the UI cannot present it as a verified export.
    """
    try:
        return build_export(request)
    except ElnExportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


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
