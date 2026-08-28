from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import ActiveWorkspace, DbSession, ThrottledUser
from app.services.library import (
    ArtifactKind,
    LibraryPermissionError,
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
    request: SaveArtifactRequest,
    db: DbSession,
    user: ThrottledUser,
    workspace: ActiveWorkspace,
) -> SavedArtifactRead:
    """
    Save one agent output.

    Called only when the researcher asks to keep a result; the payload is re-validated against the
    model that produced it, so a stored artifact keeps the review caveats it was shown with. Saved
    while a workspace is active, the item belongs to that workspace and its members can read it.
    """
    try:
        return save_artifact(db, user_id=str(user.id), request=request, workspace=workspace)
    except LibraryPermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except LibraryRequestError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("", response_model=list[SavedArtifactSummary])
def list_saved_artifacts(
    db: DbSession,
    user: ThrottledUser,
    workspace: ActiveWorkspace,
    kind: ArtifactKind | None = None,
) -> list[SavedArtifactSummary]:
    """The caller's own saved items plus the active workspace's, newest first."""
    return list_artifacts(db, user_id=str(user.id), kind=kind, workspace=workspace)


@router.get("/{artifact_id}", response_model=SavedArtifactRead)
def read_saved_artifact(
    artifact_id: str, db: DbSession, user: ThrottledUser, workspace: ActiveWorkspace
) -> SavedArtifactRead:
    try:
        return get_artifact(db, artifact_id=artifact_id, user_id=str(user.id), workspace=workspace)
    except LibraryRequestError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_saved_artifact(
    artifact_id: str, db: DbSession, user: ThrottledUser, workspace: ActiveWorkspace
) -> Response:
    try:
        delete_artifact(db, artifact_id=artifact_id, user_id=str(user.id), workspace=workspace)
    except LibraryPermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except LibraryRequestError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
