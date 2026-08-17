from __future__ import annotations

from typing import Any

import httpx

from app.core.dependency_health import MonitoredAsyncClient
from app.services.rate_limit import RateLimiter, retry_with_backoff

from .errors import PatentRequestError, PatentResponseError

# The base URL is a constant here and a setting in `Settings`; it is never taken from caller
# input, which is what keeps a "search this URL" request from becoming an SSRF primitive. User
# input only ever becomes a query *parameter* on this fixed host.
ODP_BASE_URL = "https://api.uspto.gov/api/v1"
SEARCH_PATH = "patent/applications/search"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# Upstream answers a search that matched nothing with 404 and this phrase, rather than with an
# empty 200 body. Matching on the phrase keeps a genuine zero-hit search distinguishable from a
# 404 caused by a wrong path or a withdrawn endpoint, which is a deployment fault and must not
# be reported to a researcher as "no prior art found".
NO_MATCH_MARKER = "no matching records found"
EMPTY_PAYLOAD: dict[str, Any] = {"count": 0, "patentFileWrapperDataBag": []}
# Upstream's own ceiling per request; also what one screen of prior art can usefully show.
MAX_PAGE_SIZE = 50


class UsptoOdpClient:
    """
    Thin async wrapper over the USPTO Open Data Portal patent application search endpoint.

    The endpoint requires a free ODP API key, sent as `X-API-KEY`. Without one the client is
    `configured is False` and never makes a request, so the service can report the source as
    unavailable rather than failing or pretending to have searched. Requests are spaced by a
    shared `RateLimiter` (USPTO publishes no public per-key rate, so the default is a politeness
    measure) and retried with exponential backoff on 429/5xx and transport failures.

    The key is held here and sent only as a request header: it is never logged, never echoed
    into an error message, and never part of a response body.
    """

    def __init__(
        self,
        *,
        api_key: str = "",
        timeout: float = 20.0,
        rate_limiter: RateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = ODP_BASE_URL,
        max_attempts: int = 3,
        base_delay: float = 0.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.rate_limiter = rate_limiter or RateLimiter(2.0)
        self._client = MonitoredAsyncClient("uspto_odp", timeout=timeout, transport=transport)

    @property
    def configured(self) -> bool:
        """True when an API key is present. False means no request may be attempted."""
        return bool(self.api_key)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> UsptoOdpClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def search_applications(self, params: dict[str, str]) -> dict[str, Any]:
        """
        Raw search payload for already-built query parameters.

        Raises `PatentRequestError` (carrying the upstream status) or `PatentResponseError`.
        """
        if not self.configured:
            raise PatentRequestError("USPTO ODP API key is not configured")
        url = f"{self.base_url}/{SEARCH_PATH}"
        headers = {"X-API-KEY": self.api_key, "Accept": "application/json"}

        async def attempt() -> httpx.Response:
            await self.rate_limiter.acquire()
            try:
                response = await self._client.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                raise PatentRequestError(f"patent search request failed: {exc}") from exc
            if response.status_code == 404 and _is_no_match(response):
                return response
            if response.status_code >= 400:
                raise PatentRequestError(
                    f"patent search failed (HTTP {response.status_code})",
                    status_code=response.status_code,
                )
            return response

        def should_retry(exc: BaseException) -> bool:
            if not isinstance(exc, PatentRequestError):
                return False
            # A transport failure has no status code and is worth another attempt.
            return exc.status_code is None or exc.status_code in RETRYABLE_STATUS_CODES

        response = await retry_with_backoff(
            attempt,
            should_retry=should_retry,
            max_attempts=self.max_attempts,
            base_delay=self.base_delay,
        )
        if response.status_code == 404:
            # A search that matched nothing, reported as the empty result set it is.
            return dict(EMPTY_PAYLOAD)
        try:
            payload = response.json()
        except ValueError as exc:
            raise PatentResponseError("patent search returned a non-JSON body") from exc
        if not isinstance(payload, dict):
            raise PatentResponseError("patent search returned a non-object body")
        return payload


def _is_no_match(response: httpx.Response) -> bool:
    """True when a 404 body says the query matched no records, rather than that the path is gone."""
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    text = " ".join(str(body.get(key, "")) for key in ("detailedMessage", "message", "error"))
    return NO_MATCH_MARKER in text.casefold()
