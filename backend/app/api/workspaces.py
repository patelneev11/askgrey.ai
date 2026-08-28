from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import ClientIp, DbSession, ThrottledUser
from app.core import audit
from app.services.workspaces import (
    CreatedInvite,
    CreateWorkspaceRequest,
    InviteRequest,
    MemberSummary,
    RoleRequest,
    SeatLimitError,
    UpdateWorkspaceRequest,
    WorkspaceDetail,
    WorkspaceMembership,
    WorkspaceRequestError,
    WorkspaceSummary,
    accept_invite,
    create_workspace,
    delete_workspace,
    detail,
    invite_member,
    list_memberships,
    remove_member,
    revoke_invite,
    set_active,
    set_role,
    transfer_ownership,
    update_workspace,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class ActiveWorkspaceRequest(BaseModel):
    """Null switches the account back to working privately."""

    workspace_id: str | None = Field(default=None, max_length=36)


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=8, max_length=200)


def _log(
    event: str,
    *,
    db: Session,
    user_id: str,
    ip: str,
    outcome: audit.Outcome = "success",
    detail: dict[str, str | int | float | bool | None] | None = None,
) -> None:
    """
    Membership changes are security events, so they go to the trail.

    Never the invitation token, and never the invited address: an email names a person, and the
    trail records that a seat was offered, not who to. The workspace id is enough to follow.
    """
    audit.record(
        event, outcome=outcome, actor=user_id, client_ip=ip, detail=detail, db=db, user_id=user_id
    )


def _request_error(exc: WorkspaceRequestError) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


def _seat_error(exc: SeatLimitError) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.get("", response_model=WorkspaceMembership)
def read_memberships(db: DbSession, user: ThrottledUser) -> WorkspaceMembership:
    """The workspaces this account belongs to, and which one it is working in."""
    return list_memberships(db, user)


@router.post("", response_model=WorkspaceSummary, status_code=status.HTTP_201_CREATED)
def create(
    request: CreateWorkspaceRequest, db: DbSession, user: ThrottledUser, ip: ClientIp
) -> WorkspaceSummary:
    try:
        summary = create_workspace(db, user=user, request=request)
    except WorkspaceRequestError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    _log(
        "workspace.created",
        db=db,
        user_id=str(user.id),
        ip=ip,
        detail={"workspace_id": summary.id, "seat_limit": summary.seat_limit},
    )
    return summary


@router.put("/active", response_model=WorkspaceMembership)
def switch(
    request: ActiveWorkspaceRequest, db: DbSession, user: ThrottledUser
) -> WorkspaceMembership:
    try:
        return set_active(db, user=user, workspace_id=request.workspace_id)
    except WorkspaceRequestError as exc:
        raise _request_error(exc) from exc


@router.post("/invites/accept", response_model=WorkspaceSummary)
def accept(
    request: AcceptInviteRequest, db: DbSession, user: ThrottledUser, ip: ClientIp
) -> WorkspaceSummary:
    """Redeem an invitation token for the calling account, which then works in that workspace."""
    try:
        summary = accept_invite(db, user=user, token=request.token)
    except SeatLimitError as exc:
        raise _seat_error(exc) from exc
    except WorkspaceRequestError as exc:
        _log("workspace.invite_rejected", db=db, user_id=str(user.id), ip=ip, outcome="denied")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    _log(
        "workspace.invite_accepted",
        db=db,
        user_id=str(user.id),
        ip=ip,
        detail={"workspace_id": summary.id, "role": summary.role.value},
    )
    return summary


@router.get("/{workspace_id}", response_model=WorkspaceDetail)
def read(workspace_id: str, db: DbSession, user: ThrottledUser) -> WorkspaceDetail:
    try:
        return detail(db, workspace_id=workspace_id, user_id=str(user.id))
    except WorkspaceRequestError as exc:
        raise _request_error(exc) from exc


