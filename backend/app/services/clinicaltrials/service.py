from __future__ import annotations

from collections.abc import AsyncIterator

from app.core.config import Settings, get_settings
from app.services.rate_limit import RateLimiter

from .client import MAX_PAGE_SIZE, ClinicalTrialsClient
from .errors import ClinicalTrialsRequestError, InvalidQueryError
from .models import TrialPage, TrialSearch
from .parsing import parse_study

DEFAULT_PAGE_SIZE = 25


class ClinicalTrialsService:
    """
    Filtered, paginated search over ClinicalTrials.gov v2.

    Filters map onto the API's own facets: sponsor/condition/intervention are text search areas,
    phase and status are enum filters, and everything supplied is AND-ed together. Results come
    back as `TrialRecord`s that project into the shared `SourceRecord` review row.
    """

    def __init__(self, client: ClinicalTrialsClient | None = None) -> None:
        self.client = client or ClinicalTrialsClient()

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ClinicalTrialsService:
        settings = settings or get_settings()
        return cls(
            ClinicalTrialsClient(
                timeout=settings.clinicaltrials_timeout_seconds,
                base_url=settings.clinicaltrials_base_url,
                rate_limiter=RateLimiter(settings.clinicaltrials_rate_limit),
            )
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def search(
        self,
        search: TrialSearch,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        page_token: str | None = None,
    ) -> TrialPage:
        """
        One page of trials matching `search`.

        Carry the returned `next_page_token` into the following call to walk a large result set;
        it is `None` once the last page has been served.
        """
        if search.is_empty():
            raise InvalidQueryError("at least one filter is required")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise InvalidQueryError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")

        params = build_params(search, page_size=page_size, page_token=page_token)
        try:
            payload = await self.client.studies(params)
        except ClinicalTrialsRequestError as exc:
            # A 400 means the API rejected the filter expression itself, so retrying is pointless.
            if exc.status_code == 400:
                raise InvalidQueryError(str(exc)) from exc
            raise

        # The client has already verified `studies` is a list.
        studies = payload["studies"]
        trials = [parse_study(study) for study in studies if isinstance(study, dict)]
        total = payload.get("totalCount")
        token = payload.get("nextPageToken")
        return TrialPage(
            search=search,
            trials=trials,
            total_count=total if isinstance(total, int) else len(trials),
            page_size=page_size,
            next_page_token=token if isinstance(token, str) and token else None,
        )

    async def iter_pages(
        self,
        search: TrialSearch,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = 10,
    ) -> AsyncIterator[TrialPage]:
        """Walk pages until the result set is exhausted or `max_pages` have been yielded."""
        token: str | None = None
        for _ in range(max_pages):
            page = await self.search(search, page_size=page_size, page_token=token)
            yield page
            if not page.has_more:
                return
            token = page.next_page_token


def build_params(
    search: TrialSearch, *, page_size: int, page_token: str | None = None
) -> dict[str, str]:
    """Translate a `TrialSearch` into v2 query parameters."""
    params: dict[str, str] = {"pageSize": str(page_size)}
    if search.term.strip():
        params["query.term"] = search.term.strip()
    if search.sponsor.strip():
        params["query.spons"] = search.sponsor.strip()
    if search.condition.strip():
        params["query.cond"] = search.condition.strip()
    if search.intervention.strip():
        params["query.intr"] = search.intervention.strip()
    if search.statuses:
        params["filter.overallStatus"] = ",".join(status.value for status in search.statuses)
    if search.phases:
        # Phase has no dedicated filter parameter; it lives in the Essie advanced expression.
        values = [phase.value for phase in search.phases]
        expression = values[0] if len(values) == 1 else f"({' OR '.join(values)})"
        params["filter.advanced"] = f"AREA[Phase]{expression}"
    if page_token:
        params["pageToken"] = page_token
    return params
