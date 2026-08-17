"""Operational endpoints: liveness for the uptime check, detail for whoever is on call."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import ThrottledUser, llm_budget
from app.core.config import get_settings
from app.core.dependency_health import KNOWN_PROVIDERS, ProviderSnapshot, health
from app.core.llm_cost import get_meter

router = APIRouter(prefix="/status", tags=["system"])


class DependencyStatus(BaseModel):
    provider: str
    status: str
    calls: int
    failures: int
    error_rate: float
    p95_latency_ms: float | None
    last_error: str | None
    last_error_age_seconds: float | None


class DependencyReport(BaseModel):
    status: str
    dependencies: list[DependencyStatus]


class CostReport(BaseModel):
    day: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    by_model: dict[str, float]
    alert_threshold_usd: float
    threshold_crossed: bool
    account_calls_remaining_today: int


def _to_model(snapshot: ProviderSnapshot) -> DependencyStatus:
    return DependencyStatus(**snapshot.__dict__)


@router.get("/dependencies", response_model=DependencyReport)
def dependencies(_user: ThrottledUser) -> DependencyReport:
    """Rolling health of every upstream API, so an incident starts with "whose fault is it?".

    Authenticated: the provider mix and error rates are an operational detail, and an
    unauthenticated version of this is a free map of the system for anyone scanning.
    """
    snapshots = health.snapshot(KNOWN_PROVIDERS)
    worst = "healthy"
    for snapshot in snapshots:
        if snapshot.status == "unhealthy":
            worst = "unhealthy"
            break
        if snapshot.status == "degraded":
            worst = "degraded"
    return DependencyReport(status=worst, dependencies=[_to_model(s) for s in snapshots])


class CapabilityReport(BaseModel):
    extraction_available: bool


@router.get("/capabilities", response_model=CapabilityReport)
def capabilities(_user: ThrottledUser) -> CapabilityReport:
    """Whether extraction can run at all.

    Without model credentials every extraction fails, but only after the user has uploaded a
    paper and written a goal. The UI asks first so it can say so up front instead.
    """
    return CapabilityReport(extraction_available=bool(get_settings().anthropic_api_key))


@router.get("/llm-cost", response_model=CostReport)
def llm_cost(user: ThrottledUser) -> CostReport:
    """Today's metered Claude spend, plus what this account has left of the call budget."""
    usage = get_meter().snapshot()
    settings = get_settings()
    return CostReport(
        day=usage.day.isoformat(),
        calls=usage.calls,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=usage.cost_usd,
        by_model=usage.by_model,
        alert_threshold_usd=settings.llm_daily_cost_alert_usd,
        threshold_crossed=usage.alerted,
        account_calls_remaining_today=llm_budget.remaining(str(user.id)),
    )
