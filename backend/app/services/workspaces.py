"""
Shared workspaces: membership, roles, seats and invitations.

A workspace is a group of accounts that share saved work. It shares *findings* — extraction
tables, drafts, budgets, protocols — and not stored papers: a paper's ciphertext is bound to one
account through its KMS encryption context and carries that account's retention clock and quota,
so making bytes org-wide is a separate decision with a publisher-licence question attached.

Access is decided here and nowhere else. Every read and write of shared work asks this module for
an `Access` — the workspace the caller is working in plus the role they hold in it — and the
services that store work take that object rather than a workspace id, so a caller cannot name a
workspace it is not a member of.

There is no mail server in this deployment, so an invitation is a single-use token shown to the
inviter once and handed over out of band. Only its hash is stored, so a database read cannot be
replayed into workspace access.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.library import SavedArtifact
from app.models.protocol import ProtocolVersion, SavedProtocol
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceInvite, WorkspaceMember, WorkspaceRole

# A researcher belongs to a handful of groups, not a directory of them; a page of memberships is
# the whole list.
MAX_WORKSPACES_OWNED = 10
DEFAULT_SEAT_LIMIT = 5
MAX_SEAT_LIMIT = 50
INVITE_TTL_DAYS = 14
# Long enough that the token is the secret, not the email address it was sent to.
INVITE_TOKEN_BYTES = 32


class WorkspaceError(Exception):
    """Base class for workspace failures."""


class WorkspaceRequestError(WorkspaceError):
    """The caller asked for something that does not exist, or is not allowed to."""


class SeatLimitError(WorkspaceError):
    """The workspace has no seat free for another member or pending invitation."""


@dataclass(frozen=True)
class Access:
    """
    The right to act on one workspace's shared work.

    Only this module constructs it, so possession of an `Access` is proof that the membership was
    checked. `may_write` and `may_administer` are asked by the services that store work, so the
    role rules live in one place rather than being restated per tab.
    """

    workspace_id: str
    user_id: str
    role: WorkspaceRole

    @property
    def may_write(self) -> bool:
        """Viewers read shared work; everyone else may add to it."""
        return self.role.at_least(WorkspaceRole.MEMBER)

    @property
    def may_administer(self) -> bool:
        """Admins and the owner may edit or remove work they did not save."""
        return self.role.at_least(WorkspaceRole.ADMIN)


class MemberSummary(BaseModel):
    user_id: str
    email: str
    full_name: str
    role: WorkspaceRole
    joined_at: datetime
    is_owner: bool


class InviteSummary(BaseModel):
    """A pending invitation. The token is never returned again after it was created."""

    id: str
    email: str
    role: WorkspaceRole
    invited_by_user_id: str
    created_at: datetime
    expires_at: datetime


class WorkspaceSummary(BaseModel):
    id: str
    name: str
    role: WorkspaceRole
    seat_limit: int
    seats_used: int
    member_count: int
    created_at: datetime


class WorkspaceDetail(WorkspaceSummary):
    members: list[MemberSummary]
    # Only administrators see who has been invited; a viewer has no business reading the list of
    # addresses the workspace has approached.
    invites: list[InviteSummary]


class WorkspaceMembership(BaseModel):
    """What the app needs to render the workspace switcher and scope saved work."""

    workspaces: list[WorkspaceSummary]
    active_workspace_id: str | None


class CreatedInvite(BaseModel):
    """
    The one response that carries an invitation token.

    The token is not stored in the clear and is not returned by any later read, so the inviter
    copies it now or revokes the invitation and issues another.
    """

    invite: InviteSummary
    token: str


class CreateWorkspaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    seat_limit: int = Field(default=DEFAULT_SEAT_LIMIT, ge=1, le=MAX_SEAT_LIMIT)


class UpdateWorkspaceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    seat_limit: int | None = Field(default=None, ge=1, le=MAX_SEAT_LIMIT)


class InviteRequest(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.MEMBER


class RoleRequest(BaseModel):
    role: WorkspaceRole


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes even for timezone-aware columns."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _normalized(email: str) -> str:
    return email.strip().lower()


def _membership(db: Session, *, workspace_id: str, user_id: str) -> WorkspaceMember | None:
    return db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )


def access(
    db: Session, *, workspace_id: str, user_id: str, floor: WorkspaceRole = WorkspaceRole.VIEWER
) -> Access:
    """
    The caller's right to act on this workspace, or a failure that does not confirm it exists.

    A workspace the caller is not a member of is reported as missing rather than forbidden, so
    the endpoints cannot be used to discover which workspace ids are real. A role too low for the
    operation is a different message: the workspace is one the caller can see, so hiding why the
    action failed would only leave them guessing.
    """
    member = _membership(db, workspace_id=workspace_id, user_id=user_id)
    if member is None:
        raise WorkspaceRequestError("no workspace with that id")
    if not member.role.at_least(floor):
        raise WorkspaceRequestError(
            f"this action needs the {floor.value} role; you are a {member.role.value}"
        )
    return Access(workspace_id=workspace_id, user_id=user_id, role=member.role)


def active_access(db: Session, user: User) -> Access | None:
    """
    The workspace this account is currently working in, or None for private work.

    A pointer at a workspace the account is no longer a member of reads as private and is
    cleared, so removing someone takes effect on their next request rather than when they next
    choose to switch.
    """
    workspace_id = user.active_workspace_id
    if not workspace_id:
        return None
    member = _membership(db, workspace_id=workspace_id, user_id=str(user.id))
    if member is None:
        user.active_workspace_id = None
        db.commit()
        return None
    return Access(workspace_id=workspace_id, user_id=str(user.id), role=member.role)


def _seats_used(db: Session, workspace_id: str) -> int:
    """Members plus invitations still open: an invitation holds a seat, or seats mean nothing."""
    members = (
        db.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id)
        )
        or 0
    )
    pending = (
        db.scalar(
            select(func.count())
            .select_from(WorkspaceInvite)
            .where(
                WorkspaceInvite.workspace_id == workspace_id,
                WorkspaceInvite.accepted_at.is_(None),
                WorkspaceInvite.revoked_at.is_(None),
                WorkspaceInvite.expires_at > _now(),
            )
        )
        or 0
    )
    return int(members) + int(pending)


def _member_count(db: Session, workspace_id: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id)
        )
        or 0
    )


def _summary(db: Session, workspace: Workspace, role: WorkspaceRole) -> WorkspaceSummary:
    return WorkspaceSummary(
        id=workspace.id,
        name=workspace.name,
        role=role,
        seat_limit=workspace.seat_limit,
        seats_used=_seats_used(db, workspace.id),
        member_count=_member_count(db, workspace.id),
        created_at=_as_utc(workspace.created_at),
    )


def _workspace(db: Session, workspace_id: str) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:  # pragma: no cover - membership rows cascade with the workspace
        raise WorkspaceRequestError("no workspace with that id")
    return workspace


def create_workspace(
    db: Session, *, user: User, request: CreateWorkspaceRequest
) -> WorkspaceSummary:
    """Start a workspace with its creator as owner, and make it the account's active one."""
    owned = (
        db.scalar(
            select(func.count())
            .select_from(Workspace)
            .where(Workspace.owner_user_id == str(user.id))
        )
        or 0
    )
    if int(owned) >= MAX_WORKSPACES_OWNED:
        raise WorkspaceRequestError(f"this account already owns {MAX_WORKSPACES_OWNED} workspaces")
    workspace = Workspace(
        name=request.name.strip(),
        owner_user_id=str(user.id),
        seat_limit=request.seat_limit,
    )
    db.add(workspace)
    db.flush()
    db.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=str(user.id), role=WorkspaceRole.OWNER)
    )
    user.active_workspace_id = workspace.id
    db.commit()
    db.refresh(workspace)
    return _summary(db, workspace, WorkspaceRole.OWNER)


