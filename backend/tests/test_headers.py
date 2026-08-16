import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.headers import API_CSP, APP_CSP, HSTS
from app.main import app

# A deployed environment refuses a SQLite file, so these settings name a managed database.
DEPLOYED_DATABASE = "postgresql://user:pw@db.internal/askgrey"


def test_every_response_carries_the_browser_enforced_headers(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    # Extraction tables and exports must not land in a shared cache.
    assert response.headers["Cache-Control"] == "no-store"


def test_development_does_not_pin_localhost_to_https(client: TestClient) -> None:
    assert "Strict-Transport-Security" not in client.get("/api/health").headers


def test_a_deployed_environment_sends_hsts(monkeypatch: pytest.MonkeyPatch) -> None:
    deployed = Settings(
        environment="production", jwt_secret="x" * 48, database_url=DEPLOYED_DATABASE
    )
    monkeypatch.setattr("app.core.headers.get_settings", lambda: deployed)

    with TestClient(app) as deployed_client:
        assert deployed_client.get("/api/health").headers["Strict-Transport-Security"] == HSTS


def test_the_api_forbids_loading_anything_at_all(client: TestClient) -> None:
    assert client.get("/api/health").headers["Content-Security-Policy"] == API_CSP


def test_non_api_responses_may_load_the_spa_bundle(client: TestClient) -> None:
    # `default-src 'none'` would block the app's own script and the pdf.js worker.
    policy = client.get("/some-client-route").headers["Content-Security-Policy"]

    assert policy == APP_CSP
    assert "worker-src 'self' blob:" in policy
    assert "frame-ancestors 'none'" in policy


def test_health_does_not_name_the_deployment(client: TestClient) -> None:
    # An unauthenticated caller learning which environment they reached is free
    # reconnaissance and buys the operator nothing.
    assert client.get("/api/health").json() == {"status": "ok"}


def test_the_default_cors_list_is_explicit() -> None:
    assert "*" not in get_settings().cors_origin_list


def test_a_deployed_environment_refuses_wildcard_cors() -> None:
    # Sessions ride on a cookie, so a wildcard origin would hand the API to any site.
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(
            environment="production",
            jwt_secret="x" * 48,
            database_url=DEPLOYED_DATABASE,
            cors_origins="*",
        )
