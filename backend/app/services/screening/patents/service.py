from __future__ import annotations

import logging

import httpx

from app.core.config import Settings, get_settings
from app.services.rate_limit import RateLimiter

from .client import MAX_PAGE_SIZE, ODP_BASE_URL, UsptoOdpClient
from .errors import InvalidFilterError, PatentRequestError, PatentResponseError
from .models import (
    MAX_OFFSET,
    NO_MATCH_STATEMENT,
    DerivedQuery,
    PatentLandscape,
    PatentSearch,
    PatentSort,
    QueryDerivation,
    StructureBasis,
)
from .parsing import parse_records, total_found
from .query import derive_terms, formula_term, query_string

logger = logging.getLogger(__name__)

# Upstream sort expressions, keyed by the sort the API exposes. `RELEVANCE` sends nothing and
# keeps the upstream ranking.
SORT_EXPRESSIONS: dict[PatentSort, str] = {
    PatentSort.FILING_DATE_DESC: "applicationMetaData.filingDate desc",
    PatentSort.FILING_DATE_ASC: "applicationMetaData.filingDate asc",
    PatentSort.GRANT_DATE_DESC: "applicationMetaData.grantDate desc",
}
FILING_DATE_FIELD = "applicationMetaData.filingDate"
# `rangeFilters` needs both ends, so a one-sided filter is widened with a bound that cannot
# exclude a real filing date.
OPEN_RANGE_START = "1790-01-01"
OPEN_RANGE_END = "9999-12-31"

UNCONFIGURED_STATUS = (
    "The USPTO Open Data Portal search API requires a free API key (X-API-KEY) and none is "
    "configured for this deployment, so no patent search was performed. Nothing below is a "
    "search result. Set USPTO_ODP_API_KEY to enable the source."
)


def degraded_status(status_code: int | None) -> str:
    """What to tell the caller when the upstream search could not be completed."""
    if status_code in (401, 403):
        return (
            "The USPTO Open Data Portal rejected this deployment's API key, so no patent search "
            "was performed. Nothing below is a search result."
        )
    if status_code == 429:
        return (
            "The USPTO Open Data Portal rate-limited this deployment, so no patent search was "
            "performed. Nothing below is a search result; retry shortly."
        )
    detail = f"HTTP {status_code}" if status_code is not None else "was unreachable"
    return (
        f"The USPTO Open Data Portal search API {detail} after retries, so no patent search was "
        "performed. Nothing below is a search result; this says nothing about prior art."
    )