def update_workspace(
    db: Session, *, workspace_id: str, user_id: str, request: UpdateWorkspaceRequest
) -> WorkspaceSummary:
    granted = access(db, workspace_id=workspace_id, user_id=user_id, floor=WorkspaceRole.OWNER)
    workspace = _workspace(db, workspace_id)
    if request.name is not None:
        workspace.name = request.name.strip()
    if request.seat_limit is not None:
        used = _seats_used(db, workspace_id)
        if request.seat_limit < used:
            raise SeatLimitError(
                f"{used} seats are in use; remove members or revoke invitations first"
            )
        workspace.seat_limit = request.seat_limit
    db.commit()
    db.refresh(workspace)
    return _summary(db, workspace, granted.role)


def delete_workspace(db: Session, *, workspace_id: str, user_id: str) -> None:
    """
    Remove a workspace, and with it the work its members shared into it.

    Shared rows cascade: work saved into a workspace was saved to be shared, so leaving it
    readable to whoever saved it would be a quieter outcome than the owner asked for. Private
    work is untouched, because it never carried a workspace id.
    """
    access(db, workspace_id=workspace_id, user_id=user_id, floor=WorkspaceRole.OWNER)
    workspace = _workspace(db, workspace_id)
    db.execute(
        update(User)
        .where(User.active_workspace_id == workspace_id)
        .values(active_workspace_id=None)
    )
    # The dependent rows are removed here rather than left to the foreign keys: SQLite does not
    # enforce them unless the connection asks it to, and a workspace whose shared work survives
    # on one database and not another is worse than either behaviour.
    shared_protocols = db.scalars(
        select(SavedProtocol.id).where(SavedProtocol.workspace_id == workspace_id)
    ).all()
    if shared_protocols:
        db.execute(delete(ProtocolVersion).where(ProtocolVersion.protocol_id.in_(shared_protocols)))
    db.execute(delete(SavedProtocol).where(SavedProtocol.workspace_id == workspace_id))
    db.execute(delete(SavedArtifact).where(SavedArtifact.workspace_id == workspace_id))
    db.execute(delete(WorkspaceInvite).where(WorkspaceInvite.workspace_id == workspace_id))
    db.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id))
    db.delete(workspace)
    db.commit()


