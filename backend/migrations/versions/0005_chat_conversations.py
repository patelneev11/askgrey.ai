"""chat conversations and messages

Two tables behind the AI chat tab: a thread per researcher, and the messages in it with the tool
steps that produced each answer.

Revision ID: 0005_chat
Revises: 0004_library
Create Date: 2026-08-19 21:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_chat"
down_revision: str | None = "0004_library"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A development database still builds itself with `create_all`, so the tables may already be
    # there; adopt such a database rather than failing on "table exists".
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "chat_conversations" not in existing:
        op.create_table(
            "chat_conversations",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_chat_conversations_user_id", "chat_conversations", ["user_id"])

    if "chat_messages" not in existing:
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("conversation_id", sa.String(length=36), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            # The tool trace as JSON text: summaries, citations and bounded payloads, read back
            # whole to rebuild the cards under an answer.
            sa.Column("trace", sa.Text(), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_conversations")
