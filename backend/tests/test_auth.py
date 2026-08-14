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


def test_register_returns_token_pair(client: TestClient) -> None:
    tokens = register(client)
    assert tokens["access_token"] and tokens["refresh_token"]
    assert tokens["token_type"] == "bearer"


def test_register_rejects_duplicate_email(client: TestClient) -> None:
    register(client)
    response = client.post("/api/auth/register", json=CREDENTIALS)
    assert response.status_code == 409


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


def test_refresh_token_cannot_be_used_as_access_token(client: TestClient) -> None:
    tokens = register(client)
    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    )
    assert response.status_code == 401


def test_refresh_issues_new_pair(client: TestClient) -> None:
    tokens = register(client)
    response = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_sso_disabled_by_default(client: TestClient) -> None:
    response = client.get("/api/auth/sso")
    assert response.status_code == 200
    assert response.json()["enabled"] is False