def list_memberships(db: Session, user: User) -> WorkspaceMembership:
    rows = db.execute(
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == str(user.id))
        .order_by(Workspace.created_at.asc())
    ).all()
    active = active_access(db, user)
    return WorkspaceMembership(
        workspaces=[_summary(db, workspace, role) for workspace, role in rows],
        active_workspace_id=active.workspace_id if active is not None else None,
    )


def set_active(db: Session, *, user: User, workspace_id: str | None) -> WorkspaceMembership:
    """Switch the account into a workspace, or out of all of them."""
    if workspace_id:
        access(db, workspace_id=workspace_id, user_id=str(user.id))
    user.active_workspace_id = workspace_id or None
    db.commit()
    return list_memberships(db, user)


def _members(db: Session, workspace: Workspace) -> list[MemberSummary]:
    rows = db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace.id)
        .order_by(WorkspaceMember.joined_at.asc())
    ).all()
    return [
        MemberSummary(
            user_id=member.user_id,
            email=user.email,
            full_name=user.full_name,
            role=member.role,
            joined_at=_as_utc(member.joined_at),
            is_owner=member.user_id == workspace.owner_user_id,
        )
        for member, user in rows
    ]


def _pending(db: Session, workspace_id: str) -> list[WorkspaceInvite]:
    return list(
        db.scalars(
            select(WorkspaceInvite)
            .where(
                WorkspaceInvite.workspace_id == workspace_id,
                WorkspaceInvite.accepted_at.is_(None),
                WorkspaceInvite.revoked_at.is_(None),
                WorkspaceInvite.expires_at > _now(),
            )
            .order_by(WorkspaceInvite.created_at.asc())
        ).all()
    )


def _invite_summary(invite: WorkspaceInvite) -> InviteSummary:
    return InviteSummary(
        id=invite.id,
        email=invite.email,
        role=invite.role,
        invited_by_user_id=invite.invited_by_user_id,
        created_at=_as_utc(invite.created_at),
        expires_at=_as_utc(invite.expires_at),
    )


