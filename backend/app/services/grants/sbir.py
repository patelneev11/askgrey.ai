from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from app.services.rate_limit import RateLimiter, retry_with_backoff

from .errors import GrantsRequestError, GrantsResponseError
from .models import GrantOpportunity, GrantSource
from .parsing import clean_text, parse_date, parse_program, parse_status

SBIR_BASE_URL = "https://api.www.sbir.gov/public/api"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
# The documented cap for the `rows` parameter.
MAX_PAGE_SIZE = 50


class SbirClient:
    """
    Async wrapper over the SBIR.gov solicitations API.

    The endpoint is public and needs no key, but SBIR.gov fronts it with a WAF that rejects
    some hosting ranges outright with `403 Forbidden`; that failure is surfaced as a request
    error so the caller can degrade to grants.gov alone rather than fail the whole search.
    """

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        rate_limiter: RateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = SBIR_BASE_URL,
        max_attempts: int = 3,
        base_delay: float = 0.5,
        user_agent: str = "askgrey/1.0",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.rate_limiter = rate_limiter or RateLimiter(2.0)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> SbirClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def solicitations(
        self,
        *,
        keyword: str = "",
        agency: str = "",
        open_only: bool = True,
        rows: int = 25,
        start: int = 0,
    ) -> list[dict[str, Any]]:
        """One page of solicitations, newest offsets first, as raw provider objects."""
        params: dict[str, str] = {"rows": str(min(rows, MAX_PAGE_SIZE)), "start": str(start)}
        if keyword.strip():
            params["keyword"] = keyword.strip()
        if agency.strip():
            params["agency"] = agency.strip()
        if open_only:
            params["open"] = "1"

        url = f"{self.base_url}/solicitations"

        async def attempt() -> httpx.Response:
            await self.rate_limiter.acquire()
            try:
                response = await self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                raise GrantsRequestError(f"solicitations request failed: {exc}") from exc
            if response.status_code >= 400:
                raise GrantsRequestError(
                    f"solicitations failed (HTTP {response.status_code})",
                    status_code=response.status_code,
                )
            return response

        def should_retry(exc: BaseException) -> bool:
            if not isinstance(exc, GrantsRequestError):
                return False
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
            raise GrantsResponseError("solicitations returned a non-JSON body") from exc
        if not isinstance(payload, list):
            raise GrantsResponseError("solicitations returned a non-list body")
        return [item for item in payload if isinstance(item, dict)]


def _topics(solicitation: dict[str, Any]) -> tuple[list[str], str]:
    """
    Flatten `solicitation_topics` (and their subtopics) into titles plus one description blob.

    A solicitation is only as specific as its topics — the solicitation record itself carries
    no abstract — so the topic text is what the semantic matcher has to work with.
    """
    titles: list[str] = []
    descriptions: list[str] = []
    raw_topics = solicitation.get("solicitation_topics")
    for topic in raw_topics if isinstance(raw_topics, list) else []:
        if not isinstance(topic, dict):
            continue
        title = clean_text(topic.get("topic_title"), limit=300)
        if title:
            titles.append(title)
        description = clean_text(topic.get("topic_description"), limit=2000)
        if description:
            descriptions.append(f"{title}: {description}" if title else description)
        subtopics = topic.get("subtopics")
        for subtopic in subtopics if isinstance(subtopics, list) else []:
            if not isinstance(subtopic, dict):
                continue
            sub_title = clean_text(subtopic.get("subtopic_title"), limit=300)
            if sub_title:
                titles.append(sub_title)
            sub_description = clean_text(subtopic.get("subtopic_description"), limit=1000)
            if sub_description:
                descriptions.append(
                    f"{sub_title}: {sub_description}" if sub_title else sub_description
                )
    return titles, clean_text(" ".join(descriptions), limit=8000)


def parse_solicitation(solicitation: dict[str, Any], today: date) -> GrantOpportunity:
    """Normalize one SBIR.gov solicitation into the shared opportunity shape."""
    titles, description = _topics(solicitation)
    # `close_date` is the solicitation's own end; individual topics may close earlier via
    # `application_due_date`, so the earliest published due date wins when both exist.
    close_date = parse_date(solicitation.get("close_date"))
    due_dates = solicitation.get("application_due_date")
    parsed_due = (
        [
            parsed
            for parsed in (parse_date(value) for value in due_dates or [])
            if parsed is not None
        ]
        if isinstance(due_dates, list)
        else []
    )
    if parsed_due:
        earliest = min(parsed_due)
        close_date = earliest if close_date is None else min(close_date, earliest)

    number = clean_text(solicitation.get("solicitation_number"), limit=100)
    return GrantOpportunity(
        source=GrantSource.SBIR,
        opportunity_id=number or clean_text(solicitation.get("solicitation_title"), limit=100),
        number=number,
        title=clean_text(solicitation.get("solicitation_title"), limit=500),
        agency=clean_text(solicitation.get("agency"), limit=200),
        agency_code=clean_text(solicitation.get("agency"), limit=100),
        branch=clean_text(solicitation.get("branch"), limit=200),
        program=parse_program(solicitation.get("program")),
        status=parse_status(solicitation.get("current_status"), close_date, today),
        posted_date=parse_date(solicitation.get("open_date"))
        or parse_date(solicitation.get("release_date")),
        close_date=close_date,
        topic_description=description,
        topics=titles,
        url=clean_text(solicitation.get("solicitation_agency_url"), limit=500),
    )
