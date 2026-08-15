from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.security import PASSWORD_MAX_BYTES
from app.models.user import AuthProvider, UserRole


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=PASSWORD_MAX_BYTES)
    full_name: str = Field(default="", max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Only the short-lived access token reaches script; the refresh token rides in an
    HttpOnly cookie so an XSS payload cannot read a 14-day credential out of the page."""

    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: EmailStr
    full_name: str
    role: UserRole
    provider: AuthProvider
    created_at: datetime


class SSOConfig(BaseModel):
    enabled: bool
    issuer: str
    authorize_url: str | None = None
