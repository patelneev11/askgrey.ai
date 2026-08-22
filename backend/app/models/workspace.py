import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WorkspaceRole(str, Enum):
    """What a member may do with the workspace's shared work.

    Ordered least to most: `rank` compares them, so a check reads as a floor rather than a set
    of roles that has to be updated every time a role is added.
    """

    __str__ = str.__str__

    VIEWER = "viewer"
    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"

    @property
    def rank(self) -> int:
        return _RANKS[self]

    def at_least(self, floor: "WorkspaceRole") -> bool:
        return self.rank >= floor.rank


_RANKS = {
    WorkspaceRole.VIEWER: 0,
    WorkspaceRole.MEMBER: 1,
    WorkspaceRole.ADMIN: 2,
    WorkspaceRole.OWNER: 3,
}


# Stored as text with a check constraint rather than a native database enum: adding a role later
# would otherwise need an ALTER TYPE on Postgres, and two columns sharing one named type make the
# migration order matter for nothing.
ROLE_COLUMN_TYPE = SAEnum(WorkspaceRole, name="workspacerole", native_enum=False, length=16)


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Workspace(Base):
    """
    A group of accounts that share saved work.

    A workspace shares findings — extraction tables, drafts, budgets, protocols — and not stored
    papers: a paper's ciphertext is bound to one account through its KMS encryption context and
    carries that account's retention clock, so sharing bytes is a separate decision with a
    licensing question attached.
    """

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Kept alongside the owner membership row so a workspace always names one account that
    # cannot be removed from it, even if the membership table is edited by hand.
    owner_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Members plus pending invites. Not a billing plan: nothing charges for a seat.
    seat_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WorkspaceMember(Base):
    """One account's place in one workspace."""

    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        ROLE_COLUMN_TYPE, nullable=False, default=WorkspaceRole.MEMBER
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WorkspaceInvite(Base):
    """
    An outstanding invitation, addressed to an email and redeemable once.

    There is no mail server, so the token is shown to the inviter once and handed over out of
    band. Only its hash is stored: a database read cannot be replayed into workspace access.
    """

    __tablename__ = "workspace_invites"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_workspace_invite_token"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    role: Mapped[WorkspaceRole] = mapped_column(
        ROLE_COLUMN_TYPE, nullable=False, default=WorkspaceRole.MEMBER
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    invited_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
