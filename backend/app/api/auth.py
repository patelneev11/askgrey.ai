import secrets
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import ClientIp, CurrentUser, DbSession, throttle_account, throttle_auth
from app.core import audit
from app.core.config import get_settings
from app.core.security import create_token
from app.core.terms import TERMS_VERSION
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    SSOConfig,
    TermsInfo,
    TokenResponse,
    UserRead,
)
from app.services import google_oidc
from app.services import sessions as session_service
from app.services import users as user_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "askgrey_refresh"
# The state and nonce of an in-flight Google sign-in, held only for the length of the redirect.
GOOGLE_STATE_COOKIE = "askgrey_google_state"
GOOGLE_STATE_PATH = "/api/auth/google"
GOOGLE_STATE_TTL_SECONDS = 600
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


def _clear_refresh_cookie_headers() -> dict[str, str]:
    """The same deletion as `_clear_refresh_cookie`, as headers an HTTPException can carry.

    FastAPI only merges the injected `Response` into the reply when the endpoint returns; a
    raised exception is rendered into a fresh response, so a `Set-Cookie` written on the
    injected object is dropped. Failure paths must attach the header to the exception instead.
    """
    probe = Response()
    probe.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    return {"set-cookie": probe.headers["set-cookie"]}


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
    if payload.accepted_terms_version != TERMS_VERSION:
        # The client accepted wording that is no longer the published one, so what it showed the
        # researcher and what the record would claim they agreed to have diverged.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The terms of agreement have changed. Reload the page and read them again.",
        )
    user = user_service.create_user(
        db,
        payload.email,
        payload.password,
        payload.full_name,
        terms_version=payload.accepted_terms_version,
    )
    audit.record(
        "auth.register",
        actor=user.id,
        client_ip=ip,
        db=db,
        user_id=user.id,
        detail={"accepted_terms_version": payload.accepted_terms_version},
    )
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
    audit.record("auth.login", actor=user.id, client_ip=ip, db=db, user_id=user.id)
    return _sign_in(db, response, user.id)


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    db: DbSession,
    response: Response,
    ip: ClientIp,
    _throttled: Throttled,
    refresh_token: RefreshCookie = None,
) -> TokenResponse:
    invalid = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Invalid refresh token",
        headers=_clear_refresh_cookie_headers(),
    )
    if not refresh_token:
        raise invalid
    try:
        rotated = session_service.rotate(db, refresh_token)
    except session_service.RefreshReuseError as exc:
        # A spent token came back, so a copy exists somewhere. Every session for the account
        # is already revoked by the service; the client is signed out here.
        audit.record("auth.refresh_reuse", outcome="denied", actor=str(exc), client_ip=ip)
        raise invalid from exc
    if rotated is None:
        raise invalid
    user_id, replacement = rotated
    if user_service.get_by_id(db, user_id) is None:
        raise invalid
    audit.record("auth.refresh", actor=user_id, client_ip=ip, db=db, user_id=user_id)
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
        audit.record("auth.logout", actor=user_id, client_ip=ip, db=db, user_id=user_id)
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(db: DbSession, response: Response, ip: ClientIp, user: CurrentUser) -> Response:
    """Sign the account out everywhere — the lever to pull when a device is lost."""
    session_service.revoke_all(db, user.id)
    audit.record("auth.logout_all", actor=user.id, client_ip=ip, db=db, user_id=user.id)
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)


@router.get("/terms", response_model=TermsInfo)
def terms() -> TermsInfo:
    """The terms version a registration has to accept, read before any session exists."""
    return TermsInfo(version=TERMS_VERSION)


@router.get("/sso", response_model=SSOConfig)
def sso_config() -> SSOConfig:
    """Advertise the workspace SSO provider so the login screen can render the right entry point.

    The authorization code exchange itself lands with the tenant onboarding work; this endpoint
    exists so the frontend contract is stable beforehand.
    """
    settings = get_settings()
    if not settings.sso_enabled:
        return SSOConfig(enabled=False, issuer="", google_enabled=settings.google_sso_enabled)
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
        google_enabled=settings.google_sso_enabled,
    )


