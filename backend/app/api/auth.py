from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.security import create_token, decode_token
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    SSOConfig,
    TokenPair,
    UserRead,
)
from app.services import users as user_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_tokens(user_id: str) -> TokenPair:
    return TokenPair(
        access_token=create_token(user_id, "access"),
        refresh_token=create_token(user_id, "refresh"),
    )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession) -> TokenPair:
    if user_service.get_by_email(db, payload.email) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered")
    user = user_service.create_user(db, payload.email, payload.password, payload.full_name)
    return _issue_tokens(user.id)


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, db: DbSession) -> TokenPair:
    user = user_service.authenticate(db, payload.email, payload.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return _issue_tokens(user.id)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: DbSession) -> TokenPair:
    user_id = decode_token(payload.refresh_token, expected_type="refresh")
    if user_id is None or user_service.get_by_id(db, user_id) is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    return _issue_tokens(user_id)


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
