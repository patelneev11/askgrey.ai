from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.api.deps import ClientIp, LlmUser, ThrottledUser
from app.api.export import download_response
from app.core import audit
from app.services.export import ExportError, ExportFormat
from app.services.grants import (
    MAX_PAGE_SIZE,
    GrantPage,
    GrantProgram,
    GrantSearch,
    GrantSource,
    GrantsRequestError,
    GrantsResponseError,
    GrantsService,
    InvalidQueryError,
    MatchingError,
    MatchResult,
)
from app.services.grants.budget import (
    BudgetCalculator,
    BudgetConfigError,
    BudgetInputError,
    BudgetRequest,
    BudgetRules,
    GrantBudget,
    render,
)
from app.services.grants.eligibility import (
    CompanyProfile,
    EligibilityChecker,
    EligibilityConfigError,
    EligibilityReport,
    RuleConfig,
)

router = APIRouter(prefix="/grants", tags=["grants"])


def get_grants_service() -> GrantsService:
    return GrantsService.from_settings()


def get_eligibility_checker() -> EligibilityChecker:
    # A broken rules file is a deployment fault, not a bad request: say so rather than letting
    # a config error surface as an opaque 500.
    try:
        return EligibilityChecker.from_config_file()
    except EligibilityConfigError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"eligibility rules are unusable: {exc}"
        ) from exc


def get_budget_calculator() -> BudgetCalculator:
    try:
        return BudgetCalculator.from_config_file()
    except BudgetConfigError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"budget rules are unusable: {exc}"
        ) from exc


Service = Annotated[GrantsService, Depends(get_grants_service)]
Checker = Annotated[EligibilityChecker, Depends(get_eligibility_checker)]
Calculator = Annotated[BudgetCalculator, Depends(get_budget_calculator)]


class MatchRequest(BaseModel):
    """Rank open opportunities against a short description of a company's research focus."""

    focus: str = Field(min_length=1, max_length=2000)
    keyword: str = Field(default="", max_length=200)
    agency: str = Field(default="", max_length=200)
    program: GrantProgram | None = None
    open_only: bool = True
    closing_after: date | None = None
    closing_before: date | None = None
    sources: list[GrantSource] = Field(
        default_factory=lambda: [GrantSource.GRANTS_GOV, GrantSource.SBIR]
    )
    limit: int = Field(default=10, ge=1, le=50)
    candidate_pool: int = Field(default=40, ge=1, le=100)

    def to_search(self) -> GrantSearch:
        return GrantSearch(
            keyword=self.keyword,
            agency=self.agency,
            program=self.program,
            open_only=self.open_only,
            closing_after=self.closing_after,
            closing_before=self.closing_before,
            sources=self.sources,
        )


class EligibilityRequest(BaseModel):
    """A structured company profile plus the set-aside programme to evaluate it against."""

    profile: CompanyProfile
    program: GrantProgram = GrantProgram.SBIR


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidQueryError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    if isinstance(exc, MatchingError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"grants request failed: {exc}")


@router.get("/search", response_model=GrantPage)
async def search(
    _user: ThrottledUser,
    service: Service,
    keyword: Annotated[str, Query(max_length=200, description="Topic keyword")] = "",
    agency: Annotated[
        str, Query(max_length=200, description="Agency name or code, e.g. NIH, BARDA, DoD")
    ] = "",
    program: Annotated[GrantProgram | None, Query(description="SBIR/STTR set-aside")] = None,
    open_only: Annotated[bool, Query(description="Exclude closed opportunities")] = True,
    closing_after: Annotated[date | None, Query(description="Earliest deadline")] = None,
    closing_before: Annotated[date | None, Query(description="Latest deadline")] = None,
    source: Annotated[list[GrantSource] | None, Query(description="Repeatable")] = None,
    page: Annotated[int, Query(ge=0, description="Offset page, per provider")] = 0,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
) -> GrantPage:
    query = GrantSearch(
        keyword=keyword,
        agency=agency,
        program=program,
        open_only=open_only,
        closing_after=closing_after,
        closing_before=closing_before,
        sources=source or [GrantSource.GRANTS_GOV, GrantSource.SBIR],
    )
    try:
        return await service.search(query, page=page, page_size=page_size)
    except (InvalidQueryError, GrantsRequestError, GrantsResponseError) as exc:
        raise _handle(exc) from exc
    finally:
        await service.aclose()


@router.post("/match", response_model=MatchResult)
async def match(_user: LlmUser, service: Service, request: MatchRequest) -> MatchResult:
    try:
        return await service.match(
            request.focus,
            request.to_search(),
            limit=request.limit,
            candidate_pool=request.candidate_pool,
        )
    except (InvalidQueryError, MatchingError, GrantsRequestError, GrantsResponseError) as exc:
        raise _handle(exc) from exc
    finally:
        await service.aclose()


@router.post("/eligibility", response_model=EligibilityReport)
def check_eligibility(
    _user: ThrottledUser, checker: Checker, request: EligibilityRequest
) -> EligibilityReport:
    """
    Rules-based SBIR/STTR eligibility screen.

    Deterministic: every verdict comes from a numeric threshold in the service's `rules.json`,
    so no model is consulted and the same profile always produces the same report.
    """
    try:
        return checker.check(request.profile, request.program)
    except InvalidQueryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/eligibility/rules", response_model=RuleConfig)
def eligibility_rules(_user: ThrottledUser, checker: Checker) -> RuleConfig:
    """The thresholds a report was produced under, so a verdict can be traced to its numbers."""
    return checker.config


@router.post("/budget", response_model=GrantBudget)
def build_budget(
    _user: ThrottledUser, calculator: Calculator, request: BudgetRequest
) -> GrantBudget:
    """Cost internal R&D estimates into SF-424 (R&R) shape under the configured federal rules."""
    try:
        return calculator.build(request)
    except BudgetInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/budget/rules", response_model=BudgetRules)
def budget_rules(_user: ThrottledUser, calculator: Calculator) -> BudgetRules:
    """The salary cap, indirect and fee figures the budget was built under."""
    return calculator.rules


@router.post("/budget/export")
def export_budget(
    user: ThrottledUser,
    ip: ClientIp,
    calculator: Calculator,
    request: BudgetRequest,
    fmt: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.XLSX,
) -> Response:
    """The same budget as a file, through the shared exporter rather than a second writer."""
    try:
        budget = calculator.build(request)
        response = download_response(render(budget, fmt))
    except (BudgetInputError, ExportError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    audit.record(
        "grants.budget_exported",
        actor=str(user.id),
        client_ip=ip,
        detail={"format": fmt.value, "program": budget.program.value},
    )
    return response
