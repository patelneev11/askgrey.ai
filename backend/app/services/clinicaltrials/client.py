from __future__ import annotations

from typing import Any

import httpx

from app.core.dependency_health import MonitoredAsyncClient
from app.services.rate_limit import RateLimiter, retry_with_backoff

from .errors import ClinicalTrialsRequestError, ClinicalTrialsResponseError

CTG_BASE_URL = "https://clinicaltrials.gov/api/v2"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_PAGE_SIZE = 100

# Only the modules the normalizer reads. The full study document is ~50x larger, and the API
# charges the caller in latency rather than quota for the difference.
STUDY_FIELDS = (
    "protocolSection.identificationModule.nctId",
    "protocolSection.identificationModule.briefTitle",
    "protocolSection.identificationModule.officialTitle",
    "protocolSection.statusModule",
    "protocolSection.sponsorCollaboratorsModule",
    "protocolSection.conditionsModule.conditions",
    "protocolSection.designModule",
    "protocolSection.armsInterventionsModule.interventions",
)


class ClinicalTrialsClient:
    """
    Thin async wrapper over the ClinicalTrials.gov v2 `/studies` endpoint.

    The API is unauthenticated and does not publish a rate limit, so the default limiter is a
    politeness measure rather than a quota. Requests are retried with exponential backoff on
    429/5xx and transport failures; 4xx (a malformed filter expression) is surfaced immediately.
    """

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        rate_limiter: RateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = CTG_BASE_URL,
        max_attempts: int = 4,
        base_delay: float = 0.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.rate_limiter = rate_limiter or RateLimiter(5.0)
        self._client = MonitoredAsyncClient("clinicaltrials", timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ClinicalTrialsClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def studies(self, params: dict[str, str]) -> dict[str, Any]:
        """Raw `/studies` payload for already-built query parameters."""
        url = f"{self.base_url}/studies"
        request_params = {**params, "fields": ",".join(STUDY_FIELDS), "countTotal": "true"}

        async def attempt() -> httpx.Response:
            await self.rate_limiter.acquire()
            try:
                response = await self._client.get(url, params=request_params)
            except httpx.HTTPError as exc:
                raise ClinicalTrialsRequestError(f"studies request failed: {exc}") from exc
            if response.status_code >= 400:
                raise ClinicalTrialsRequestError(
                    f"studies failed (HTTP {response.status_code}: {_error_detail(response)})",
                    status_code=response.status_code,
                )
            return response

        def should_retry(exc: BaseException) -> bool:
            if not isinstance(exc, ClinicalTrialsRequestError):
                return False
            # A transport failure has no status code and is worth another attempt.
            return exc.status_code is None or exc.status_code in RETRYABLE_STATUS_CODES

        response = await retry_with_backoff(
            attempt,
            should_retry=should_retry,
            max_attempts=self.max_attempts,
            base_delay=self.base_delay,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ClinicalTrialsResponseError("studies returned a non-JSON body") from exc
        if not isinstance(payload, dict):
            raise ClinicalTrialsResponseError("studies returned a non-object body")
        if not isinstance(payload.get("studies"), list):
            raise ClinicalTrialsResponseError("studies response is missing the studies list")
        return payload


def _error_detail(response: httpx.Response) -> str:
    """The v2 API reports filter errors as a plain-text body, occasionally as JSON."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:200]
    if isinstance(body, dict):
        message = body.get("message") or body.get("error")
        if isinstance(message, str):
            return message
    return response.text.strip()[:200]