class PatentsService:
    """
    Keyword prior-art search over USPTO patent applications.

    Deliberately narrow: it builds one text query, sends it to one endpoint, and reports what
    came back. It does not rank by structural similarity, score novelty or opine on freedom to
    operate — `PatentLandscape.unavailable` names each of those and what it would take instead.

    An unusable source (no API key, a rejected key, a degraded upstream) returns a landscape
    with `source_available=False` and an empty hit list rather than raising, so the Screening tab
    can render the reason. Only a query the upstream API itself rejects (HTTP 400) raises, since
    that is a bug in query construction rather than a source outage.
    """

    def __init__(self, client: UsptoOdpClient | None = None) -> None:
        self.client = client or UsptoOdpClient()

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> PatentsService:
        settings = settings or get_settings()
        return cls(
            UsptoOdpClient(
                api_key=settings.uspto_odp_api_key,
                timeout=settings.uspto_odp_timeout_seconds,
                base_url=settings.uspto_odp_base_url or ODP_BASE_URL,
                rate_limiter=RateLimiter(settings.uspto_odp_rate_limit),
                transport=transport,
            )
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def search(self, search: PatentSearch) -> PatentLandscape:
        """
        One page of keyword prior-art results for `search`.

        Raises `InvalidStructureError`, `InvalidKeywordError` or `InvalidFilterError` for input
        the service will not send upstream, and `PatentRequestError` when the upstream API
        rejects the constructed query. Every other upstream failure degrades to a landscape
        marked `source_available=False`.
        """
        query = build_query(search)
        if not self.client.configured:
            logger.info(
                "screening.patents.search",
                extra={"outcome": "unconfigured", "terms": len(query.terms)},
            )
            return unavailable_landscape(search, query, UNCONFIGURED_STATUS)

        params = build_params(search, query.query_used)
        try:
            payload = await self.client.search_applications(params)
        except PatentRequestError as exc:
            # 400 means the API rejected the query expression itself: our bug, not an outage.
            if exc.status_code == 400:
                logger.warning(
                    "screening.patents.search", extra={"outcome": "rejected", "status": 400}
                )
                raise
            logger.warning(
                "screening.patents.search",
                extra={"outcome": "degraded", "status": exc.status_code},
            )
            return unavailable_landscape(search, query, degraded_status(exc.status_code))
        except PatentResponseError:
            logger.warning("screening.patents.search", extra={"outcome": "unparseable"})
            return unavailable_landscape(search, query, degraded_status(None))

        hits = parse_records(payload)
        total = total_found(payload)
        logger.info(
            "screening.patents.search",
            extra={"outcome": "ok", "returned": len(hits), "terms": len(query.terms)},
        )
        return PatentLandscape(
            source_available=True,
            query=query,
            sort=search.sort,
            page_size=search.page_size,
            offset=search.offset,
            returned=len(hits),
            total_found=total,
            hits=hits,
            no_match_statement="" if hits else NO_MATCH_STATEMENT,
        )


def build_query(search: PatentSearch) -> DerivedQuery:
    """Validate the request and describe the text query it produces."""
    validate_filters(search)
    derived = derive_terms(search.smiles, search.keywords)
    structure = derived.structure
    if structure is None:
        derivation = (
            "Searched the keywords supplied, AND-ed together, as a free-form text query. No "
            "structure was submitted."
        )
        derived_from = QueryDerivation.KEYWORDS
        basis = None
    else:
        formula = formula_term(structure)
        keyword_part = [term for term in derived.terms if term != formula]
        derived_from = (
            QueryDerivation.STRUCTURE_FORMULA_AND_KEYWORDS
            if keyword_part
            else QueryDerivation.STRUCTURE_FORMULA
        )
        extra = f" AND the keywords {', '.join(keyword_part)}" if keyword_part else ""
        derivation = (
            f"A structure was submitted, but the upstream index holds text rather than chemical "
            f"structures. The search ran on the molecular formula RDKit computed from the "
            f"structure ({formula}){extra} — not on the structure itself."
        )
        basis = StructureBasis(
            input_smiles=structure.input_smiles,
            canonical_smiles=structure.canonical_smiles,
            molecular_formula=structure.molecular_formula,
            inchikey=structure.inchikey,
        )
    return DerivedQuery(
        query_used=query_string(derived.terms),
        derived_from=derived_from,
        terms=derived.terms,
        derivation=derivation,
        structure=basis,
    )


def validate_filters(search: PatentSearch) -> None:
    """Re-check the bounds the route's schema already applies, and the ones it cannot."""
    if not 1 <= search.page_size <= MAX_PAGE_SIZE:
        raise InvalidFilterError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    if not 0 <= search.offset <= MAX_OFFSET:
        raise InvalidFilterError(f"offset must be between 0 and {MAX_OFFSET}")
    if search.filed_from and search.filed_to and search.filed_from > search.filed_to:
        raise InvalidFilterError("filed_from must not be later than filed_to")


def build_params(search: PatentSearch, query_used: str) -> dict[str, str]:
    """
    The upstream query parameters for `search`.

    User input reaches the upstream API only through these values, never through the URL or
    path, which is what keeps the request pointed at the configured host.
    """
    params = {"q": query_used, "limit": str(search.page_size), "offset": str(search.offset)}
    expression = SORT_EXPRESSIONS.get(search.sort)
    if expression:
        params["sort"] = expression
    if search.filed_from or search.filed_to:
        start = search.filed_from.isoformat() if search.filed_from else OPEN_RANGE_START
        end = search.filed_to.isoformat() if search.filed_to else OPEN_RANGE_END
        params["rangeFilters"] = f"{FILING_DATE_FIELD} {start}:{end}"
    return params


def unavailable_landscape(
    search: PatentSearch, query: DerivedQuery, status: str
) -> PatentLandscape:
    """
    A landscape saying the source could not be searched.

    `no_match_statement` stays empty on purpose: no search ran, so there is nothing to describe
    as "no matches".
    """
    return PatentLandscape(
        source_available=False,
        source_status=status,
        query=query,
        sort=search.sort,
        page_size=search.page_size,
        offset=search.offset,
        returned=0,
        total_found=None,
        hits=[],
    )
