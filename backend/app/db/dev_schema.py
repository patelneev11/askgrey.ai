"""Bring a development database up to the schema the code expects.

Deployed environments migrate in their entrypoint, before the server starts. Development used to
call ``Base.metadata.create_all``, which creates missing *tables* but never adds a column to a
table that already exists — so pulling a migration that adds one left the developer with a
database the code could not query, surfacing as a 500 on the first request to touch it. Running
the migrations instead means a pull is enough, and the baseline adopts a database create_all
built rather than failing on tables that are already there.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

logger = logging.getLogger("askgrey.db")

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    """Alembic configured the way the CLI would be, from any working directory.

    The URL is deliberately absent here as it is in ``alembic.ini``: ``migrations/env.py`` reads
    it from the same Settings the app uses, so a migration run and the server cannot disagree
    about which database they are talking to.
    """
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    # This process already has its logging configured; alembic.ini's belongs to the CLI.
    config.attributes["configure_logging"] = False
    return config


def migrate_development_schema(engine: Engine) -> None:
    """Migrate the development database to head, creating it on first run."""
    existing = bool(inspect(engine).get_table_names())
    command.upgrade(alembic_config(), "head")
    # Not `created`: LogRecord owns that name, and overwriting it raises.
    logger.info("development schema migrated", extra={"database_created": not existing})
