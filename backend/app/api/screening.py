from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import LlmUser, ThrottledUser
from app.services.screening import MAX_SMILES_LENGTH, InvalidStructureError
from app.services.screening.admet import AdmetProfile, AdmetService
from app.services.screening.sar import DescriptorProfile, SarService, SuggestionSet

router = APIRouter(prefix="/screening", tags=["screening"])


def get_sar_service() -> SarService:
    return SarService.from_settings()


def get_admet_service() -> AdmetService:
    return AdmetService()


Sar = Annotated[SarService, Depends(get_sar_service)]
Admet = Annotated[AdmetService, Depends(get_admet_service)]


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


@router.post("/admet", response_model=AdmetProfile)
async def admet(
    _user: ThrottledUser,
    service: Admet,
    request: StructureRequest,
) -> AdmetProfile:
    """ADMET classifications from published physicochemical rules, each carrying its model basis."""
    try:
        return service.evaluate(request.smiles)
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
