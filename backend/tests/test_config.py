import pytest

from app.core.config import DEV_JWT_SECRET, Settings

# A deployed environment also has to name a real database, so these settings carry one; the
# database rules themselves are covered in test_db_config.py.
DEPLOYED_DATABASE = "postgresql://user:pw@db.internal/askgrey"


def test_development_may_keep_the_shipped_secret() -> None:
    settings = Settings(environment="development", jwt_secret=DEV_JWT_SECRET)

    assert settings.jwt_secret == DEV_JWT_SECRET


@pytest.mark.parametrize(
    "secret",
    [DEV_JWT_SECRET, "change-me-in-every-deployed-environment", "short-but-custom"],
)
def test_a_deployed_environment_refuses_a_guessable_signing_key(secret: str) -> None:
    # Anyone who knows the key can mint an access token for any user id, so the process
    # must fail to boot rather than serve requests it cannot authenticate.
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(environment="production", jwt_secret=secret, database_url=DEPLOYED_DATABASE)


def test_a_deployed_environment_accepts_a_real_secret() -> None:
    settings = Settings(
        environment="production", jwt_secret="x" * 48, database_url=DEPLOYED_DATABASE
    )

    assert settings.environment == "production"
