"""Google sign-in: the authorization code exchange and the identity token check.

Google is handled on its own rather than through the generic `oidc_*` tenant settings because a
corporate tenant and "continue with Google" are different products: a tenant is configured per
customer, Google is configured once for the whole deployment.

Nothing here trusts the browser. The code is exchanged server-side with the client secret, the
returned identity token is verified against Google's published signing keys for our own client
id, and the email is only accepted when Google says it is verified — an unverified address would
let anyone who can set a Google profile email claim an existing askgrey account.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from app.core.config import get_settings

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
ISSUERS = ("https://accounts.google.com", "accounts.google.com")

SCOPES = "openid email profile"


class GoogleAuthError(Exception):
    """The exchange or the identity token failed. The message is safe to show a user."""


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    full_name: str


def new_state() -> str:
    """A value the callback must see come back, to bind the redirect to the request we started."""
    return secrets.token_urlsafe(32)


def authorization_url(state: str, nonce: str) -> str:
    settings = get_settings()
    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_url,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "nonce": nonce,
            # Ask every time rather than silently reusing whichever account the browser is
            # already signed into: shared machines are normal in a lab.
            "prompt": "select_account",
            "access_type": "online",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


# One client, so Google's signing keys are fetched and cached once rather than per sign-in.
_jwk_client: PyJWKClient | None = None


def _jwks() -> PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(JWKS_URL, cache_keys=True)
    return _jwk_client


def exchange_code(code: str, nonce: str) -> GoogleIdentity:
    """Trade an authorization code for a verified Google identity.

    Raises `GoogleAuthError` for anything that is not a usable, verified identity.
    """
    settings = get_settings()
    try:
        response = httpx.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_url,
                "grant_type": "authorization_code",
            },
            timeout=settings.google_timeout_seconds,
        )
    except httpx.HTTPError as exc:
        raise GoogleAuthError("Could not reach Google to complete sign-in") from exc

    if response.status_code != 200:
        # Google's body names the client misconfiguration (bad redirect_uri, wrong secret); it is
        # useful in the log and useless to the user, so it is not forwarded.
        raise GoogleAuthError("Google rejected the sign-in attempt")

    id_token = response.json().get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise GoogleAuthError("Google did not return an identity token")

    return verify_id_token(id_token, nonce)


def verify_id_token(id_token: str, nonce: str) -> GoogleIdentity:
    settings = get_settings()
    try:
        key = _jwks().get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=list(ISSUERS),
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )
    except Exception as exc:  # noqa: BLE001 - any verification failure is the same refusal
        raise GoogleAuthError("Google's identity token could not be verified") from exc

    if claims.get("nonce") != nonce:
        # Without this an identity token captured from another sign-in could be replayed here.
        raise GoogleAuthError("Google's identity token did not match this sign-in attempt")

    email = claims.get("email")
    if not isinstance(email, str) or not email:
        raise GoogleAuthError("Google did not share an email address")
    if claims.get("email_verified") is not True:
        raise GoogleAuthError("Google has not verified that email address")

    name = claims.get("name")
    return GoogleIdentity(
        subject=str(claims["sub"]),
        email=email.lower(),
        full_name=name if isinstance(name, str) else "",
    )
