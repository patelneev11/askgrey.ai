"""papers added inside a shared workspace

Adds a nullable workspace to the stored papers table. Nullable is what makes this safe on a live
database: every paper stored today keeps NULL and stays private to the account that added it, so
adopting workspaces does not retroactively hand anyone's uploads to their colleagues.

The foreign key is `ON DELETE SET NULL`, unlike the one on saved artifacts: a row here owns a copy
of a paper an account uploaded, so deleting the workspace has to give that copy back rather than
delete it.

Revision ID: 0008_shared_documents
Revises: 0007_workspaces
Create Date: 2026-08-13 21:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_shared_documents"
down_revision: str | None = "0007_workspaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "literature_documents"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "workspace_id" in {column["name"] for column in inspector.get_columns(_TABLE)}:
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column("workspace_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            f"fk_{_TABLE}_workspace_id",
            "workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(f"ix_{_TABLE}_workspace_id", _TABLE, ["workspace_id"])


def downgrade() -> None:
    op.drop_index(f"ix_{_TABLE}_workspace_id", table_name=_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(f"fk_{_TABLE}_workspace_id", type_="foreignkey")
        batch.drop_column("workspace_id")
