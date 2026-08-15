from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import LlmUser, ThrottledUser
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

router = APIRouter(prefix="/grants", tags=["grants"])


def get_grants_service() -> GrantsService:
    return GrantsService.from_settings()


Service = Annotated[GrantsService, Depends(get_grants_service)]


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


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, InvalidQueryError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
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
