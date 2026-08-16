from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core import audit
from app.core.config import get_settings
from app.core.ratelimit import DailyBudget, SlidingWindowLimiter
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User
from app.services import users as user_service

bearer_scheme = HTTPBearer(auto_error=False)

_settings = get_settings()

# Module-level so the windows survive across requests. Anonymous auth traffic is limited by
# source address; everything else by account, since the account is the thing that spends money.
auth_ip_limiter = SlidingWindowLimiter(_settings.auth_rate_limit_per_minute, 60.0)
auth_account_limiter = SlidingWindowLimiter(_settings.auth_account_rate_limit_per_hour, 3600.0)
api_limiter = SlidingWindowLimiter(_settings.api_rate_limit_per_minute, 60.0)
llm_limiter = SlidingWindowLimiter(_settings.llm_rate_limit_per_minute, 60.0)
# Per-account limits alone are only as strong as the cost of an account, so the expensive
# endpoints are also capped by source address: one host cannot register its way around them.
llm_ip_limiter = SlidingWindowLimiter(_settings.llm_ip_rate_limit_per_minute, 60.0)
llm_budget = DailyBudget(_settings.llm_daily_call_budget)

DbSession = Annotated[Session, Depends(get_db)]
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


def get_current_user(db: DbSession, credentials: Credentials) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    user_id = decode_token(credentials.credentials, expected_type="access")
    if user_id is None:
        raise unauthorized
    user = user_service.get_by_id(db, user_id)
    if user is None:
        raise unauthorized
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _enforce(
    limiter: SlidingWindowLimiter,
    key: str,
    *,
    event: str,
    actor: str | None,
    ip: str,
) -> None:
    if not get_settings().rate_limit_enabled:
        return
    retry_after = limiter.retry_after(key)
    if retry_after is None:
        return
    audit.record(
        "rate_limit.blocked", outcome="denied", actor=actor, client_ip=ip, detail={"scope": event}
    )
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="too many requests; slow down and retry shortly",
        headers={"Retry-After": str(max(1, int(retry_after) + 1))},
    )


def throttle_auth(request: Request) -> None:
    """Per-source-address limit on the unauthenticated auth endpoints."""
    ip = client_ip(request)
    _enforce(auth_ip_limiter, f"{request.url.path}:{ip}", event="auth", actor=None, ip=ip)


def throttle_account(email: str, request: Request) -> None:
    """Per-account limit, so a distributed attacker still cannot grind one mailbox."""
    ip = client_ip(request)
    _enforce(auth_account_limiter, email.strip().lower(), event="auth.account", actor=email, ip=ip)


def throttle_api(request: Request, user: CurrentUser) -> User:
    ip = client_ip(request)
    _enforce(api_limiter, str(user.id), event="api", actor=str(user.id), ip=ip)
    return user


def throttle_llm(request: Request, user: CurrentUser) -> User:
    """Rate limit plus a daily ceiling on calls that spend money at Anthropic."""
    ip = client_ip(request)
    actor = str(user.id)
    _enforce(api_limiter, actor, event="api", actor=actor, ip=ip)
    _enforce(llm_limiter, actor, event="llm", actor=actor, ip=ip)
    _enforce(llm_ip_limiter, ip, event="llm.ip", actor=actor, ip=ip)
    if get_settings().rate_limit_enabled and not llm_budget.consume(actor):
        audit.record("llm.budget_exhausted", outcome="denied", actor=actor, client_ip=ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="daily analysis budget for this account is used up; it resets at 00:00 UTC",
        )
    return user


ThrottledUser = Annotated[User, Depends(throttle_api)]
LlmUser = Annotated[User, Depends(throttle_llm)]
ClientIp = Annotated[str, Depends(client_ip)]
