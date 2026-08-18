"""What the process does with the database URL it is handed."""

import base64

import pytest

from app.core.config import Settings
from app.db.session import engine_options

# A deployed environment also has to own the key its stored papers are readable under, which
# is asserted in test_config.py; these settings carry one so the database rules can be read
# on their own.
DEPLOYED = {
    "environment": "production",
    "jwt_secret": "x" * 48,
    "document_encryption_key": base64.b64encode(b"k" * 32).decode(),
}


def test_development_keeps_the_file_backed_sqlite_default() -> None:
    assert Settings(environment="development").sqlalchemy_url.startswith("sqlite")


@pytest.mark.parametrize(
    "url",
    ["sqlite:///./askgrey.db", "sqlite:////var/data/askgrey.db"],
)
def test_a_deployed_environment_refuses_a_sqlite_file(url: str) -> None:
    # The container filesystem is replaced on every deploy and is not shared between
    # replicas, so this URL is silent data loss rather than a slow database.
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(**DEPLOYED, database_url=url)


def test_a_deployed_environment_accepts_a_managed_database() -> None:
    settings = Settings(**DEPLOYED, database_url="postgresql://user:pw@db.internal:5432/askgrey")

    assert settings.environment == "production"


@pytest.mark.parametrize(
    "url",
    [
        "postgres://user:pw@db.internal:5432/askgrey",
        "postgresql://user:pw@db.internal:5432/askgrey",
    ],
)
def test_a_providers_postgres_url_is_rewritten_onto_the_installed_driver(url: str) -> None:
    # Both schemes resolve to psycopg2, which is not installed; the rewrite is what lets a
    # deployment paste the provider's URL unchanged.
    settings = Settings(**DEPLOYED, database_url=url)

    assert settings.sqlalchemy_url == "postgresql+psycopg://user:pw@db.internal:5432/askgrey"
    assert settings.database_url == url


def test_an_explicit_driver_is_left_alone() -> None:
    url = "postgresql+psycopg://user:pw@db.internal/askgrey"

    assert Settings(**DEPLOYED, database_url=url).sqlalchemy_url == url


def test_sqlite_gets_the_thread_check_waived_and_no_pool_sizing() -> None:
    options = engine_options("sqlite:///./askgrey.db", Settings(environment="development"))

    assert options == {"connect_args": {"check_same_thread": False}}


def test_a_network_database_gets_a_bounded_recycled_pool() -> None:
    settings = Settings(**DEPLOYED, database_url="postgresql+psycopg://u@h/db", db_pool_size=3)

    options = engine_options(settings.sqlalchemy_url, settings)

    assert options["pool_size"] == 3
    assert options["pool_pre_ping"] is True
    # Recycling inside the far end's idle timeout is what stops a checked-out connection
    # from being one the server already closed.
    assert options["pool_recycle"] == settings.db_pool_recycle_seconds
    assert "connect_args" not in options
