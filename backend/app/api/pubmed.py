from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import LlmUser
from app.services.pubmed import (
    EntrezRequestError,
    EntrezResponseError,
    InvalidQueryError,
    PubMedService,
    SearchResult,
    TranslationError,
)

router = APIRouter(prefix="/pubmed", tags=["pubmed"])


def get_pubmed_service() -> PubMedService:
    return PubMedService.from_settings()


Service = Annotated[PubMedService, Depends(get_pubmed_service)]


@router.get("/search", response_model=SearchResult)
async def search(
    _user: LlmUser,
    service: Service,
    q: Annotated[str, Query(min_length=1, max_length=1000, description="Natural language query")],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort: Annotated[str, Query(pattern="^(relevance|pub_date|author|journal)$")] = "relevance",
) -> SearchResult:
    try:
        return await service.search(q, limit=limit, offset=offset, sort=sort)
    except InvalidQueryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except TranslationError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Query translation failed: {exc}"
        ) from exc
    except (EntrezRequestError, EntrezResponseError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"PubMed request failed: {exc}") from exc
    finally:
        await service.aclose()
