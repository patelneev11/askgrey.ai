from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
import jwt
from jwt import InvalidTokenError

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


# A hash of a value nothing can present, compared against when there is no account to check so
# that both answers cost the same bcrypt work. Minted once per process: generating it per call
# would be a second bcrypt round and make the unknown-address path the slower one.
_ABSENT_ACCOUNT_HASH = hash_password("no account holds this password")


def waste_a_password_comparison(password: str) -> None:
    """Spend one password verification whose result is discarded, to level response time."""
    verify_password(password, _ABSENT_ACCOUNT_HASH)


def create_token(subject: str, token_type: TokenType = "access", *, jti: str | None = None) -> str:
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
    if jti is not None:
        claims["jti"] = jti
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_claims(token: str, expected_type: TokenType = "access") -> dict[str, Any] | None:
    """Return the verified claims, or None when the token is invalid or of the wrong type."""
    settings = get_settings()
    try:
        claims: dict[str, Any] = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except InvalidTokenError:
        return None
    if claims.get("type") != expected_type:
        return None
    return claims


def decode_token(token: str, expected_type: TokenType = "access") -> str | None:
    """Return the token subject, or None when the token is invalid or of the wrong type."""
    claims = decode_claims(token, expected_type)
    if claims is None:
        return None
    subject = claims.get("sub")
    return subject if isinstance(subject, str) else None
