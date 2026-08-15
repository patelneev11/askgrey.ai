"""Server-side refresh sessions: rotation, reuse detection and revocation."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_token, decode_claims
from app.models.session import RefreshSession


class RefreshReuseError(Exception):
    """A refresh token was presented after it had already been rotated or revoked."""


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(moment: datetime) -> datetime:
    # SQLite hands back naive datetimes even for timezone-aware columns.
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def issue(db: Session, user_id: str) -> str:
    settings = get_settings()
    jti = str(uuid.uuid4())
    token = create_token(user_id, "refresh", jti=jti)
    db.add(
        RefreshSession(
            id=jti,
            user_id=user_id,
            token_hash=_digest(token),
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    db.commit()
    return token


def revoke_all(db: Session, user_id: str) -> None:
    db.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    db.commit()


def _lookup(db: Session, token: str) -> tuple[RefreshSession, str] | None:
    claims = decode_claims(token, "refresh")
    if claims is None:
        return None
    jti, subject = claims.get("jti"), claims.get("sub")
    if not isinstance(jti, str) or not isinstance(subject, str):
        return None
    record = db.get(RefreshSession, jti)
    # Constant-time compare keeps the stored hash from being probed a byte at a time.
    if record is None or not hmac.compare_digest(record.token_hash, _digest(token)):
        return None
    if record.user_id != subject:
        return None
    return record, subject


def rotate(db: Session, token: str) -> tuple[str, str] | None:
    """Exchange a refresh token for a fresh one, returning `(user_id, new_token)`.

    Returns None when the token is not recognised. Raises `RefreshReuseError` when the token
    is recognised but already spent: that means a copy is circulating, so every session for
    the account is revoked rather than just this one.
    """
    found = _lookup(db, token)
    if found is None:
        return None
    record, user_id = found
    if record.revoked_at is not None:
        revoke_all(db, user_id)
        raise RefreshReuseError(user_id)
    if _aware(record.expires_at) <= datetime.now(timezone.utc):
        return None

    replacement = issue(db, user_id)
    record.revoked_at = datetime.now(timezone.utc)
    replacement_claims = decode_claims(replacement, "refresh") or {}
    record.replaced_by_id = replacement_claims.get("jti")
    db.commit()
    return user_id, replacement


def revoke(db: Session, token: str) -> str | None:
    """Revoke a single session, returning the owning user id when the token was known."""
    found = _lookup(db, token)
    if found is None:
        return None
    record, user_id = found
    if record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return user_id


def active_count(db: Session, user_id: str) -> int:
    stmt = select(RefreshSession).where(
        RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None)
    )
    return len(db.execute(stmt).scalars().all())
