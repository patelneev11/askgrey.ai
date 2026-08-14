from __future__ import annotations

from typing import Any

import httpx

from .errors import EntrezRequestError, EntrezResponseError
from .rate_limit import RateLimiter, retry_with_backoff

EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class EntrezClient:
    """
    Thin async wrapper over the E-utilities endpoints this product uses.

    Every request passes through a shared `RateLimiter` and is retried with exponential
    backoff on 429/5xx, so callers never have to think about NCBI's throttling.
    """

    def __init__(
        self,
        *,
        api_key: str = "",
        tool: str = "askgrey",
        email: str = "",
        timeout: float = 20.0,
        rate_limiter: RateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = EUTILS_BASE_URL,
        max_attempts: int = 4,
        base_delay: float = 0.5,
    ) -> None:
        self.api_key = api_key
        self.tool = tool
        self.email = email
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.rate_limiter = rate_limiter or RateLimiter(10.0 if api_key else 3.0)
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> EntrezClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    def _params(self, extra: dict[str, Any]) -> dict[str, Any]:
        params: dict[str, Any] = {"db": "pubmed", "tool": self.tool}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        params.update({key: value for key, value in extra.items() if value is not None})
        return params

    async def _get(self, endpoint: str, params: dict[str, Any]) -> httpx.Response:
        url = f"{self.base_url}/{endpoint}"

        async def attempt() -> httpx.Response:
            await self.rate_limiter.acquire()
            try:
                response = await self._client.get(url, params=self._params(params))
            except httpx.HTTPError as exc:
                raise EntrezRequestError(f"{endpoint} request failed: {exc}") from exc
            if response.status_code >= 400:
                raise EntrezRequestError(
                    f"{endpoint} returned HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            return response

        def should_retry(exc: BaseException) -> bool:
            if not isinstance(exc, EntrezRequestError):
                return False
            # A transport failure has no status code and is worth another attempt.
            return exc.status_code is None or exc.status_code in RETRYABLE_STATUS_CODES

        return await retry_with_backoff(
            attempt,
            should_retry=should_retry,
            max_attempts=self.max_attempts,
            base_delay=self.base_delay,
        )

    async def esearch(
        self,
        term: str,
        *,
        retmax: int = 20,
        retstart: int = 0,
        sort: str = "relevance",
    ) -> dict[str, Any]:
        """Run a search and return the raw JSON `esearchresult` payload."""
        response = await self._get(
            "esearch.fcgi",
            {
                "term": term,
                "retmax": retmax,
                "retstart": retstart,
                "sort": sort,
                "retmode": "json",
            },
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise EntrezResponseError("esearch returned a non-JSON body") from exc
        result = payload.get("esearchresult")
        if not isinstance(result, dict):
            raise EntrezResponseError("esearch response is missing esearchresult")
        return result

    async def efetch(self, pmids: list[str]) -> str:
        """Fetch full records for `pmids` as PubmedArticleSet XML."""
        if not pmids:
            return ""
        response = await self._get(
            "efetch.fcgi",
            {"id": ",".join(pmids), "retmode": "xml"},
        )
        return response.text

    async def esummary(self, pmids: list[str]) -> dict[str, Any]:
        """Fetch document summaries for `pmids` as the raw JSON `result` payload."""
        if not pmids:
            return {}
        response = await self._get(
            "esummary.fcgi",
            {"id": ",".join(pmids), "retmode": "json"},
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise EntrezResponseError("esummary returned a non-JSON body") from exc
        result = payload.get("result")
        if not isinstance(result, dict):
            raise EntrezResponseError("esummary response is missing result")
        return result
