"""saved protocols and their version history

The Protocol tab's tables landed on main after the baseline revision, from the era when
`Base.metadata.create_all` still built the schema at startup, so each table is created only
if it is absent.

Revision ID: 0002_protocols
Revises: 0001_baseline
Create Date: 2026-08-17 16:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_protocols"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _existing_tables()

    if "saved_protocols" not in existing:
        op.create_table(
            "saved_protocols",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("goal", sa.Text(), nullable=False),
            sa.Column("current_version", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_saved_protocols_user_id", "saved_protocols", ["user_id"])

    if "protocol_versions" not in existing:
        op.create_table(
            "protocol_versions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("protocol_id", sa.String(length=36), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            # JSON text, not a JSON column: SQLite in tests, Postgres in production, and the
            # payload is only ever read back whole.
            sa.Column("payload", sa.Text(), nullable=False),
            sa.Column("changes", sa.Text(), nullable=False),
            sa.Column("change_summary", sa.String(length=500), nullable=False),
            sa.Column("author_user_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["protocol_id"], ["saved_protocols.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("protocol_id", "version", name="uq_protocol_version"),
        )
        op.create_index("ix_protocol_versions_protocol_id", "protocol_versions", ["protocol_id"])


def downgrade() -> None:
    for table in ("protocol_versions", "saved_protocols"):
        op.drop_table(table)
