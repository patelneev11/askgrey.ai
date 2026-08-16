from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import LlmUser, ThrottledUser
from app.services.regulatory.ind import (
    IndDraft,
    IndDrafterError,
    IndDrafterUnavailableError,
    IndDraftRequest,
    IndRequestError,
    IndService,
    StructureResponse,
)
from app.services.regulatory.preclinical import (
    DrafterError,
    DrafterUnavailableError,
    PreclinicalReport,
    PreclinicalRequestError,
    PreclinicalService,
    StudyTable,
)

router = APIRouter(prefix="/regulatory", tags=["regulatory"])


def get_preclinical_service() -> PreclinicalService:
    return PreclinicalService.from_settings()


Preclinical = Annotated[PreclinicalService, Depends(get_preclinical_service)]


def _handle(exc: Exception) -> HTTPException:
    """
    Map service failures to client-safe statuses.

    The messages these exceptions carry are written not to quote study data: a request body
    here can contain unpublished manufacturing or animal study detail, and an error is the
    easiest place for that to leak into a log or a browser console.
    """
    if isinstance(exc, PreclinicalRequestError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    if isinstance(exc, DrafterUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "drafting the narrative failed")


@router.post("/preclinical/report", response_model=PreclinicalReport)
async def preclinical_report(
    _user: LlmUser, service: Preclinical, table: StudyTable
) -> PreclinicalReport:
    """
    Draft a preclinical study narrative from a structured study table and audit its numbers.

    `LlmUser` rather than `ThrottledUser`: this spends money at Anthropic, so it takes the
    per-minute LLM limit and the daily call budget as well as authentication.
    """
    try:
        return await service.draft_report(table)
    except (PreclinicalRequestError, DrafterUnavailableError, DrafterError) as exc:
        raise _handle(exc) from exc
    finally:
        await service.aclose()


def get_ind_service() -> IndService:
    return IndService.from_settings()


Ind = Annotated[IndService, Depends(get_ind_service)]


@router.get("/ind/structure", response_model=StructureResponse)
def ind_structure(_user: ThrottledUser, service: Ind) -> StructureResponse:
    """
    The dated CTD heading tree this service drafts against, with the documents it came from.

    Reads a file rather than calling a model, so it takes the ordinary API limit.
    """
    return service.structure_response()


@router.post("/ind/draft", response_model=IndDraft)
async def ind_draft(_user: LlmUser, service: Ind, request: IndDraftRequest) -> IndDraft:
    """Draft the requested Module 3 / Module 4 sections and report what the data lacks."""
    try:
        return await service.draft(request)
    except (IndRequestError, IndDrafterUnavailableError, IndDrafterError) as exc:
        raise _handle_ind(exc) from exc
    finally:
        await service.aclose()


def _handle_ind(exc: Exception) -> HTTPException:
    """Same reasoning as `_handle`: submitted batch and study data must not reach the client."""
    if isinstance(exc, IndRequestError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    if isinstance(exc, IndDrafterUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "drafting the sections failed")
