from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.dependency_health import health
from app.core.llm_cost import get_meter

CREDENTIALS = {
    "email": "ops@askgrey.dev",
    "password": "an-operator-passphrase",
    "full_name": "Ops Engineer",
}


@pytest.fixture(autouse=True)
def clean_counters() -> Iterator[None]:
    health.reset()
    get_meter().reset()
    yield
    health.reset()
    get_meter().reset()


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_liveness_stays_public_so_an_uptime_monitor_can_reach_it(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_operational_detail_is_not_free_reconnaissance(client: TestClient) -> None:
    assert client.get("/api/status/dependencies").status_code == 401
    assert client.get("/api/status/llm-cost").status_code == 401
    assert client.get("/api/status/capabilities").status_code == 401


def test_capabilities_report_whether_extraction_can_run_at_all(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = auth_header(client)
    settings = get_settings()

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert client.get("/api/status/capabilities", headers=headers).json() == {
        "extraction_available": False
    }

    monkeypatch.setattr(settings, "anthropic_api_key", "a-key")
    assert client.get("/api/status/capabilities", headers=headers).json() == {
        "extraction_available": True
    }


def test_capabilities_do_not_leak_the_key_itself(client: TestClient) -> None:
    body = client.get("/api/status/capabilities", headers=auth_header(client)).json()

    assert set(body) == {"extraction_available"}


def test_every_known_dependency_is_listed_even_before_it_is_called(client: TestClient) -> None:
    body = client.get("/api/status/dependencies", headers=auth_header(client)).json()

    assert body["status"] == "healthy"
    listed = {row["provider"]: row for row in body["dependencies"]}
    assert {"pubmed", "pubchem", "clinicaltrials", "grants_gov", "sbir", "anthropic"} <= set(listed)
    assert listed["pubmed"]["status"] == "unused"


def test_a_failing_dependency_drags_the_overall_status_down(client: TestClient) -> None:
    headers = auth_header(client)
    for _ in range(10):
        health.record("pubmed", ok=False, duration_ms=20, error="HTTP 503")

    body = client.get("/api/status/dependencies", headers=headers).json()

    assert body["status"] == "unhealthy"
    pubmed = next(row for row in body["dependencies"] if row["provider"] == "pubmed")
    assert pubmed["error_rate"] == 1.0
    assert pubmed["last_error"] == "HTTP 503"


def test_the_cost_endpoint_reports_todays_spend_and_the_remaining_call_budget(
    client: TestClient,
) -> None:
    headers = auth_header(client)
    get_meter().record(
        model="claude-sonnet-4-5", input_tokens=1_000_000, output_tokens=0, purpose="pdf_extraction"
    )

    body = client.get("/api/status/llm-cost", headers=headers).json()

    assert body["calls"] == 1
    assert body["input_tokens"] == 1_000_000
    assert body["cost_usd"] == pytest.approx(3.0)
    assert body["by_model"]["claude-sonnet-4-5"] == pytest.approx(3.0)
    assert body["alert_threshold_usd"] > 0
    assert body["threshold_crossed"] is False
    assert body["account_calls_remaining_today"] > 0
