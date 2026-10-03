"""The Google sign-in route, including the attempts it has to refuse.

The network and the identity token verification are stubbed: what is under test is the route's
own contract — state binding, what happens to an unverified email, which account the identity
lands on, and that none of it works when the deployment has no Google credentials.
"""

from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.terms import TERMS_VERSION
from app.models.user import AuthProvider, User
from app.services import google_oidc

CLIENT_ID = "test-client.apps.googleusercontent.com"


@pytest.fixture
def google_enabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A deployment with Google credentials configured, through the environment it reads."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("GOOGLE_REDIRECT_URL", "https://lab.askgrey.app/api/auth/google/callback")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://lab.askgrey.app")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _start(client: TestClient) -> tuple[str, str]:
    response = client.get("/api/auth/google/start", follow_redirects=False)
    assert response.status_code == 302, response.text
    query = parse_qs(urlparse(response.headers["location"]).query)
    cookie = client.cookies["askgrey_google_state"]
    state, _, nonce = cookie.partition(":")
    assert query["state"] == [state]
    assert query["nonce"] == [nonce]
    return state, nonce


def test_start_is_unavailable_without_credentials(client: TestClient) -> None:
    assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 404
    assert client.get("/api/auth/google/callback?code=x&state=y").status_code == 404


def test_sso_config_advertises_google_only_when_configured(client: TestClient) -> None:
    assert client.get("/api/auth/sso").json()["google_enabled"] is False


def test_placeholder_credentials_count_as_unconfigured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The value the infrastructure writes into a secret it cannot know yet is not a client."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "unset")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "unset")
    get_settings.cache_clear()
    try:
        assert client.get("/api/auth/sso").json()["google_enabled"] is False
        assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 404
    finally:
        get_settings.cache_clear()


def test_start_redirects_to_google_with_our_client_id(
    client: TestClient, google_enabled: None
) -> None:
    response = client.get("/api/auth/google/start", follow_redirects=False)
    location = urlparse(response.headers["location"])
    assert location.netloc == "accounts.google.com"
    query = parse_qs(location.query)
    assert query["client_id"] == [CLIENT_ID]
    assert query["response_type"] == ["code"]
    assert "openid" in query["scope"][0]
    assert client.get("/api/auth/sso").json()["google_enabled"] is True


def test_callback_signs_in_and_records_the_account(
    client: TestClient,
    engine: Engine,
    google_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, nonce = _start(client)
    seen: dict[str, str] = {}

    def fake_exchange(code: str, given_nonce: str) -> google_oidc.GoogleIdentity:
        seen.update(code=code, nonce=given_nonce)
        return google_oidc.GoogleIdentity(
            subject="google-sub-1", email="Ada@Lab.org", full_name="Ada Lab"
        )

    monkeypatch.setattr(google_oidc, "exchange_code", fake_exchange)
    response = client.get(
        f"/api/auth/google/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"] == "https://lab.askgrey.app/"
    assert "askgrey_refresh=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert seen == {"code": "auth-code", "nonce": nonce}

    with Session(engine) as db:
        user = db.query(User).one()
    assert user.email == "ada@lab.org"
    assert user.provider == AuthProvider.OIDC
    assert user.password_hash is None
    assert user.subject == "google-sub-1"
    # Continuing with Google accepts the published terms, and the record has to say which.
    assert user.terms_version
    assert user.terms_accepted_at is not None

    # The session the cookie carries is usable: a refresh returns an access token.
    assert client.post("/api/auth/refresh").status_code == 200


def test_callback_refuses_a_state_it_did_not_issue(
    client: TestClient, engine: Engine, google_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _start(client)
    monkeypatch.setattr(
        google_oidc,
        "exchange_code",
        lambda *_: pytest.fail("the code must not be exchanged on a state mismatch"),
    )

    response = client.get(
        "/api/auth/google/callback?code=auth-code&state=forged", follow_redirects=False
    )

    assert response.status_code == 302
    assert "sso_error" in response.headers["location"]
    assert "askgrey_refresh=" not in response.headers.get("set-cookie", "")
    with Session(engine) as db:
        assert db.query(User).count() == 0


def test_callback_reports_a_failed_exchange_on_the_sign_in_screen(
    client: TestClient, google_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = _start(client)

    def refuse(*_: object) -> google_oidc.GoogleIdentity:
        raise google_oidc.GoogleAuthError("Google has not verified that email address")

    monkeypatch.setattr(google_oidc, "exchange_code", refuse)
    response = client.get(
        f"/api/auth/google/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://lab.askgrey.app/login?")
    assert "has+not+verified" in location


def test_a_second_sign_in_reuses_the_same_account(
    client: TestClient, engine: Engine, google_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        google_oidc,
        "exchange_code",
        lambda *_: google_oidc.GoogleIdentity(
            subject="google-sub-1", email="ada@lab.org", full_name="Ada Lab"
        ),
    )
    for _ in range(2):
        state, _ = _start(client)
        assert (
            client.get(
                f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False
            ).status_code
            == 302
        )

    with Session(engine) as db:
        assert db.query(User).count() == 1


def test_an_email_changed_at_google_stays_the_same_account(
    client: TestClient, engine: Engine, google_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The subject is the identity; the address is a label that can change."""
    emails = iter(["ada@lab.org", "ada@newlab.org"])
    monkeypatch.setattr(
        google_oidc,
        "exchange_code",
        lambda *_: google_oidc.GoogleIdentity(
            subject="google-sub-1", email=next(emails), full_name="Ada Lab"
        ),
    )
    for _ in range(2):
        state, _ = _start(client)
        client.get(f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False)

    with Session(engine) as db:
        assert db.query(User).count() == 1


def test_a_verified_google_email_attaches_to_an_existing_password_account(
    client: TestClient, engine: Engine, google_enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post(
        "/api/auth/register",
        json={
            "email": "ada@lab.org",
            "password": "obsidian-workspace-1",
            "accepted_terms_version": TERMS_VERSION,
        },
    )
    monkeypatch.setattr(
        google_oidc,
        "exchange_code",
        lambda *_: google_oidc.GoogleIdentity(
            subject="google-sub-1", email="ada@lab.org", full_name="Ada Lab"
        ),
    )
    state, _ = _start(client)
    client.get(f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False)

    with Session(engine) as db:
        user = db.query(User).one()
    # Still signs in with its password too: taking that away would lock out an account whose
    # organisation later drops Google.
    assert user.password_hash is not None
    assert user.subject == "google-sub-1"


def test_identity_token_verification_requires_a_verified_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claims = {
        "sub": "google-sub-1",
        "email": "ada@lab.org",
        "email_verified": False,
        "nonce": "n",
    }
    monkeypatch.setattr(google_oidc, "_jwks", lambda: _StubJwks())
    monkeypatch.setattr(google_oidc.jwt, "decode", lambda *a, **k: claims)

    with pytest.raises(google_oidc.GoogleAuthError, match="not verified"):
        google_oidc.verify_id_token("token", "n")

    claims["email_verified"] = True
    claims["nonce"] = "other"
    with pytest.raises(google_oidc.GoogleAuthError, match="did not match"):
        google_oidc.verify_id_token("token", "n")

    claims["nonce"] = "n"
    identity = google_oidc.verify_id_token("token", "n")
    assert identity.email == "ada@lab.org"


class _StubJwks:
    def get_signing_key_from_jwt(self, _: str) -> object:
        class _Key:
            key = "stub"

        return _Key()
