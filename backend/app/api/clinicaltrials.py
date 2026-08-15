from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import ThrottledUser
from app.services.clinicaltrials import (
    MAX_PAGE_SIZE,
    ClinicalTrialsRequestError,
    ClinicalTrialsResponseError,
    ClinicalTrialsService,
    InvalidQueryError,
    TrialPage,
    TrialPhase,
    TrialSearch,
    TrialStatus,
)

router = APIRouter(prefix="/clinicaltrials", tags=["clinicaltrials"])


def get_clinicaltrials_service() -> ClinicalTrialsService:
    return ClinicalTrialsService.from_settings()


Service = Annotated[ClinicalTrialsService, Depends(get_clinicaltrials_service)]


@router.get("/search", response_model=TrialPage)
async def search(
    _user: ThrottledUser,
    service: Service,
    sponsor: Annotated[str, Query(max_length=200, description="Lead sponsor or collaborator")] = "",
    condition: Annotated[str, Query(max_length=200, description="Disease or condition")] = "",
    intervention: Annotated[str, Query(max_length=200, description="Drug or intervention")] = "",
    term: Annotated[
        str, Query(max_length=200, description="Free-text search across the study")
    ] = "",
    phase: Annotated[list[TrialPhase] | None, Query(description="Repeatable; OR-ed")] = None,
    trial_status: Annotated[
        list[TrialStatus] | None, Query(alias="status", description="Repeatable; OR-ed")
    ] = None,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
    page_token: Annotated[str | None, Query(description="Cursor from a previous page")] = None,
) -> TrialPage:
    query = TrialSearch(
        sponsor=sponsor,
        condition=condition,
        intervention=intervention,
        term=term,
        phases=phase or [],
        statuses=trial_status or [],
    )
    try:
        return await service.search(query, page_size=page_size, page_token=page_token)
    except InvalidQueryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except (ClinicalTrialsRequestError, ClinicalTrialsResponseError) as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"ClinicalTrials.gov request failed: {exc}"
        ) from exc
    finally:
        await service.aclose()
