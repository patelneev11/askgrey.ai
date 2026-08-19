from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.services.library import ArtifactKind

CREDENTIALS = {"email": "owner@askgrey.ai", "password": "obsidian-workspace-1"}
OTHER = {"email": "stranger@askgrey.ai", "password": "obsidian-workspace-2"}


def auth_header(client: TestClient, credentials: dict[str, str]) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=credentials).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def overview(client: TestClient, headers: dict[str, str]) -> dict[str, object]:
    response = client.get("/api/account/overview", headers=headers)
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


def test_the_overview_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/account/overview").status_code == 401


def test_it_reports_the_calling_account_s_own_identity(client: TestClient) -> None:
    body = overview(client, auth_header(client, CREDENTIALS))

    account = body["account"]
    assert isinstance(account, dict)
    assert account["email"] == CREDENTIALS["email"]
    assert account["provider"] == "password"


def test_a_fresh_account_stores_nothing_and_claims_nothing(client: TestClient) -> None:
    body = overview(client, auth_header(client, CREDENTIALS))

    assert body["storage"] == {
        "stored_papers": 0,
        "stored_bytes": 0,
        "retention_days": 90,
        # No paper stored means no expiry date, rather than a date with nothing behind it.
        "next_expiry": None,
    }
    saved = body["saved_work"]
    assert isinstance(saved, dict)
    assert saved == {"counts": {}, "total": 0, "last_saved_at": None}


def save_an_eligibility_artifact(client: TestClient, headers: dict[str, str]) -> None:
    ruling = client.post("/api/grants/eligibility", headers=headers, json={"profile": {}})
    assert ruling.status_code == 200, ruling.text
    saved = client.post(
        "/api/library",
        headers=headers,
        json={
            "kind": ArtifactKind.GRANTS_ELIGIBILITY.value,
            "title": "Phase I eligibility",
            "subtitle": "",
            "payload": ruling.json(),
        },
    )
    assert saved.status_code in (200, 201), saved.text


def test_saved_work_is_counted_per_tab(client: TestClient) -> None:
    headers = auth_header(client, CREDENTIALS)
    save_an_eligibility_artifact(client, headers)

    body = overview(client, headers)
    work = body["saved_work"]
    assert isinstance(work, dict)
    assert work["total"] == 1
    assert work["counts"] == {ArtifactKind.GRANTS_ELIGIBILITY.value: 1}
    assert work["last_saved_at"] is not None


def test_one_account_s_overview_never_counts_another_s_work(client: TestClient) -> None:
    owner = auth_header(client, CREDENTIALS)
    save_an_eligibility_artifact(client, owner)
    stranger = auth_header(client, OTHER)

    work = overview(client, stranger)["saved_work"]
    assert isinstance(work, dict)
    assert work["total"] == 0


def test_signing_in_twice_shows_two_live_sessions_and_signing_out_everywhere_ends_them(
    client: TestClient,
) -> None:
    headers = auth_header(client, CREDENTIALS)
    client.post("/api/auth/login", json=CREDENTIALS)

    sessions = overview(client, headers)["sessions"]
    assert isinstance(sessions, list)
    assert len(sessions) == 2

    assert client.post("/api/auth/logout-all", headers=headers).status_code == 204
    assert overview(client, headers)["sessions"] == []


def test_the_platform_section_reports_configuration_and_no_secret_value(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-not-a-real-key")

    body = overview(client, auth_header(client, CREDENTIALS))

    platform = body["platform"]
    assert isinstance(platform, dict)
    assert platform["environment"] == "development"
    assert platform["document_encryption"] == "derived-from-jwt-secret"
    # Whether a key exists, never the key: this response is rendered into a page.
    assert platform["extraction_available"] is True
    serialised = str(body)
    assert "sk-ant" not in serialised
    assert settings.jwt_secret not in serialised


def test_upstreams_say_when_a_key_is_missing_rather_than_showing_a_connection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "uspto_odp_api_key", "")

    body = overview(client, auth_header(client, CREDENTIALS))

    upstreams = body["upstreams"]
    assert isinstance(upstreams, list)
    by_name = {entry["name"]: entry for entry in upstreams if isinstance(entry, dict)}
    assert by_name["Anthropic"]["configured"] is False
    assert "No API key" in str(by_name["Anthropic"]["detail"])
    assert by_name["USPTO Open Data"]["configured"] is False
    assert by_name["PubChem"]["configured"] is True
