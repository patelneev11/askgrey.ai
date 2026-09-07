"""Development startup must migrate the database it finds, not only create missing tables.

The failure this covers is what a developer sees after pulling a migration that adds a column:
the table already exists, so `create_all` left it alone, and the first request touching the new
column returned a 500 (`no such column: users.terms_version`).
"""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, inspect

from app.db.dev_schema import alembic_config, migrate_development_schema

PREVIOUS_REVISION = "0008_shared_documents"
COLUMN_ADDED_SINCE = "terms_version"


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    url = f"sqlite:///{tmp_path / 'dev.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("ENVIRONMENT", "development")
    # Settings is cached per process, and migrations/env.py builds its engine from a fresh one.
    from app.core.config import get_settings

    get_settings.cache_clear()
    engine = create_engine(url)
    yield engine
    engine.dispose()
    get_settings.cache_clear()


def user_columns(engine: Engine) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns("users")}


def test_it_creates_the_schema_when_there_is_no_database_yet(database: Engine) -> None:
    migrate_development_schema(database)

    assert COLUMN_ADDED_SINCE in user_columns(database)


def test_it_adds_columns_a_pull_introduced_to_an_existing_database(database: Engine) -> None:
    command.upgrade(alembic_config(), PREVIOUS_REVISION)
    assert COLUMN_ADDED_SINCE not in user_columns(database)

    migrate_development_schema(database)

    assert COLUMN_ADDED_SINCE in user_columns(database)


def test_starting_twice_over_the_same_database_is_a_no_op(database: Engine) -> None:
    migrate_development_schema(database)

    migrate_development_schema(database)

    assert COLUMN_ADDED_SINCE in user_columns(database)


def test_it_leaves_the_process_logging_alone(
    database: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    """alembic.ini's logging is the CLI's: applied here it would disable the audit logger,
    and silence the line below — which is how a bad `extra` key went unnoticed."""
    audit = logging.getLogger("askgrey.audit")

    with caplog.at_level(logging.INFO, logger="askgrey.db"):
        migrate_development_schema(database)

    assert not audit.disabled
    assert audit.isEnabledFor(logging.INFO)
    assert "development schema migrated" in caplog.text
