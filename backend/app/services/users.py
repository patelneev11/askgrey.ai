from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password, waste_a_password_comparison
from app.models.user import AuthProvider, User, UserRole


def get_by_email(db: Session, email: str) -> User | None:
    stmt = select(User).where(func.lower(User.email) == email.lower())
    return db.execute(stmt).scalar_one_or_none()


def get_by_id(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)


def count_users(db: Session) -> int:
    return db.execute(select(func.count()).select_from(User)).scalar_one()


def create_user(
    db: Session,
    email: str,
    password: str,
    full_name: str = "",
    terms_version: str | None = None,
) -> User:
    # The first account to register owns the workspace.
    role = UserRole.OWNER if count_users(db) == 0 else UserRole.MEMBER
    user = User(
        email=email.lower(),
        full_name=full_name,
        role=role,
        provider=AuthProvider.PASSWORD,
        password_hash=hash_password(password),
        terms_version=terms_version,
        # Stamped here rather than taken from the client: an acceptance time a browser can choose
        # is worth nothing as evidence.
        terms_accepted_at=datetime.now(timezone.utc) if terms_version else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def upsert_federated_user(
    db: Session,
    *,
    subject: str,
    email: str,
    full_name: str,
    terms_version: str | None = None,
) -> tuple[User, bool]:
    """Find or create the account behind a verified identity from an external provider.

    Returns the account and whether it was created. Matching is on the provider's subject first,
    so an account survives the user changing their address at the provider, and falls back to the
    email — only ever called with an address the provider has verified, which is what makes
    attaching to an existing password account safe. That existing account keeps its password:
    taking it away would lock out a researcher whose organisation later drops the provider.
    """
    by_subject = db.execute(
        select(User).where(User.provider == AuthProvider.OIDC, User.subject == subject)
    ).scalar_one_or_none()
    if by_subject is not None:
        if full_name and not by_subject.full_name:
            by_subject.full_name = full_name
            db.commit()
            db.refresh(by_subject)
        return by_subject, False

    existing = get_by_email(db, email)
    if existing is not None:
        if existing.subject is None:
            existing.subject = subject
            db.commit()
            db.refresh(existing)
        return existing, False

    role = UserRole.OWNER if count_users(db) == 0 else UserRole.MEMBER
    user = User(
        email=email.lower(),
        full_name=full_name,
        role=role,
        provider=AuthProvider.OIDC,
        password_hash=None,
        subject=subject,
        terms_version=terms_version,
        terms_accepted_at=datetime.now(timezone.utc) if terms_version else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, True


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = get_by_email(db, email)
    if user is None or user.password_hash is None:
        # Spend the same bcrypt work an existing account costs. Returning immediately answers an
        # unknown address in a millisecond and a known one in a hundred, which tells an attacker
        # which addresses hold accounts however carefully the error message is worded.
        waste_a_password_comparison(password)
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
