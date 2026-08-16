from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

import httpx

from app.core.dependency_health import MonitoredAsyncClient
from app.services.rate_limit import RateLimiter, retry_with_backoff

from .errors import GrantsRequestError, GrantsResponseError
from .models import GrantOpportunity, GrantSource, ProgramProvenance
from .parsing import (
    as_dict,
    clean_text,
    infer_program,
    parse_date,
    parse_money,
    parse_status,
)

GRANTS_GOV_BASE_URL = "https://api.grants.gov/v1/api"
OPPORTUNITY_URL = "https://www.grants.gov/search-results-detail"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
MAX_PAGE_SIZE = 100

# `search2` returns nothing unless at least one status is requested.
OPEN_STATUSES = ("posted",)
ALL_STATUSES = ("forecasted", "posted", "closed", "archived")


class GrantsGovClient:
    """
    Async wrapper over the grants.gov `search2` and `fetchOpportunity` endpoints.

    Both are public REST endpoints that need no key or registration. `search2` returns a
    summary hit (title, agency, dates) but no synopsis text or funding figures, so the caller
    enriches the hits it actually intends to rank through `fetchOpportunity`.
    """

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        rate_limiter: RateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = GRANTS_GOV_BASE_URL,
        max_attempts: int = 4,
        base_delay: float = 0.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.rate_limiter = rate_limiter or RateLimiter(5.0)
        self._client = MonitoredAsyncClient("grants_gov", timeout=timeout, transport=transport)
        self._agency_vocabulary: dict[str, list[str]] | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> GrantsGovClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{path}"

        async def attempt() -> httpx.Response:
            await self.rate_limiter.acquire()
            try:
                response = await self._client.post(url, json=payload)
            except httpx.HTTPError as exc:
                raise GrantsRequestError(f"{path} request failed: {exc}") from exc
            if response.status_code >= 400:
                raise GrantsRequestError(
                    f"{path} failed (HTTP {response.status_code})",
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
            body = response.json()
        except ValueError as exc:
            raise GrantsResponseError(f"{path} returned a non-JSON body") from exc
        if not isinstance(body, dict):
            raise GrantsResponseError(f"{path} returned a non-object body")
        # grants.gov answers application-level failures with HTTP 200 and a non-zero errorcode.
        if body.get("errorcode") not in (0, "0", None):
            raise GrantsRequestError(f"{path} failed: {body.get('msg') or 'unknown error'}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise GrantsResponseError(f"{path} response is missing the data object")
        return data

    async def search(
        self,
        *,
        keyword: str = "",
        agency_codes: list[str] | None = None,
        statuses: list[str] | None = None,
        rows: int = 25,
        start_record: int = 0,
    ) -> dict[str, Any]:
        """Raw `search2` data object for one page of hits."""
        payload: dict[str, Any] = {
            "keyword": keyword,
            "rows": rows,
            "startRecordNum": start_record,
            "oppStatuses": "|".join(statuses or list(ALL_STATUSES)),
        }
        if agency_codes:
            payload["agencies"] = "|".join(agency_codes)
        return await self._post("search2", payload)

    async def agency_vocabulary(self) -> dict[str, list[str]]:
        """
        Department code -> every agency code that sits under it, from the `search2` facet.

        `agencies` matches codes exactly, with no prefix expansion: `agencies="DOD"` finds the
        two opportunities literally filed under `DOD` while the department's real postings sit
        under `DOD-AMRAA`, `DOD-DARPA-*` and so on. The facet is the provider's own vocabulary,
        so it is read once per client rather than hard-coded and left to drift.
        """
        if self._agency_vocabulary is None:
            data = await self.search(rows=0)
            vocabulary: dict[str, list[str]] = {}
            facet = data.get("agencies")
            for entry in facet if isinstance(facet, list) else []:
                department = as_dict(entry)
                code = clean_text(department.get("value"), limit=100)
                if not code:
                    continue
                options = department.get("subAgencyOptions")
                children = [
                    clean_text(as_dict(option).get("value"), limit=100)
                    for option in (options if isinstance(options, list) else [])
                ]
                vocabulary[code] = sorted({code, *(child for child in children if child)})
            self._agency_vocabulary = vocabulary
        return self._agency_vocabulary

    async def expand_agency_codes(self, codes: list[str]) -> list[str]:
        """Replace department codes with the sub-agency codes that actually carry postings."""
        # Sub-agency codes are already exact ("HHS-NIH11"), so only a bare department code
        # ("DOD") is worth the vocabulary probe.
        if all("-" in code for code in codes):
            return codes
        try:
            vocabulary = await self.agency_vocabulary()
        except (GrantsRequestError, GrantsResponseError):
            # A missing vocabulary must narrow the search, never fail it.
            return codes
        expanded: list[str] = []
        for code in codes:
            for resolved in vocabulary.get(code, [code]):
                if resolved not in expanded:
                    expanded.append(resolved)
        return expanded

    async def fetch_opportunity(self, opportunity_id: str) -> dict[str, Any]:
        """Raw `fetchOpportunity` data object, which carries the synopsis and award figures."""
        try:
            numeric_id = int(opportunity_id)
        except ValueError as exc:
            raise GrantsResponseError(f"opportunity id is not numeric: {opportunity_id}") from exc
        return await self._post("fetchOpportunity", {"opportunityId": numeric_id})


def parse_hit(hit: dict[str, Any], today: date) -> GrantOpportunity:
    """Normalize one `search2` hit. Synopsis text and funding arrive later via enrichment."""
    close_date = parse_date(hit.get("closeDate"))
    title = clean_text(hit.get("title"), limit=500)
    opportunity_id = str(hit.get("id", "")).strip()
    program = infer_program(title)
    return GrantOpportunity(
        source=GrantSource.GRANTS_GOV,
        opportunity_id=opportunity_id,
        number=clean_text(hit.get("number"), limit=100),
        title=title,
        agency=clean_text(hit.get("agency"), limit=200),
        agency_code=clean_text(hit.get("agencyCode"), limit=100),
        program=program,
        program_provenance=ProgramProvenance.INFERRED if program else None,
        status=parse_status(hit.get("oppStatus"), close_date, today),
        posted_date=parse_date(hit.get("openDate")),
        close_date=close_date,
        url=f"{OPPORTUNITY_URL}/{opportunity_id}" if opportunity_id else "",
    )


def apply_detail(
    opportunity: GrantOpportunity, detail: dict[str, Any], today: date
) -> GrantOpportunity:
    """Fold a `fetchOpportunity` payload into the summary hit it belongs to."""
    synopsis = as_dict(detail.get("synopsis")) or as_dict(detail.get("forecast"))
    description = clean_text(synopsis.get("synopsisDesc") or synopsis.get("forecastDesc"))
    close_date = parse_date(synopsis.get("responseDate")) or opportunity.close_date
    program = infer_program(opportunity.title, description) or opportunity.program
    return opportunity.model_copy(
        update={
            "number": clean_text(detail.get("opportunityNumber"), limit=100) or opportunity.number,
            # The synopsis `agencyName` is the grantor contact person, not the agency, so the
            # summary hit wins and the synopsis only fills a gap.
            "agency": opportunity.agency or clean_text(synopsis.get("agencyName"), limit=200),
            "agency_code": opportunity.agency_code
            or clean_text(synopsis.get("agencyCode"), limit=100),
            "topic_description": description or opportunity.topic_description,
            "funding_ceiling": parse_money(synopsis.get("awardCeiling")),
            "funding_floor": parse_money(synopsis.get("awardFloor")),
            "close_date": close_date,
            "posted_date": parse_date(synopsis.get("postingDate")) or opportunity.posted_date,
            "status": parse_status(
                detail.get("docType") if detail.get("docType") == "forecast" else "",
                close_date,
                today,
            )
            or opportunity.status,
            "program": program,
            "program_provenance": ProgramProvenance.INFERRED if program else None,
        }
    )


async def enrich(
    client: GrantsGovClient,
    opportunities: list[GrantOpportunity],
    *,
    today: date,
    concurrency: int = 5,
) -> list[GrantOpportunity]:
    """
    Fill in synopsis text and award figures for each hit.

    One extra request per opportunity is unavoidable — `search2` simply does not return the
    description the matcher needs — so calls are bounded and a per-opportunity failure leaves
    that row summary-only instead of failing the page.
    """
    semaphore = asyncio.Semaphore(concurrency)

    async def one(opportunity: GrantOpportunity) -> GrantOpportunity:
        async with semaphore:
            try:
                detail = await client.fetch_opportunity(opportunity.opportunity_id)
            except (GrantsRequestError, GrantsResponseError):
                return opportunity
            return apply_detail(opportunity, detail, today)

    return list(await asyncio.gather(*(one(item) for item in opportunities)))
