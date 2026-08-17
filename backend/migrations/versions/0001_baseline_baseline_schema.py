"""baseline schema

The schema as it stood when migrations were introduced: users, refresh sessions and the two
Literature tables. Before this, tables were created by `Base.metadata.create_all` at
startup, so a database that predates Alembic already holds some or all of them — each table
is therefore created only if it is absent, which makes `alembic upgrade head` safe to run
against both a fresh database and one create_all built. Nothing here drops or rewrites
existing data.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-16 17:27:27.320894
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _existing_tables()

    if "users" not in existing:
        op.create_table(
            "users",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("full_name", sa.String(length=200), nullable=False),
            sa.Column("role", sa.Enum("OWNER", "ADMIN", "MEMBER", name="userrole"), nullable=False),
            sa.Column("provider", sa.Enum("PASSWORD", "OIDC", name="authprovider"), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=True),
            sa.Column("subject", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)
        op.create_index("ix_users_subject", "users", ["subject"], unique=False)

    if "refresh_sessions" not in existing:
        op.create_table(
            "refresh_sessions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("replaced_by_id", sa.String(length=36), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"])

    if "literature_workspaces" not in existing:
        op.create_table(
            "literature_workspaces",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("goal", sa.Text(), nullable=False),
            sa.Column("sources_json", sa.Text(), nullable=False),
            sa.Column("table_json", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id"),
        )

    if "literature_documents" not in existing:
        op.create_table(
            "literature_documents",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("document_id", sa.String(length=64), nullable=False),
            sa.Column("filename", sa.String(length=500), nullable=False),
            sa.Column("source_url", sa.String(length=2000), nullable=False),
            sa.Column("byte_size", sa.Integer(), nullable=False),
            # The paper's bytes, so a cited page can still be rendered after a reload.
            sa.Column("content", sa.LargeBinary(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "document_id", name="uq_literature_document"),
        )
        op.create_index("ix_literature_documents_user_id", "literature_documents", ["user_id"])
        op.create_index(
            "ix_literature_documents_document_id", "literature_documents", ["document_id"]
        )


def downgrade() -> None:
    for table in ("literature_documents", "literature_workspaces", "refresh_sessions", "users"):
        op.drop_table(table)
