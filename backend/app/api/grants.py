from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import ClientIp, LlmUser, ThrottledUser
from app.core import audit
from app.core.config import get_settings
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
from app.services.grants.review_board import (
    MAX_TEXT_CHARS,
    MIN_TEXT_CHARS,
    BoardReport,
    PersonaSummary,
    ProposalSection,
    ReviewBoard,
    ReviewBoardError,
    ReviewBoardUnavailableError,
)

router = APIRouter(prefix="/grants", tags=["grants"])


def get_grants_service() -> GrantsService:
    return GrantsService.from_settings()


def get_review_board() -> ReviewBoard:
    return ReviewBoard.from_settings()


Service = Annotated[GrantsService, Depends(get_grants_service)]
Board = Annotated[ReviewBoard, Depends(get_review_board)]


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


class ReviewBoardRequest(BaseModel):
    """
    Put one draft proposal section in front of the configured reviewer personas.

    `text` is bounded at both ends: below the floor there is nothing for a persona to review,
    and the ceiling is what one Claude call per persona is sized for.
    """

    section_name: str = Field(min_length=1, max_length=200)
    program: str = Field(default="", max_length=100)
    phase: str = Field(default="", max_length=100)
    text: str = Field(min_length=MIN_TEXT_CHARS, max_length=MAX_TEXT_CHARS)
    personas: list[str] = Field(default_factory=list, max_length=10)

    def to_section(self) -> ProposalSection:
        return ProposalSection(
            section_name=self.section_name,
            program=self.program,
            phase=self.phase,
            text=self.text,
        )


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidQueryError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    if isinstance(exc, ReviewBoardUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    if isinstance(exc, MatchingError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    if isinstance(exc, ReviewBoardError):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
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


@router.get("/review-board/personas", response_model=list[PersonaSummary])
def review_board_personas(_user: ThrottledUser, board: Board) -> list[PersonaSummary]:
    """The enabled reviewer personas and what each scores. Their system prompts are not served."""
    return board.personas()


@router.post("/review-board", response_model=BoardReport)
async def review_board(
    user: LlmUser,
    ip: ClientIp,
    board: Board,
    request: ReviewBoardRequest,
) -> BoardReport:
    """
    Score a draft section against the configured personas.

    The report carries `validation_status` and `caveat`, and it is 503 rather than a heuristic
    score when no LLM is configured: nothing here invents a review.
    """
    try:
        personas = board.select(request.personas or None)
        if board.available:
            # Note that draft proposal text left the deployment for the model vendor. Provenance
            # only — never the draft itself, the persona prompts, or the scores. Not recorded
            # when no reviewer is configured, since then nothing is sent.
            audit.record(
                "grant_section.sent_to_llm",
                actor=str(user.id),
                client_ip=ip,
                detail={
                    "chars": len(request.text),
                    "personas": ",".join(persona.id for persona in personas),
                    "vendor": "anthropic",
                    "model": get_settings().llm_model,
                },
            )
        return await board.review(request.to_section(), request.personas or None)
    except (InvalidQueryError, ReviewBoardError) as exc:
        raise _handle(exc) from exc
    finally:
        await board.aclose()
