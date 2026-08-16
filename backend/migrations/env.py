"""Alembic entry point.

The URL comes from the application's own Settings rather than alembic.ini, so a migration
run and the server can never disagree about which database they are talking to, and no
credential has to be written into a tracked file.
"""

from logging.config import fileConfig

from alembic import context

from app.core.config import get_settings
from app.db.session import create_app_engine
from app.models.base import Base

# Importing the models is what puts the tables on Base.metadata; autogenerate compares
# against this, so a model that is not imported here looks like a table to drop.
from app.models.literature import LiteratureDocument, LiteratureWorkspace  # noqa: F401
from app.models.session import RefreshSession  # noqa: F401
from app.models.user import User  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().sqlalchemy_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_app_engine(get_settings())
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            # SQLite cannot ALTER a column in place, so a future column change needs the
            # copy-and-move batch mode; enabling it here keeps migrations dialect-agnostic.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
