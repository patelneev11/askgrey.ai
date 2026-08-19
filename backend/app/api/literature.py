from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.api.deps import ClientIp, DbSession, ThrottledUser
from app.core import audit
from app.schemas.literature import WorkspaceRead, WorkspaceWrite
from app.services import literature as literature_service

router = APIRouter(prefix="/literature", tags=["literature"])

# A document id is a digest of the paper's bytes; anything else is not worth a lookup.
DocumentId = Annotated[str, Path(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


@router.get("/workspace", response_model=WorkspaceRead)
def read_workspace(user: ThrottledUser, db: DbSession) -> WorkspaceRead:
    return literature_service.get_workspace(db, str(user.id))


@router.put("/workspace", response_model=WorkspaceRead)
def write_workspace(user: ThrottledUser, db: DbSession, payload: WorkspaceWrite) -> WorkspaceRead:
    try:
        return literature_service.save_workspace(db, str(user.id), payload)
    except literature_service.WorkspaceTooLargeError as exc:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc


@router.delete("/workspace", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(user: ThrottledUser, db: DbSession, ip: ClientIp) -> Response:
    """Clear the saved workspace and delete the papers stored behind it."""
    documents = literature_service.clear_workspace(db, str(user.id))
    audit.record(
        "literature.workspace_deleted",
        actor=str(user.id),
        client_ip=ip,
        detail={"documents_deleted": documents},
        db=db,
        user_id=str(user.id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    user: ThrottledUser,
    db: DbSession,
    ip: ClientIp,
    document_id: DocumentId,
) -> Response:
    """Delete one stored paper.

    Scoped like the read: a document stored by somebody else is a 404, indistinguishable from
    one that was never stored, so a delete cannot be used to probe another account's library.
    """
    deleted = literature_service.delete_document(db, str(user.id), document_id)
    audit.record(
        "literature.document_deleted",
        outcome="success" if deleted else "failure",
        actor=str(user.id),
        client_ip=ip,
        detail={"document_id": document_id},
        db=db,
        user_id=str(user.id),
    )
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such document")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/documents/{document_id}/pdf",
    responses={200: {"content": {"application/pdf": {}}}},
    response_class=Response,
)
def read_document(
    user: ThrottledUser,
    db: DbSession,
    ip: ClientIp,
    document_id: DocumentId,
) -> Response:
    """Serve back a paper this user already added, so its cited page can be rendered.

    This is not a proxy: it only ever returns bytes already stored against the calling
    user's own account, and it takes a document id rather than a URL, so it cannot be
    pointed at an arbitrary target. A document belonging to someone else is a 404 —
    indistinguishable from one that was never stored.
    """
    document = literature_service.get_document(db, str(user.id), document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such document")
    audit.record(
        "literature.document_read",
        actor=str(user.id),
        client_ip=ip,
        detail={"document_id": document_id, "bytes": document.byte_size},
        db=db,
        user_id=str(user.id),
    )
    return Response(
        content=document.content,
        media_type="application/pdf",
        headers={
            "Content-Length": str(document.byte_size),
            # The viewer renders it with pdf.js; nothing should ever navigate to it.
            "Content-Disposition": 'inline; filename="paper.pdf"',
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )
