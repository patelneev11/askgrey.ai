from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.core.config import get_settings
from app.services.rate_limit import RateLimiter
from app.services.screening.patents import (
    NO_MATCH_STATEMENT,
    InvalidFilterError,
    PatentRequestError,
    PatentSearch,
    PatentSort,
    PatentsService,
    UsptoOdpClient,
    build_params,
    build_query,
)
from tests.screening.patents.conftest import (
    fixture_handler,
    json_handler,
    make_service,
    no_match_handler,
    status_handler,
    timeout_handler,
)

ASPIRIN = "CC(=O)OC1=CC=CC=C1C(=O)O"


@pytest.mark.asyncio
async def test_search_returns_the_parsed_upstream_page() -> None:
    service, transport = make_service(fixture_handler("search_page1.json"))

    landscape = await service.search(PatentSearch(keywords="salicylate composition"))
    await service.aclose()

    assert landscape.source_available is True
    assert landscape.returned == 3
    # Upstream's `count` is the whole match set, not this page: 16 matches, 3 records returned.
    assert landscape.total_found == 16
    assert landscape.hits[0].title == "Salicylate Compound Composition"
    assert landscape.no_match_statement == ""
    # Every term required, in the upstream's own operator: a literal `AND` would be searched
    # as a word, since this API defaults to OR.
    assert transport.last_query()["q"] == ["+salicylate +composition"]


@pytest.mark.asyncio
async def test_search_sends_only_query_parameters_to_the_configured_host() -> None:
    service, transport = make_service(fixture_handler("search_page1.json"))

    await service.search(PatentSearch(keywords="salicylate"))
    await service.aclose()

    request = transport.requests[-1]
    assert str(request.url).startswith("https://api.uspto.gov/api/v1/patent/applications/search?")
    assert request.headers["x-api-key"] == "test-odp-key"


@pytest.mark.asyncio
async def test_granted_records_carry_the_grant_metadata_upstream_reported() -> None:
    service, _ = make_service(fixture_handler("search_granted.json"))

    landscape = await service.search(PatentSearch(keywords="aspirin crystalline"))
    await service.aclose()

    hit = landscape.hits[0]
    assert (hit.patent_number, hit.grant_date) == ("12048708", "2024-07-30")
    assert hit.applicants == ["RHOSHAN PHARMACEUTICALS, INC."]
    assert hit.url == "https://data.uspto.gov/ui/patent/applications/17406285"
    # Two records off a seven-match set, so the landscape must report seven.
    assert (landscape.returned, landscape.total_found) == (2, 7)


@pytest.mark.asyncio
async def test_a_search_that_matched_nothing_is_a_result_not_a_degraded_source() -> None:
    """Upstream reports a zero-hit search as 404; reporting that as an outage would be a lie."""
    service, _ = make_service(no_match_handler())

    landscape = await service.search(PatentSearch(keywords="zzqxwvtherm nonexistentterm"))
    await service.aclose()

    assert landscape.source_available is True
    assert landscape.source_status == ""
    assert landscape.returned == 0
    assert landscape.total_found == 0
    assert landscape.hits == []
    assert landscape.no_match_statement == NO_MATCH_STATEMENT
    assert "not evidence of novelty" in landscape.no_match_statement


@pytest.mark.asyncio
async def test_a_404_that_is_not_a_no_match_answer_degrades_instead_of_reporting_zero_hits() -> (
    None
):
    """A 404 from a moved endpoint must never read as "no prior art found"."""
    service, _ = make_service(status_handler(404))

    landscape = await service.search(PatentSearch(keywords="salicylate"))
    await service.aclose()

    assert landscape.source_available is False
    assert landscape.no_match_statement == ""
    assert "did not answer" in landscape.source_status


@pytest.mark.asyncio
async def test_a_404_with_an_unreadable_body_degrades_too() -> None:
    service, _ = make_service(lambda _query: httpx.Response(404, text="<html>gone</html>"))

    landscape = await service.search(PatentSearch(keywords="salicylate"))
    await service.aclose()

    assert landscape.source_available is False
    assert landscape.no_match_statement == ""


@pytest.mark.asyncio
async def test_an_unconfigured_key_reports_the_source_unavailable_without_calling_upstream() -> (
    None
):
    service, transport = make_service(fixture_handler("search_page1.json"), api_key="")

    landscape = await service.search(PatentSearch(keywords="salicylate"))
    await service.aclose()

    assert transport.requests == []
    assert landscape.source_available is False
    assert "requires a free API key" in landscape.source_status
    assert landscape.hits == []
    assert landscape.total_found is None
    # No search ran, so nothing may be described as "no matches found".
    assert landscape.no_match_statement == ""
    # The derived query is still reported, so the UI can show what would have been searched.
    assert landscape.query.query_used == "+salicylate"


@pytest.mark.parametrize("status_code", [401, 403, 404, 429, 500, 503])
@pytest.mark.asyncio
async def test_upstream_failures_degrade_to_an_unavailable_source(status_code: int) -> None:
    service, _ = make_service(status_handler(status_code))

    landscape = await service.search(PatentSearch(keywords="salicylate"))
    await service.aclose()

    assert landscape.source_available is False
    assert landscape.hits == []
    assert landscape.no_match_statement == ""
    assert "Nothing below is a search result" in landscape.source_status


@pytest.mark.asyncio
async def test_a_timeout_degrades_to_an_unavailable_source() -> None:
    service, _ = make_service(timeout_handler())

    landscape = await service.search(PatentSearch(keywords="salicylate"))
    await service.aclose()

    assert landscape.source_available is False
    assert "was unreachable" in landscape.source_status


@pytest.mark.asyncio
async def test_an_unparseable_body_degrades_rather_than_raising() -> None:
    service, _ = make_service(json_handler(["not", "an", "object"]))

    landscape = await service.search(PatentSearch(keywords="salicylate"))
    await service.aclose()

    assert landscape.source_available is False
    assert landscape.hits == []


@pytest.mark.asyncio
async def test_a_rejected_query_raises_because_it_is_our_bug_not_an_outage() -> None:
    service, _ = make_service(status_handler(400))

    with pytest.raises(PatentRequestError):
        await service.search(PatentSearch(keywords="salicylate"))
    await service.aclose()


@pytest.mark.asyncio
async def test_retries_are_spaced_by_backoff_on_a_retryable_status(no_sleep: list[float]) -> None:
    service, transport = make_service(status_handler(503), max_attempts=3)
    service.client.base_delay = 0.5

    await service.search(PatentSearch(keywords="salicylate"))
    await service.aclose()

    assert len(transport.requests) == 3
    # The sub-millisecond sleeps are the rate limiter's spacing; the backoff is the rest.
    assert [round(delay, 3) for delay in no_sleep if delay >= 0.1] == [0.5, 1.0]


@pytest.mark.asyncio
async def test_a_client_error_is_not_retried() -> None:
    service, transport = make_service(status_handler(404), max_attempts=3)

    await service.search(PatentSearch(keywords="salicylate"))
    await service.aclose()

    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_the_outbound_rate_limiter_spaces_requests(no_sleep: list[float]) -> None:
    service, _ = make_service(fixture_handler("search_page1.json"), rate_limiter=RateLimiter(2.0))

    await service.search(PatentSearch(keywords="salicylate"))
    await service.search(PatentSearch(keywords="prodrug"))
    await service.aclose()

    assert any(delay > 0 for delay in no_sleep)


@pytest.mark.asyncio
async def test_from_settings_leaves_the_source_unavailable_without_a_key() -> None:
    # An explicit empty key rather than the ambient settings, so a key in a developer's local
    # .env cannot make this pass or fail for the wrong reason.
    settings = get_settings().model_copy(update={"uspto_odp_api_key": ""})
    service = PatentsService.from_settings(settings)

    assert service.client.configured is False
    assert service.client.base_url == "https://api.uspto.gov/api/v1"
    await service.aclose()


def test_params_carry_paging_and_the_sort_expression() -> None:
    search = PatentSearch(
        keywords="salicylate", page_size=10, offset=20, sort=PatentSort.FILING_DATE_DESC
    )

    params = build_params(search, build_query(search).query_used)

    assert params == {
        "q": "+salicylate",
        "limit": "10",
        "offset": "20",
        "sort": "applicationMetaData.filingDate desc",
    }


def test_relevance_sort_sends_no_sort_expression() -> None:
    params = build_params(PatentSearch(keywords="salicylate"), "salicylate")

    assert "sort" not in params
    assert params["limit"] == "25"
    assert params["offset"] == "0"


def test_a_date_filter_becomes_a_bounded_range_filter() -> None:
    search = PatentSearch(
        keywords="salicylate", filed_from=date(2015, 1, 1), filed_to=date(2020, 12, 31)
    )

    params = build_params(search, "salicylate")

    assert params["rangeFilters"] == "applicationMetaData.filingDate 2015-01-01:2020-12-31"


def test_a_one_sided_date_filter_is_widened_rather_than_dropped() -> None:
    from_only = build_params(PatentSearch(keywords="x1", filed_from=date(2015, 1, 1)), "x1")
    to_only = build_params(PatentSearch(keywords="x1", filed_to=date(2015, 1, 1)), "x1")

    assert from_only["rangeFilters"].endswith("2015-01-01:9999-12-31")
    assert to_only["rangeFilters"].endswith("1790-01-01:2015-01-01")


def test_an_inverted_date_range_is_rejected() -> None:
    search = PatentSearch(
        keywords="salicylate", filed_from=date(2021, 1, 1), filed_to=date(2019, 1, 1)
    )

    with pytest.raises(InvalidFilterError):
        build_query(search)


def test_out_of_range_paging_is_rejected_by_the_service_too() -> None:
    search = PatentSearch.model_construct(
        smiles="", keywords="salicylate", sort=PatentSort.RELEVANCE, page_size=500, offset=0
    )

    with pytest.raises(InvalidFilterError):
        build_query(search)


def test_a_client_without_a_key_refuses_to_request() -> None:
    assert UsptoOdpClient(api_key="").configured is False
