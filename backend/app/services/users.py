from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.user import AuthProvider, User, UserRole


def get_by_email(db: Session, email: str) -> User | None:
    stmt = select(User).where(func.lower(User.email) == email.lower())
    return db.execute(stmt).scalar_one_or_none()


def get_by_id(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)


def count_users(db: Session) -> int:
    return db.execute(select(func.count()).select_from(User)).scalar_one()


def create_user(db: Session, email: str, password: str, full_name: str = "") -> User:
    # The first account to register owns the workspace.
    role = UserRole.OWNER if count_users(db) == 0 else UserRole.MEMBER
    user = User(
        email=email.lower(),
        full_name=full_name,
        role=role,
        provider=AuthProvider.PASSWORD,
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = get_by_email(db, email)
    if user is None or user.password_hash is None:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user
