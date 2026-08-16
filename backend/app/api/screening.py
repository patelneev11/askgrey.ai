from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import LlmUser, ThrottledUser
from app.services.screening import MAX_SMILES_LENGTH, InvalidStructureError
from app.services.screening.patents import (
    InvalidFilterError,
    InvalidKeywordError,
    PatentLandscape,
    PatentRequestError,
    PatentSearch,
    PatentsService,
)
from app.services.screening.sar import DescriptorProfile, SarService, SuggestionSet

router = APIRouter(prefix="/screening", tags=["screening"])


def get_sar_service() -> SarService:
    return SarService.from_settings()


def get_patents_service() -> PatentsService:
    return PatentsService.from_settings()


Sar = Annotated[SarService, Depends(get_sar_service)]
Patents = Annotated[PatentsService, Depends(get_patents_service)]


class StructureRequest(BaseModel):
    """A single small molecule, as SMILES. Bounded here and re-validated in the service."""

    smiles: str = Field(min_length=1, max_length=MAX_SMILES_LENGTH)


@router.post("/sar/descriptors", response_model=DescriptorProfile)
async def descriptors(
    _user: ThrottledUser,
    service: Sar,
    request: StructureRequest,
) -> DescriptorProfile:
    """Deterministic RDKit descriptors and drug-likeness rule-set outcomes."""
    try:
        return service.profile(request.smiles)
    except InvalidStructureError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("/sar/suggestions", response_model=SuggestionSet)
async def suggestions(
    _user: LlmUser,
    service: Sar,
    request: StructureRequest,
) -> SuggestionSet:
    """Heuristic substituent modification suggestions. LLM-backed, so LLM-throttled."""
    try:
        return await service.suggestions(request.smiles)
    except InvalidStructureError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    finally:
        await service.aclose()


@router.post("/patents/search", response_model=PatentLandscape)
async def patent_search(
    _user: ThrottledUser,
    service: Patents,
    request: PatentSearch,
) -> PatentLandscape:
    """
    Keyword prior-art search over USPTO patent applications. External HTTP, so throttled.

    Not a structural search and not a novelty or FTO assessment: the response carries the
    derived text query, a caveat, and an explicit unavailable entry for each of those.
    """
    try:
        return await service.search(request)
    except (InvalidStructureError, InvalidKeywordError, InvalidFilterError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except PatentRequestError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "the patent search API rejected the derived query"
        ) from exc
    finally:
        await service.aclose()
