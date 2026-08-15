from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status

from app.api.deps import ClientIp, CurrentUser, DbSession, throttle_account, throttle_auth
from app.core import audit
from app.core.config import get_settings
from app.core.security import create_token
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    SSOConfig,
    TokenResponse,
    UserRead,
)
from app.services import sessions as session_service
from app.services import users as user_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "askgrey_refresh"
# Scoped to the auth routes so the long-lived credential is not attached to every API call.
REFRESH_COOKIE_PATH = "/api/auth"

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]
Throttled = Annotated[None, Depends(throttle_auth)]


def _set_refresh_cookie(response: Response, token: str) -> None:
    """Store the refresh token where script cannot read it.

    HttpOnly removes it from XSS reach, SameSite=lax stops a cross-site page from silently
    driving /auth/refresh, and Secure is dropped only in local development where there is
    no TLS to attach it to.
    """
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        httponly=True,
        secure=settings.environment != "development",
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


def _sign_in(db: DbSession, response: Response, user_id: str) -> TokenResponse:
    _set_refresh_cookie(response, session_service.issue(db, user_id))
    return TokenResponse(access_token=create_token(user_id, "access"))


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    db: DbSession,
    response: Response,
    request: Request,
    ip: ClientIp,
    _throttled: Throttled,
) -> TokenResponse:
    throttle_account(payload.email, request)
    if user_service.get_by_email(db, payload.email) is not None:
        audit.record("auth.register", outcome="failure", actor=payload.email, client_ip=ip)
        # Deliberately not "email already registered": that is a membership oracle for any
        # address an attacker cares about. Fully closing it needs email verification, which
        # is a product change rather than a fix — see docs/security-review.md.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That account could not be created with those details"
        )
    user = user_service.create_user(db, payload.email, payload.password, payload.full_name)
    audit.record("auth.register", actor=user.id, client_ip=ip)
    return _sign_in(db, response, user.id)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    db: DbSession,
    response: Response,
    request: Request,
    ip: ClientIp,
    _throttled: Throttled,
) -> TokenResponse:
    throttle_account(payload.email, request)
    user = user_service.authenticate(db, payload.email, payload.password)
    if user is None:
        audit.record("auth.login", outcome="failure", actor=payload.email, client_ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    audit.record("auth.login", actor=user.id, client_ip=ip)
    return _sign_in(db, response, user.id)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    db: DbSession,
    response: Response,
    ip: ClientIp,
    _throttled: Throttled,
    refresh_token: RefreshCookie = None,
) -> TokenResponse:
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    if not refresh_token:
        raise invalid
    try:
        rotated = session_service.rotate(db, refresh_token)
    except session_service.RefreshReuseError as exc:
        # A spent token came back, so a copy exists somewhere. Every session for the account
        # is already revoked by the service; the client is signed out here.
        audit.record("auth.refresh_reuse", outcome="denied", actor=str(exc), client_ip=ip)
        _clear_refresh_cookie(response)
        raise invalid from exc
    if rotated is None:
        _clear_refresh_cookie(response)
        raise invalid
    user_id, replacement = rotated
    if user_service.get_by_id(db, user_id) is None:
        _clear_refresh_cookie(response)
        raise invalid
    audit.record("auth.refresh", actor=user_id, client_ip=ip)
    _set_refresh_cookie(response, replacement)
    return TokenResponse(access_token=create_token(user_id, "access"))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    db: DbSession,
    response: Response,
    ip: ClientIp,
    refresh_token: RefreshCookie = None,
) -> Response:
    if refresh_token:
        user_id = session_service.revoke(db, refresh_token)
        audit.record("auth.logout", actor=user_id, client_ip=ip)
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(db: DbSession, response: Response, ip: ClientIp, user: CurrentUser) -> Response:
    """Sign the account out everywhere — the lever to pull when a device is lost."""
    session_service.revoke_all(db, user.id)
    audit.record("auth.logout_all", actor=user.id, client_ip=ip)
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)


@router.get("/sso", response_model=SSOConfig)
def sso_config() -> SSOConfig:
    """Advertise the workspace SSO provider so the login screen can render the right entry point.

    The authorization code exchange itself lands with the tenant onboarding work; this endpoint
    exists so the frontend contract is stable beforehand.
    """
    settings = get_settings()
    if not settings.sso_enabled:
        return SSOConfig(enabled=False, issuer="")
    query = urlencode(
        {
            "client_id": settings.oidc_client_id,
            "redirect_uri": settings.oidc_redirect_url,
            "response_type": "code",
            "scope": "openid email profile",
        }
    )
    return SSOConfig(
        enabled=True,
        issuer=settings.oidc_issuer,
        authorize_url=f"{settings.oidc_issuer.rstrip('/')}/authorize?{query}",
    )
