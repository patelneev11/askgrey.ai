"""which terms of agreement an account accepted, and when

Both columns are nullable, which is what makes this safe on a live database: accounts that
registered before the terms existed keep NULL rather than being backfilled into having agreed to
wording they never saw.

Revision ID: 0009_terms_acceptance
Revises: 0008_shared_documents
Create Date: 2026-09-06 17:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_terms_acceptance"
down_revision: str | None = "0008_shared_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns(_TABLE)}
    with op.batch_alter_table(_TABLE) as batch:
        if "terms_version" not in existing:
            batch.add_column(sa.Column("terms_version", sa.String(length=32), nullable=True))
        if "terms_accepted_at" not in existing:
            batch.add_column(
                sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True)
            )


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column("terms_accepted_at")
        batch.drop_column("terms_version")
