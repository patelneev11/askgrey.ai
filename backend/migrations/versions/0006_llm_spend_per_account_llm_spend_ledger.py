"""per-account LLM spend ledger

Backs the assistant's dollar caps. The in-process cost meter is a deployment-wide alert that
forgets everything on restart, so a cap enforced from it would reset with the process and would
not be shared between replicas; this table is the durable per-account total.

Revision ID: 0006_llm_spend
Revises: 0005_chat
Create Date: 2026-08-13 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_llm_spend"
down_revision: str | None = "0005_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A development database still builds itself with `create_all`, so adopt an existing table
    # rather than failing on "table exists".
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "llm_spend" in existing:
        return
    op.create_table(
        "llm_spend",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "day", "purpose", name="uq_llm_spend_scope"),
    )
    op.create_index("ix_llm_spend_user_id", "llm_spend", ["user_id"])
    op.create_index("ix_llm_spend_day", "llm_spend", ["day"])


def downgrade() -> None:
    op.drop_table("llm_spend")
