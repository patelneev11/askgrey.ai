from __future__ import annotations

import asyncio
from datetime import date

from app.core.config import Settings, get_settings
from app.services.rate_limit import RateLimiter

from .agencies import resolve_agency
from .errors import GrantsError, InvalidQueryError
from .grants_gov import MAX_PAGE_SIZE as GRANTS_GOV_MAX_PAGE_SIZE
from .grants_gov import OPEN_STATUSES, GrantsGovClient, enrich, parse_hit
from .matching import (
    ClaudeMatchRanker,
    FallbackMatchRanker,
    LexicalMatchRanker,
    MatchRanker,
    RankedMatches,
    normalize_focus,
)
from .models import (
    GrantOpportunity,
    GrantPage,
    GrantSearch,
    GrantSource,
    GrantStatus,
    MatchResult,
    SourceStatus,
)
from .sbir import MAX_PAGE_SIZE as SBIR_MAX_PAGE_SIZE
from .sbir import SbirClient, parse_solicitation

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = min(GRANTS_GOV_MAX_PAGE_SIZE, SBIR_MAX_PAGE_SIZE)
DEFAULT_MATCH_CANDIDATES = 40
MAX_MATCH_CANDIDATES = 100


class GrantsService:
    """
    Federal funding search across grants.gov and SBIR.gov, plus semantic matching.

    Both providers are queried concurrently and merged into one `GrantOpportunity` list;
    filters neither provider supports (program, closing-date window) are applied locally.
    A provider that fails is reported in `sources` and the page is served from the other one,
    because a WAF block or an outage on one side should not blank the Grants tab.
    """

    def __init__(
        self,
        *,
        grants_gov: GrantsGovClient | None = None,
        sbir: SbirClient | None = None,
        ranker: MatchRanker | None = None,
        enrich_limit: int = 25,
        today: date | None = None,
    ) -> None:
        self.grants_gov = grants_gov or GrantsGovClient()
        self.sbir = sbir or SbirClient()
        self.ranker = ranker or LexicalMatchRanker()
        self.enrich_limit = enrich_limit
        self._today = today

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> GrantsService:
        settings = settings or get_settings()
        lexical = LexicalMatchRanker()
        ranker: MatchRanker = lexical
        if settings.anthropic_api_key:
            ranker = FallbackMatchRanker(
                ClaudeMatchRanker(
                    api_key=settings.anthropic_api_key,
                    model=settings.llm_model,
                    base_url=settings.anthropic_base_url,
                    anthropic_version=settings.anthropic_version,
                    max_tokens=settings.grants_match_max_tokens,
                    timeout=settings.grants_match_timeout_seconds,
                ),
                lexical,
            )
        return cls(
            grants_gov=GrantsGovClient(
                timeout=settings.grants_gov_timeout_seconds,
                base_url=settings.grants_gov_base_url,
                rate_limiter=RateLimiter(settings.grants_gov_rate_limit),
            ),
            sbir=SbirClient(
                timeout=settings.sbir_timeout_seconds,
                base_url=settings.sbir_base_url,
                rate_limiter=RateLimiter(settings.sbir_rate_limit),
            ),
            ranker=ranker,
            enrich_limit=settings.grants_enrich_limit,
        )

    async def aclose(self) -> None:
        await asyncio.gather(self.grants_gov.aclose(), self.sbir.aclose())

    @property
    def today(self) -> date:
        return self._today or date.today()

    async def search(
        self,
        search: GrantSearch,
        *,
        page: int = 0,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> GrantPage:
        """
        One page of opportunities matching `search`.

        `page` is an offset into each provider independently, so a page holds up to
        `page_size` results per enabled provider rather than `page_size` in total.
        """
        if search.is_empty():
            raise InvalidQueryError("at least one filter is required")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise InvalidQueryError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        if page < 0:
            raise InvalidQueryError("page must not be negative")
        if not search.sources:
            raise InvalidQueryError("at least one source is required")
        if (
            search.closing_after
            and search.closing_before
            and search.closing_after > search.closing_before
        ):
            raise InvalidQueryError("closing_after must not be later than closing_before")

        today = self.today
        tasks = []
        if GrantSource.GRANTS_GOV in search.sources:
            tasks.append(self._search_grants_gov(search, page, page_size, today))
        if GrantSource.SBIR in search.sources:
            tasks.append(self._search_sbir(search, page, page_size, today))

        results = await asyncio.gather(*tasks)

        opportunities: list[GrantOpportunity] = []
        statuses: list[SourceStatus] = []
        total = 0
        for found, status in results:
            kept = [item for item in found if self._keep(item, search, today)]
            status.returned = len(kept)
            opportunities.extend(kept)
            statuses.append(status)
            total += status.total_count

        opportunities.sort(key=_deadline_sort_key)
        return GrantPage(
            search=search,
            opportunities=opportunities,
            total_count=total,
            page=page,
            page_size=page_size,
            sources=statuses,
        )

    async def match(
        self,
        focus: str,
        search: GrantSearch,
        *,
        limit: int = 10,
        candidate_pool: int = DEFAULT_MATCH_CANDIDATES,
    ) -> MatchResult:
        """
        Rank open opportunities against a short description of a company's research focus.

        The pool is gathered with the same filters as `search`, then ranked semantically; the
        filters decide *what is eligible*, the ranker only decides the order.
        """
        normalized = normalize_focus(focus)
        if limit < 1:
            raise InvalidQueryError("limit must be at least 1")
        if not 1 <= candidate_pool <= MAX_MATCH_CANDIDATES:
            raise InvalidQueryError(f"candidate_pool must be between 1 and {MAX_MATCH_CANDIDATES}")

        candidates: list[GrantOpportunity] = []
        statuses: list[SourceStatus] = []
        page = 0
        while len(candidates) < candidate_pool:
            page_size = min(MAX_PAGE_SIZE, candidate_pool - len(candidates))
            found = await self.search(search, page=page, page_size=page_size)
            statuses = found.sources
            if not found.opportunities:
                break
            candidates.extend(found.opportunities)
            if not found.has_more:
                break
            page += 1

        candidates = candidates[:candidate_pool]
        ranked = (
            await self.ranker.rank(normalized, candidates)
            if candidates
            else RankedMatches(self.ranker.name, [])
        )
        return MatchResult(
            focus=normalized,
            matcher=ranked.matcher,
            candidates_considered=len(candidates),
            matches=ranked.matches[:limit],
            sources=statuses,
        )

    async def _search_grants_gov(
        self, search: GrantSearch, page: int, page_size: int, today: date
    ) -> tuple[list[GrantOpportunity], SourceStatus]:
        status = SourceStatus(source=GrantSource.GRANTS_GOV)
        alias = resolve_agency(search.agency) if search.agency.strip() else None
        try:
            codes = (
                await self.grants_gov.expand_agency_codes(alias.grants_gov_codes) if alias else None
            )
            data = await self.grants_gov.search(
                keyword=search.keyword.strip(),
                agency_codes=codes,
                statuses=list(OPEN_STATUSES) if search.open_only else None,
                rows=page_size,
                start_record=page * page_size,
            )
        except GrantsError as exc:
            status.ok = False
            status.error = str(exc)
            return [], status

        hits = data.get("oppHits")
        opportunities = [
            parse_hit(hit, today) for hit in (hits if isinstance(hits, list) else []) if hit
        ]
        hit_count = data.get("hitCount")
        status.total_count = hit_count if isinstance(hit_count, int) else len(opportunities)

        if self.enrich_limit > 0:
            opportunities = (
                await enrich(self.grants_gov, opportunities[: self.enrich_limit], today=today)
                + opportunities[self.enrich_limit :]
            )
        return opportunities, status

    async def _search_sbir(
        self, search: GrantSearch, page: int, page_size: int, today: date
    ) -> tuple[list[GrantOpportunity], SourceStatus]:
        status = SourceStatus(source=GrantSource.SBIR)
        alias = resolve_agency(search.agency) if search.agency.strip() else None
        if alias is not None and not alias.sbir_code:
            # SBIR.gov only filters by department, so a sub-agency alias (e.g. NIH) has no
            # equivalent there; searching without the filter would silently widen the request.
            status.ok = False
            status.error = (
                f"SBIR.gov cannot filter by '{search.agency}'; it only accepts department "
                "codes such as HHS, DOW, NASA, NSF, DOE, USDA, EPA, DOC, ED, DOT, DHS."
            )
            return [], status
        try:
            payload = await self.sbir.solicitations(
                keyword=search.keyword.strip(),
                agency=alias.sbir_code if alias else "",
                open_only=search.open_only,
                rows=page_size,
                start=page * page_size,
            )
        except GrantsError as exc:
            status.ok = False
            status.error = str(exc)
            return [], status

        opportunities = [parse_solicitation(item, today) for item in payload]
        # The endpoint reports no hit count, so the caller can only know a page was full.
        status.total_count = page * page_size + len(opportunities)
        return opportunities, status

    def _keep(self, opportunity: GrantOpportunity, search: GrantSearch, today: date) -> bool:
        """Apply the filters neither provider supports."""
        if search.program and opportunity.program is not search.program:
            # A `BOTH` solicitation satisfies a request for either SBIR or STTR.
            if opportunity.program is None or opportunity.program.value != "BOTH":
                return False
        if search.open_only and opportunity.status is GrantStatus.CLOSED:
            return False
        close_date = opportunity.close_date
        if search.closing_after and (close_date is None or close_date < search.closing_after):
            return False
        if search.closing_before and (close_date is None or close_date > search.closing_before):
            return False
        if search.open_only and close_date is not None and close_date < today:
            return False
        return True


def _deadline_sort_key(opportunity: GrantOpportunity) -> tuple[int, date, str]:
    """Soonest deadline first; undated opportunities sink to the bottom."""
    if opportunity.close_date is None:
        return (1, date.max, opportunity.title)
    return (0, opportunity.close_date, opportunity.title)
