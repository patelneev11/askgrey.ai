from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser
from app.services.pubchem import (
    CompoundLookup,
    CompoundNotFoundError,
    IdentifierKind,
    InvalidIdentifierError,
    PubChemRequestError,
    PubChemResponseError,
    PubChemService,
)

router = APIRouter(prefix="/pubchem", tags=["pubchem"])


def get_pubchem_service() -> PubChemService:
    return PubChemService.from_settings()


Service = Annotated[PubChemService, Depends(get_pubchem_service)]


@router.get("/compound", response_model=CompoundLookup)
async def compound(
    _user: CurrentUser,
    service: Service,
    q: Annotated[str, Query(min_length=1, max_length=4000, description="SMILES, name or synonym")],
    kind: Annotated[IdentifierKind | None, Query(description="Force an interpretation")] = None,
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> CompoundLookup:
    try:
        return await service.lookup(q, kind=kind, limit=limit)
    except InvalidIdentifierError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except CompoundNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (PubChemRequestError, PubChemResponseError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"PubChem request failed: {exc}") from exc
    finally:
        await service.aclose()
