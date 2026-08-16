"""The migrations must describe the same schema the models do, on a fresh or existing database.

These run Alembic for real against a temporary SQLite file, because the failure they exist to
catch — a model changed without a migration — is invisible to every other test: the rest of
the suite builds its schema with `create_all`, so it passes either way.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect

from app.models.base import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TABLES = {"users", "refresh_sessions", "literature_workspaces", "literature_documents"}


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    # env.py reads the URL from Settings, so the environment is how a test redirects it.
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    url = f"sqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("ENVIRONMENT", "development")
    # Settings is cached per process, and env.py builds its engine from a fresh instance.
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_engine(url)
    yield engine
    engine.dispose()
    get_settings.cache_clear()


def test_upgrade_builds_the_whole_schema_on_an_empty_database(database: Engine) -> None:
    command.upgrade(alembic_config(str(database.url)), "head")

    assert TABLES <= set(inspect(database).get_table_names())


def test_the_migrations_and_the_models_agree(database: Engine) -> None:
    command.upgrade(alembic_config(str(database.url)), "head")

    with database.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    # Anything here is a model change that never got a migration, which is a deploy that
    # boots against a schema missing the column it just started writing to.
    assert differences == []


def test_upgrading_a_database_create_all_already_built_is_a_no_op(database: Engine) -> None:
    # Every deployment that predates migrations has exactly this shape: the tables exist and
    # alembic_version does not. The baseline must adopt it rather than fail on "table exists".
    Base.metadata.create_all(bind=database)

    command.upgrade(alembic_config(str(database.url)), "head")

    tables = set(inspect(database).get_table_names())
    assert TABLES <= tables
    assert "alembic_version" in tables


def test_upgrade_is_idempotent(database: Engine) -> None:
    config = alembic_config(str(database.url))
    command.upgrade(config, "head")

    command.upgrade(config, "head")

    assert TABLES <= set(inspect(database).get_table_names())
