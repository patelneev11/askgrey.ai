import base64

import pytest

from app.core.config import DEV_JWT_SECRET, Settings

# A deployed environment also has to name a real database, so these settings carry one; the
# database rules themselves are covered in test_db_config.py.
DEPLOYED_DATABASE = "postgresql://user:pw@db.internal/askgrey"
A_DOCUMENT_KEY = base64.b64encode(b"k" * 32).decode()


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
        environment="production",
        jwt_secret="x" * 48,
        database_url=DEPLOYED_DATABASE,
        document_encryption_key=A_DOCUMENT_KEY,
    )

    assert settings.environment == "production"


def test_development_may_derive_the_document_key_from_the_signing_secret() -> None:
    settings = Settings(environment="development")

    assert settings.document_encryption_scheme == "derived-from-jwt-secret"


def test_a_deployed_environment_refuses_to_derive_the_document_key() -> None:
    # Otherwise rotating JWT_SECRET — the first thing you rotate after a suspected token leak
    # — destroys every stored paper, and one secret covers both sessions and documents.
    with pytest.raises(ValueError, match="DOCUMENT_KMS_KEY_ID"):
        Settings(environment="production", jwt_secret="x" * 48, database_url=DEPLOYED_DATABASE)


def test_a_kms_key_satisfies_the_deployed_document_key_requirement() -> None:
    settings = Settings(
        environment="production",
        jwt_secret="x" * 48,
        database_url=DEPLOYED_DATABASE,
        document_kms_key_id="alias/askgrey-documents",
    )

    assert settings.document_encryption_scheme == "kms"


def test_a_local_key_reports_itself_as_the_scheme_in_use() -> None:
    settings = Settings(
        environment="production",
        jwt_secret="x" * 48,
        database_url=DEPLOYED_DATABASE,
        document_encryption_key=A_DOCUMENT_KEY,
    )

    assert settings.document_encryption_scheme == "local-key"


def test_kms_wins_when_both_keys_are_configured() -> None:
    # Both set is the migration state: new documents go to KMS while the local key still reads
    # the rows written before it.
    settings = Settings(
        environment="production",
        jwt_secret="x" * 48,
        database_url=DEPLOYED_DATABASE,
        document_encryption_key=A_DOCUMENT_KEY,
        document_kms_key_id="alias/askgrey-documents",
    )

    assert settings.document_encryption_scheme == "kms"
