"""What an unauthenticated scanner can learn from, or reach on, a deployed instance."""

from fastapi.testclient import TestClient

from app.core.headers import PERMISSIONS_POLICY
from app.main import app, docs_path


def test_a_deployment_publishes_no_schema() -> None:
    # The OpenAPI document names every route, its body shape and its auth, which is a map for
    # anyone probing the deployment.
    assert docs_path("/openapi.json", "production") is None
    assert docs_path("/docs", "staging") is None


def test_development_keeps_the_interactive_docs() -> None:
    assert docs_path("/docs", "development") == "/docs"
    assert app.docs_url == "/docs"  # tests run as development


def test_responses_carry_the_opt_out_browser_policies(client: TestClient) -> None:
    headers = client.get("/api/health").headers

    assert headers["Permissions-Policy"] == PERMISSIONS_POLICY
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert headers["Cross-Origin-Resource-Policy"] == "same-origin"


def test_preflight_offers_no_more_than_the_app_sends(client: TestClient) -> None:
    origin = "http://localhost:5173"
    response = client.options(
        "/api/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    allowed = response.headers.get("access-control-allow-methods", "")
    assert "*" not in allowed
    assert "TRACE" not in allowed
    assert "*" not in response.headers.get("access-control-allow-headers", "")


def test_an_unknown_header_is_refused_at_preflight(client: TestClient) -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-admin-override",
        },
    )

    assert response.status_code == 400
    assert "x-admin-override" not in response.headers.get("access-control-allow-headers", "")