def detail(db: Session, *, workspace_id: str, user_id: str) -> WorkspaceDetail:
    """The workspace as its members see it; only administrators see pending invitations."""
    granted = access(db, workspace_id=workspace_id, user_id=user_id)
    workspace = _workspace(db, workspace_id)
    summary = _summary(db, workspace, granted.role)
    invites = _pending(db, workspace_id) if granted.may_administer else []
    return WorkspaceDetail(
        **summary.model_dump(),
        members=_members(db, workspace),
        invites=[_invite_summary(invite) for invite in invites],
    )


def invite_member(
    db: Session, *, workspace_id: str, user_id: str, request: InviteRequest
) -> CreatedInvite:
    """
    Offer a seat to an email address, returning the token exactly once.

    An address that already holds a seat or an open invitation is refused rather than issued a
    second token: two live tokens for one seat is how a seat limit stops meaning anything.
    """
    access(db, workspace_id=workspace_id, user_id=user_id, floor=WorkspaceRole.ADMIN)
    if request.role is WorkspaceRole.OWNER:
        raise WorkspaceRequestError("a workspace has one owner; invite an admin instead")
    workspace = _workspace(db, workspace_id)
    email = _normalized(str(request.email))

    existing = db.scalar(
        select(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id, User.email == email)
    )
    if existing is not None:
        raise WorkspaceRequestError("that address already has a seat in this workspace")
    if any(invite.email == email for invite in _pending(db, workspace_id)):
        raise WorkspaceRequestError("that address already has an invitation waiting")
    if _seats_used(db, workspace_id) >= workspace.seat_limit:
        raise SeatLimitError(
            f"all {workspace.seat_limit} seats are taken; raise the limit or free one first"
        )

    token = secrets.token_urlsafe(INVITE_TOKEN_BYTES)
    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        email=email,
        role=request.role,
        token_hash=_digest(token),
        invited_by_user_id=user_id,
        expires_at=_now() + timedelta(days=INVITE_TTL_DAYS),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return CreatedInvite(invite=_invite_summary(invite), token=token)


def revoke_invite(db: Session, *, workspace_id: str, user_id: str, invite_id: str) -> None:
    access(db, workspace_id=workspace_id, user_id=user_id, floor=WorkspaceRole.ADMIN)
    invite = db.get(WorkspaceInvite, invite_id)
    if invite is None or invite.workspace_id != workspace_id or invite.accepted_at is not None:
        raise WorkspaceRequestError("no open invitation with that id")
    invite.revoked_at = _now()
    db.commit()


def accept_invite(db: Session, *, user: User, token: str) -> WorkspaceSummary:
    """
    Redeem an invitation for the calling account.

    The invitation is found by the hash of the token, so the stored row is not the secret, and it
    must have been addressed to this account's own email: a token that leaked out of a mailbox
    should not let a stranger into the workspace it was meant for. The seat limit is re-checked
    here, because seats can have been filled between the invitation and the acceptance.
    """
    digest = _digest(token.strip())
    invite = db.scalar(select(WorkspaceInvite).where(WorkspaceInvite.token_hash == digest))
    if invite is None:
        raise WorkspaceRequestError("that invitation is not valid")
    if invite.accepted_at is not None or invite.revoked_at is not None:
        raise WorkspaceRequestError("that invitation has already been used or was revoked")
    if _as_utc(invite.expires_at) <= _now():
        raise WorkspaceRequestError("that invitation has expired; ask for another")
    if _normalized(user.email) != invite.email:
        raise WorkspaceRequestError("that invitation was sent to a different address")

    workspace = _workspace(db, invite.workspace_id)
    if _membership(db, workspace_id=workspace.id, user_id=str(user.id)) is not None:
        raise WorkspaceRequestError("this account already has a seat in that workspace")
    # The invitation itself holds one of the seats it is about to convert into a membership.
    if _seats_used(db, workspace.id) > workspace.seat_limit:
        raise SeatLimitError("that workspace has no seat free")

    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=str(user.id), role=invite.role))
    invite.accepted_at = _now()
    user.active_workspace_id = workspace.id
    db.commit()
    db.refresh(workspace)
    return _summary(db, workspace, invite.role)


