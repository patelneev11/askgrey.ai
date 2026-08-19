"""What the Workspace and Settings tabs read: this account's real identity, usage and config."""

from fastapi import APIRouter

from app.api.deps import DbSession, ThrottledUser
from app.services import account as account_service
from app.services.account import AccountOverview

router = APIRouter(prefix="/account", tags=["account"])


@router.get("/overview", response_model=AccountOverview)
def overview(user: ThrottledUser, db: DbSession) -> AccountOverview:
    """This account's own facts.

    Scoped to the caller with no parameter for whose account to read, like the audit feed: the
    counts are of the caller's rows, and the platform section is deployment configuration that
    is already visible in the app's behaviour — never a secret's value.
    """
    return account_service.overview(db, user)
