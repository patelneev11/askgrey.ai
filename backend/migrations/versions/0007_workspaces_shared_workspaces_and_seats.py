"""shared workspaces, seats and invitations

Adds the three workspace tables, the account's current workspace, and a nullable workspace on the
two kinds of saved work that can be shared. Nullable is what makes this safe to apply to a live
database: every row that exists today keeps NULL and stays private, so nothing a researcher saved
before workspaces existed becomes visible to anyone.

Revision ID: 0007_workspaces
Revises: 0006_llm_spend
Create Date: 2026-08-13 20:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_workspaces"
down_revision: str | None = "0006_llm_spend"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Text plus a check constraint rather than a native enum, matching the model: adding a role later
# would otherwise need an ALTER TYPE on Postgres. Spelled out here rather than imported from the
# model, so a later change to the enum cannot rewrite what this revision did.
_ROLE = sa.Enum(
    "viewer", "member", "admin", "owner", name="workspacerole", native_enum=False, length=16
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    if "workspaces" not in existing:
        op.create_table(
            "workspaces",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("owner_user_id", sa.String(length=36), nullable=False),
            sa.Column("seat_limit", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_workspaces_owner_user_id", "workspaces", ["owner_user_id"])

    if "workspace_members" not in existing:
        op.create_table(
            "workspace_members",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("role", _ROLE, nullable=False),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
        )
        op.create_index("ix_workspace_members_workspace_id", "workspace_members", ["workspace_id"])
        op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])

    if "workspace_invites" not in existing:
        op.create_table(
            "workspace_invites",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("role", _ROLE, nullable=False),
            # Only the hash: an invitation is a bearer credential, so a stolen database dump must
            # not contain anything that can be redeemed.
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("invited_by_user_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name="uq_workspace_invite_token"),
        )
        op.create_index("ix_workspace_invites_workspace_id", "workspace_invites", ["workspace_id"])
        op.create_index("ix_workspace_invites_email", "workspace_invites", ["email"])

    if "active_workspace_id" not in {column["name"] for column in inspector.get_columns("users")}:
        op.add_column(
            "users", sa.Column("active_workspace_id", sa.String(length=36), nullable=True)
        )

    for table in ("saved_artifacts", "saved_protocols"):
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "workspace_id" in columns:
            continue
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("workspace_id", sa.String(length=36), nullable=True))
            batch.create_foreign_key(
                f"fk_{table}_workspace_id",
                "workspaces",
                ["workspace_id"],
                ["id"],
                ondelete="CASCADE",
            )
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])


def downgrade() -> None:
    for table in ("saved_artifacts", "saved_protocols"):
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_workspace_id", type_="foreignkey")
            batch.drop_column("workspace_id")
    op.drop_column("users", "active_workspace_id")
    op.drop_table("workspace_invites")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
