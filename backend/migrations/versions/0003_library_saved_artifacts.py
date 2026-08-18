"""saved library of agent outputs

One table for every output a researcher explicitly keeps, keyed by kind, with the endpoint's own
response as the payload.

Revision ID: 0003_library
Revises: 0002_protocols
Create Date: 2026-08-16 01:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_library"
down_revision: str | None = "0002_protocols"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A development database still builds itself with `create_all`, so the table may already be
    # there; the baseline revision adopts such a database rather than failing on "table exists".
    if "saved_artifacts" in set(sa.inspect(op.get_bind()).get_table_names()):
        return

    op.create_table(
        "saved_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("subtitle", sa.String(length=500), nullable=False),
        # JSON text, not a JSON column: SQLite in tests, Postgres in production, and the payload
        # is only ever read back whole.
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_saved_artifacts_user_id", "saved_artifacts", ["user_id"])
    op.create_index("ix_saved_artifacts_kind", "saved_artifacts", ["kind"])


def downgrade() -> None:
    op.drop_table("saved_artifacts")
