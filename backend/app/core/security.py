from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

TokenType = Literal["access", "refresh"]

# bcrypt silently ignores input beyond 72 bytes, so passwords are bounded at the schema layer.
PASSWORD_MAX_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_token(subject: str, token_type: TokenType = "access") -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    if token_type == "access":
        expires = now + timedelta(minutes=settings.access_token_ttl_minutes)
    else:
        expires = now + timedelta(days=settings.refresh_token_ttl_days)
    claims: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: TokenType = "access") -> str | None:
    """Return the token subject, or None when the token is invalid or of the wrong type."""
    settings = get_settings()
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    if claims.get("type") != expected_type:
        return None
    subject = claims.get("sub")
    return subject if isinstance(subject, str) else None