def set_role(
    db: Session, *, workspace_id: str, user_id: str, member_user_id: str, role: WorkspaceRole
) -> MemberSummary:
    """
    Change what a member may do.

    The owner's own role is fixed: a workspace with no owner has nobody who can delete it or
    raise its seat limit, and an admin who could demote the owner would be the owner.
    """
    access(db, workspace_id=workspace_id, user_id=user_id, floor=WorkspaceRole.ADMIN)
    workspace = _workspace(db, workspace_id)
    if role is WorkspaceRole.OWNER:
        raise WorkspaceRequestError("ownership is transferred, not granted as a role")
    if member_user_id == workspace.owner_user_id:
        raise WorkspaceRequestError("the owner's role cannot be changed")
    member = _membership(db, workspace_id=workspace_id, user_id=member_user_id)
    if member is None:
        raise WorkspaceRequestError("that account is not a member of this workspace")
    member.role = role
    db.commit()
    return next(summary for summary in _members(db, workspace) if summary.user_id == member_user_id)


def remove_member(db: Session, *, workspace_id: str, user_id: str, member_user_id: str) -> None:
    """
    Take a seat back, leaving the work that member shared in place.

    Shared work stays: it was contributed to the workspace, and a departure that silently deleted
    a colleague's protocols would be a data loss nobody asked for. Their private work was never
    in the workspace to begin with.
    """
    granted = access(db, workspace_id=workspace_id, user_id=user_id)
    workspace = _workspace(db, workspace_id)
    leaving = member_user_id == user_id
    if not leaving and not granted.may_administer:
        raise WorkspaceRequestError("only an admin can remove another member")
    if member_user_id == workspace.owner_user_id:
        raise WorkspaceRequestError("the owner cannot leave; transfer the workspace or delete it")
    member = _membership(db, workspace_id=workspace_id, user_id=member_user_id)
    if member is None:
        raise WorkspaceRequestError("that account is not a member of this workspace")
    db.delete(member)
    db.execute(
        update(User)
        .where(User.id == member_user_id, User.active_workspace_id == workspace_id)
        .values(active_workspace_id=None)
    )
    db.commit()


def transfer_ownership(
    db: Session, *, workspace_id: str, user_id: str, member_user_id: str
) -> WorkspaceDetail:
    """Hand the workspace to another member, demoting the previous owner to admin."""
    access(db, workspace_id=workspace_id, user_id=user_id, floor=WorkspaceRole.OWNER)
    workspace = _workspace(db, workspace_id)
    successor = _membership(db, workspace_id=workspace_id, user_id=member_user_id)
    if successor is None:
        raise WorkspaceRequestError("that account is not a member of this workspace")
    if member_user_id == workspace.owner_user_id:
        raise WorkspaceRequestError("that account already owns this workspace")
    previous = _membership(db, workspace_id=workspace_id, user_id=workspace.owner_user_id)
    if previous is not None:
        previous.role = WorkspaceRole.ADMIN
    successor.role = WorkspaceRole.OWNER
    workspace.owner_user_id = member_user_id
    db.commit()
    return detail(db, workspace_id=workspace_id, user_id=user_id)


__all__ = [
    "Access",
    "CreateWorkspaceRequest",
    "CreatedInvite",
    "InviteRequest",
    "MemberSummary",
    "RoleRequest",
    "SeatLimitError",
    "UpdateWorkspaceRequest",
    "WorkspaceDetail",
    "WorkspaceMembership",
    "WorkspaceRequestError",
    "WorkspaceSummary",
    "accept_invite",
    "access",
    "active_access",
    "create_workspace",
    "delete_workspace",
    "detail",
    "invite_member",
    "list_memberships",
    "remove_member",
    "revoke_invite",
    "set_active",
    "set_role",
    "transfer_ownership",
    "update_workspace",
]
