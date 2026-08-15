from fastapi.testclient import TestClient

CREDENTIALS = {"email": "researcher@askgrey.ai", "password": "obsidian-workspace-1"}


def register(client: TestClient) -> dict[str, str]:
    response = client.post("/api/auth/register", json={**CREDENTIALS, "full_name": "Ada Lab"})
    assert response.status_code == 201, response.text
    return response.json()


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_register_returns_an_access_token_and_a_refresh_cookie(client: TestClient) -> None:
    response = client.post("/api/auth/register", json={**CREDENTIALS, "full_name": "Ada Lab"})

    assert response.json()["access_token"]
    assert response.json()["token_type"] == "bearer"
    # The long-lived credential must never be readable by script.
    assert "refresh_token" not in response.json()
    cookie = response.headers["set-cookie"]
    assert "askgrey_refresh=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/api/auth" in cookie


def test_register_rejects_duplicate_email_without_confirming_it_exists(
    client: TestClient,
) -> None:
    register(client)
    response = client.post("/api/auth/register", json=CREDENTIALS)
    assert response.status_code == 409
    assert "already" not in response.json()["detail"].lower()


def test_register_rejects_short_password(client: TestClient) -> None:
    response = client.post("/api/auth/register", json={"email": "a@b.co", "password": "short"})
    assert response.status_code == 422


def test_login_and_me(client: TestClient) -> None:
    register(client)
    tokens = client.post("/api/auth/login", json=CREDENTIALS).json()
    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == CREDENTIALS["email"]
    # First account bootstraps the workspace owner.
    assert body["role"] == "owner"


def test_login_rejects_bad_password(client: TestClient) -> None:
    register(client)
    response = client.post(
        "/api/auth/login", json={**CREDENTIALS, "password": "wrong-password-here"}
    )
    assert response.status_code == 401


def test_me_requires_token(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_a_refresh_token_cannot_be_used_as_an_access_token(client: TestClient) -> None:
    register(client)
    stolen = client.cookies["askgrey_refresh"]

    response = client.get("/api/auth/me", headers={"Authorization": f"Bearer {stolen}"})

    assert response.status_code == 401


def test_refresh_rotates_the_cookie(client: TestClient) -> None:
    register(client)
    original = client.cookies["askgrey_refresh"]

    response = client.post("/api/auth/refresh")

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert client.cookies["askgrey_refresh"] != original


def test_replaying_a_rotated_token_revokes_every_session(client: TestClient) -> None:
    register(client)
    spent = client.cookies["askgrey_refresh"]
    assert client.post("/api/auth/refresh").status_code == 200
    current = client.cookies["askgrey_refresh"]

    client.cookies.set("askgrey_refresh", spent)
    replayed = client.post("/api/auth/refresh")

    assert replayed.status_code == 401
    # The still-valid token is collateral: a copy is circulating, so the account is cut off.
    client.cookies.set("askgrey_refresh", current)
    assert client.post("/api/auth/refresh").status_code == 401


def test_logout_revokes_the_session(client: TestClient) -> None:
    register(client)
    token = client.cookies["askgrey_refresh"]

    assert client.post("/api/auth/logout").status_code == 204

    client.cookies.set("askgrey_refresh", token)
    assert client.post("/api/auth/refresh").status_code == 401


def test_logout_all_ends_sessions_created_elsewhere(client: TestClient) -> None:
    access = register(client)["access_token"]
    other_device = client.post("/api/auth/login", json=CREDENTIALS)
    elsewhere = other_device.cookies["askgrey_refresh"]

    response = client.post("/api/auth/logout-all", headers={"Authorization": f"Bearer {access}"})

    assert response.status_code == 204
    client.cookies.set("askgrey_refresh", elsewhere)
    assert client.post("/api/auth/refresh").status_code == 401


def test_refresh_without_a_cookie_is_rejected(client: TestClient) -> None:
    assert client.post("/api/auth/refresh").status_code == 401


def test_repeated_login_attempts_are_throttled(client: TestClient) -> None:
    register(client)
    wrong = {**CREDENTIALS, "password": "not-the-password"}
    attempts = [client.post("/api/auth/login", json=wrong).status_code for _ in range(12)]

    assert 401 in attempts
    assert attempts[-1] == 429


def test_sso_disabled_by_default(client: TestClient) -> None:
    response = client.get("/api/auth/sso")
    assert response.status_code == 200
    assert response.json()["enabled"] is False