def _google_unconfigured() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Google sign-in is not configured")


def _app_url(path: str) -> str:
    return f"{get_settings().public_app_url.rstrip('/')}{path}"


@router.get("/google/start")
def google_start(ip: ClientIp, _throttled: Throttled) -> RedirectResponse:
    """Send the browser to Google, remembering what we must see come back.

    The state and nonce are kept in an HttpOnly cookie rather than server-side so that a sign-in
    survives the request landing on a different container, and the callback refuses anything that
    does not carry both.
    """
    settings = get_settings()
    if not settings.google_sso_enabled:
        raise _google_unconfigured()

    state = google_oidc.new_state()
    nonce = google_oidc.new_state()
    response = RedirectResponse(google_oidc.authorization_url(state, nonce), status_code=302)
    response.set_cookie(
        GOOGLE_STATE_COOKIE,
        f"{state}:{nonce}",
        max_age=GOOGLE_STATE_TTL_SECONDS,
        httponly=True,
        secure=settings.environment != "development",
        # Google's redirect back is a cross-site top-level navigation, which lax allows and
        # strict would drop, losing the state we are about to check.
        samesite="lax",
        path=GOOGLE_STATE_PATH,
    )
    audit.record("auth.google_start", actor="anonymous", client_ip=ip)
    return response


@router.get("/google/callback")
def google_callback(
    db: DbSession,
    ip: ClientIp,
    _throttled: Throttled,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    google_state: Annotated[str | None, Cookie(alias=GOOGLE_STATE_COOKIE)] = None,
) -> RedirectResponse:
    """Complete a Google sign-in and hand the browser back to the app signed in.

    Failures redirect to the sign-in screen with a reason rather than rendering an error page: the
    user is mid-navigation in a browser, not reading an API response.
    """
    settings = get_settings()
    if not settings.google_sso_enabled:
        raise _google_unconfigured()

    def failed(reason: str, message: str) -> RedirectResponse:
        audit.record(
            "auth.google_callback",
            outcome="failure",
            actor="anonymous",
            client_ip=ip,
            detail={"reason": reason},
        )
        redirect = RedirectResponse(
            _app_url(f"/login?{urlencode({'sso_error': message})}"), status_code=302
        )
        redirect.delete_cookie(GOOGLE_STATE_COOKIE, path=GOOGLE_STATE_PATH)
        return redirect

    if error:
        return failed("provider_error", "Google did not complete the sign-in")
    expected_state, _, nonce = (google_state or "").partition(":")
    if not code or not state or not expected_state or not nonce:
        return failed("missing_state", "That sign-in link has expired. Try again.")
    if not secrets.compare_digest(state, expected_state):
        return failed("state_mismatch", "That sign-in could not be verified. Try again.")

    try:
        identity = google_oidc.exchange_code(code, nonce)
    except google_oidc.GoogleAuthError as exc:
        return failed("exchange_failed", str(exc))

    user, created = user_service.upsert_federated_user(
        db,
        subject=identity.subject,
        email=identity.email,
        full_name=identity.full_name,
        # Continuing with Google accepts the published terms, which the button says in as many
        # words; recording the version is what makes that acceptance evidence.
        terms_version=TERMS_VERSION,
    )
    audit.record(
        "auth.google_callback",
        actor=user.id,
        client_ip=ip,
        db=db,
        user_id=user.id,
        detail={"created": created},
    )
    response = RedirectResponse(_app_url("/"), status_code=302)
    _set_refresh_cookie(response, session_service.issue(db, user.id))
    response.delete_cookie(GOOGLE_STATE_COOKIE, path=GOOGLE_STATE_PATH)
    return response