@router.patch("/{workspace_id}", response_model=WorkspaceSummary)
def update(
    workspace_id: str,
    request: UpdateWorkspaceRequest,
    db: DbSession,
    user: ThrottledUser,
    ip: ClientIp,
) -> WorkspaceSummary:
    try:
        summary = update_workspace(
            db, workspace_id=workspace_id, user_id=str(user.id), request=request
        )
    except SeatLimitError as exc:
        raise _seat_error(exc) from exc
    except WorkspaceRequestError as exc:
        raise _request_error(exc) from exc
    _log(
        "workspace.updated",
        db=db,
        user_id=str(user.id),
        ip=ip,
        detail={"workspace_id": workspace_id, "seat_limit": summary.seat_limit},
    )
    return summary


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(workspace_id: str, db: DbSession, user: ThrottledUser, ip: ClientIp) -> Response:
    try:
        delete_workspace(db, workspace_id=workspace_id, user_id=str(user.id))
    except WorkspaceRequestError as exc:
        raise _request_error(exc) from exc
    _log(
        "workspace.deleted",
        db=db,
        user_id=str(user.id),
        ip=ip,
        detail={"workspace_id": workspace_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{workspace_id}/invites", response_model=CreatedInvite, status_code=status.HTTP_201_CREATED
)
def invite(
    workspace_id: str,
    request: InviteRequest,
    db: DbSession,
    user: ThrottledUser,
    ip: ClientIp,
) -> CreatedInvite:
    """
    Offer a seat, returning the token once.

    There is no mail server, so the response carries the token for the inviter to pass on. It is
    not stored in the clear and no later read returns it.
    """
    try:
        created = invite_member(
            db, workspace_id=workspace_id, user_id=str(user.id), request=request
        )
    except SeatLimitError as exc:
        _log(
            "workspace.invite_refused",
            db=db,
            user_id=str(user.id),
            ip=ip,
            outcome="denied",
            detail={"workspace_id": workspace_id, "reason": "seat limit"},
        )
        raise _seat_error(exc) from exc
    except WorkspaceRequestError as exc:
        raise _request_error(exc) from exc
    _log(
        "workspace.invited",
        db=db,
        user_id=str(user.id),
        ip=ip,
        detail={"workspace_id": workspace_id, "role": created.invite.role.value},
    )
    return created


@router.delete("/{workspace_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_invite(
    workspace_id: str, invite_id: str, db: DbSession, user: ThrottledUser, ip: ClientIp
) -> Response:
    try:
        revoke_invite(db, workspace_id=workspace_id, user_id=str(user.id), invite_id=invite_id)
    except WorkspaceRequestError as exc:
        raise _request_error(exc) from exc
    _log(
        "workspace.invite_revoked",
        db=db,
        user_id=str(user.id),
        ip=ip,
        detail={"workspace_id": workspace_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{workspace_id}/members/{member_user_id}", response_model=MemberSummary)
def change_role(
    workspace_id: str,
    member_user_id: str,
    request: RoleRequest,
    db: DbSession,
    user: ThrottledUser,
    ip: ClientIp,
) -> MemberSummary:
    try:
        member = set_role(
            db,
            workspace_id=workspace_id,
            user_id=str(user.id),
            member_user_id=member_user_id,
            role=request.role,
        )
    except WorkspaceRequestError as exc:
        raise _request_error(exc) from exc
    _log(
        "workspace.role_changed",
        db=db,
        user_id=str(user.id),
        ip=ip,
        detail={"workspace_id": workspace_id, "role": member.role.value},
    )
    return member


@router.delete("/{workspace_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_seat(
    workspace_id: str,
    member_user_id: str,
    db: DbSession,
    user: ThrottledUser,
    ip: ClientIp,
) -> Response:
    """Remove a member, or leave the workspace by naming yourself."""
    leaving = member_user_id == str(user.id)
    try:
        remove_member(
            db, workspace_id=workspace_id, user_id=str(user.id), member_user_id=member_user_id
        )
    except WorkspaceRequestError as exc:
        raise _request_error(exc) from exc
    _log(
        "workspace.left" if leaving else "workspace.member_removed",
        db=db,
        user_id=str(user.id),
        ip=ip,
        detail={"workspace_id": workspace_id},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{workspace_id}/owner/{member_user_id}", response_model=WorkspaceDetail)
def transfer(
    workspace_id: str,
    member_user_id: str,
    db: DbSession,
    user: ThrottledUser,
    ip: ClientIp,
) -> WorkspaceDetail:
    """Hand the workspace to another member; the previous owner stays as an admin."""
    try:
        moved = transfer_ownership(
            db, workspace_id=workspace_id, user_id=str(user.id), member_user_id=member_user_id
        )
    except WorkspaceRequestError as exc:
        raise _request_error(exc) from exc
    _log(
        "workspace.ownership_transferred",
        db=db,
        user_id=str(user.id),
        ip=ip,
        detail={"workspace_id": workspace_id},
    )
    return moved
