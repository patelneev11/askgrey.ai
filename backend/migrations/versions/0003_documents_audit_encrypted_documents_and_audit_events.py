"""encrypted stored documents with a retention date, and a queryable audit event log

Two things land here.

`literature_documents.expires_at` gives every stored paper a retention date, which the service
enforces on read and write. It is NOT NULL, and existing rows have no honest value to backfill:
their bytes are also plaintext, written before the column was encrypted, and this migration has
no key to seal them with. So the existing rows are deleted rather than migrated — every one is a
copy of a paper the user can add again, and keeping a plaintext row the reader would then fail
to decrypt would be worse than losing it. New rows are ciphertext (see app.core.crypto).

`audit_events` is the queryable half of the audit log, which until now was log lines only, so
the Audit Trails tab had nothing real to show.

Revision ID: 0003_documents_audit
Revises: 0002_protocols
Create Date: 2026-08-13 21:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_documents_audit"
down_revision: str | None = "0002_protocols"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()
    columns = {column["name"] for column in inspector.get_columns("literature_documents")}
    if "expires_at" not in columns:
        _add_retention_column()
    if "audit_events" not in set(inspector.get_table_names()):
        _create_audit_events()


def _add_retention_column() -> None:
    # Plaintext rows with no retention date; see the note above.
    op.execute(sa.text("DELETE FROM literature_documents"))
    op.add_column(
        "literature_documents",
        # The server default is what lets SQLite add a NOT NULL column at all, and it fails
        # safe: a row that somehow arrived without an explicit date is already expired, so it
        # is deleted on the next read rather than kept forever.
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def _create_audit_events() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        # Nullable on purpose: an event with no account (a sign-in for an address that does not
        # exist) is logged but is never served to a tenant.
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("event", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("client_ip", sa.String(length=64), nullable=False),
        # JSON text, like the protocol payloads: SQLite in tests, Postgres in production, and
        # the detail is only ever read back whole.
        sa.Column("detail_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    # Every read is "this user's newest events", and the pruner scans by date.
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_events")
    op.drop_column("literature_documents", "expires_at")
