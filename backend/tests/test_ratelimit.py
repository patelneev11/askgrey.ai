from datetime import date

from fastapi.testclient import TestClient

from app.api import deps
from app.core.ratelimit import DailyBudget, SlidingWindowLimiter


def test_the_window_allows_the_limit_then_refuses() -> None:
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60.0)

    assert limiter.retry_after("a", now=0.0) is None
    assert limiter.retry_after("a", now=1.0) is None
    retry = limiter.retry_after("a", now=2.0)

    assert retry is not None and 0 < retry <= 60


def test_keys_do_not_share_a_window() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60.0)

    assert limiter.retry_after("a", now=0.0) is None
    assert limiter.retry_after("b", now=0.0) is None


def test_the_window_slides() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60.0)

    assert limiter.retry_after("a", now=0.0) is None
    assert limiter.retry_after("a", now=30.0) is not None
    assert limiter.retry_after("a", now=61.0) is None


def test_the_budget_stops_at_the_ceiling_and_resets_the_next_day() -> None:
    budget = DailyBudget(limit=2)

    assert budget.consume("user", today=date(2026, 8, 13)) is True
    assert budget.consume("user", today=date(2026, 8, 13)) is True
    assert budget.consume("user", today=date(2026, 8, 13)) is False
    assert budget.remaining("user") == 0
    assert budget.consume("user", today=date(2026, 8, 14)) is True


def _register(client: TestClient) -> str:
    response = client.post(
        "/api/auth/register",
        json={"email": "rate@example.com", "password": "correct horse battery", "full_name": "R"},
    )
    assert response.status_code == 201
    token: str = response.json()["access_token"]
    return token


def test_an_authenticated_caller_is_throttled_with_retry_after(client: TestClient) -> None:
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    deps.api_limiter.limit = 2
    try:
        first = [client.post("/api/export/csv", json=_TABLE, headers=headers) for _ in range(2)]
        blocked = client.post("/api/export/csv", json=_TABLE, headers=headers)
    finally:
        deps.api_limiter.limit = deps._settings.api_rate_limit_per_minute

    assert [response.status_code for response in first] == [200, 200]
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_the_daily_llm_budget_is_enforced_before_the_model_is_called(client: TestClient) -> None:
    token = _register(client)
    headers = {"Authorization": f"Bearer {token}"}
    deps.llm_budget.limit = 0
    try:
        response = client.post(
            "/api/pdf-extraction/url",
            json={"url": "https://example.org/paper.pdf", "goal": "sample size"},
            headers=headers,
        )
    finally:
        deps.llm_budget.limit = deps._settings.llm_daily_call_budget

    assert response.status_code == 429
    assert "budget" in response.json()["detail"]


def test_an_unauthenticated_caller_is_still_rejected_before_any_limit(client: TestClient) -> None:
    assert client.post("/api/export/csv", json=_TABLE).status_code == 401


_TABLE: dict[str, object] = {
    "table": {
        "goal": "sample size",
        "fields": [{"key": "sample_size", "label": "Sample size"}],
        "rows": [],
    }
}
