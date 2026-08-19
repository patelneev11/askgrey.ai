from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import DbSession, ThrottledUser
from app.services.library import (
    ArtifactKind,
    LibraryRequestError,
    SaveArtifactRequest,
    SavedArtifactRead,
    SavedArtifactSummary,
    delete_artifact,
    get_artifact,
    list_artifacts,
    save_artifact,
)

router = APIRouter(prefix="/library", tags=["library"])


# Persistence only: no model call and no outbound request, so these ride the plain per-account
# API limit rather than the LLM limit and daily budget.
@router.post("", response_model=SavedArtifactRead, status_code=status.HTTP_201_CREATED)
def create_saved_artifact(
    request: SaveArtifactRequest, db: DbSession, user: ThrottledUser
) -> SavedArtifactRead:
    """
    Save one agent output under the calling account.

    Called only when the researcher asks to keep a result; the payload is re-validated against the
    model that produced it, so a stored artifact keeps the review caveats it was shown with.
    """
    try:
        return save_artifact(db, user_id=str(user.id), request=request)
    except LibraryRequestError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("", response_model=list[SavedArtifactSummary])
def list_saved_artifacts(
    db: DbSession, user: ThrottledUser, kind: ArtifactKind | None = None
) -> list[SavedArtifactSummary]:
    """The caller's saved items, newest first, so a save survives a page reload."""
    return list_artifacts(db, user_id=str(user.id), kind=kind)


@router.get("/{artifact_id}", response_model=SavedArtifactRead)
def read_saved_artifact(artifact_id: str, db: DbSession, user: ThrottledUser) -> SavedArtifactRead:
    try:
        return get_artifact(db, artifact_id=artifact_id, user_id=str(user.id))
    except LibraryRequestError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_saved_artifact(artifact_id: str, db: DbSession, user: ThrottledUser) -> Response:
    try:
        delete_artifact(db, artifact_id=artifact_id, user_id=str(user.id))
    except LibraryRequestError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
