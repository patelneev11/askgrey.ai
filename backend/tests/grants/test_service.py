from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from app.services.grants.errors import GrantsResponseError, InvalidQueryError
from app.services.grants.models import GrantProgram, GrantSearch, GrantSource, GrantStatus
from tests.grants.conftest import (
    TODAY,
    Handler,
    error_response,
    fixture_response,
    json_response,
    make_service,
    transport_error,
)

pytestmark = pytest.mark.asyncio

GRANTS_ONLY = [GrantSource.GRANTS_GOV]
SBIR_ONLY = [GrantSource.SBIR]


def sbir_page() -> Handler:
    return fixture_response("sbir_solicitations.json")


async def test_keyword_and_agency_are_sent_to_both_providers() -> None:
    service, transport = make_service(
        search2=fixture_response("search2_nih_sbir.json"),
        solicitations=sbir_page(),
        enrich_limit=0,
    )

    await service.search(GrantSearch(keyword="organoid", agency="HHS"), page_size=5)

    payload = transport.payloads("search2")[0]
    assert payload["keyword"] == "organoid"
    assert payload["agencies"] == "HHS"
    assert payload["oppStatuses"] == "posted"
    assert payload["rows"] == 5

    query = transport.queries("solicitations")[0]
    assert query == {
        "rows": ["5"],
        "start": ["0"],
        "keyword": ["organoid"],
        "agency": ["HHS"],
        "open": ["1"],
    }
    await service.aclose()


async def test_agency_alias_is_translated_per_provider() -> None:
    service, transport = make_service(
        search2=fixture_response("search2_nih_sbir.json"),
        solicitations=sbir_page(),
        enrich_limit=0,
    )

    await service.search(GrantSearch(keyword="biothreat", agency="Department of Defense"))

    assert transport.payloads("search2")[0]["agencies"] == "DOD"
    # SBIR.gov calls the same department DOW.
    assert transport.queries("solicitations")[0]["agency"] == ["DOW"]
    await service.aclose()


async def test_sub_agency_filter_is_reported_rather_than_silently_widened_on_sbir() -> None:
    service, transport = make_service(
        search2=fixture_response("search2_nih_sbir.json"), enrich_limit=0
    )

    page = await service.search(GrantSearch(keyword="sbir", agency="NIH"))

    sbir_status = next(item for item in page.sources if item.source is GrantSource.SBIR)
    assert sbir_status.ok is False
    assert "cannot filter by 'NIH'" in sbir_status.error
    assert transport.queries("solicitations") == []
    # The grants.gov half of the search still returns results.
    assert page.opportunities
    await service.aclose()


async def test_open_only_requests_posted_opportunities_and_drops_expired_ones() -> None:
    service, transport = make_service(
        search2=fixture_response("search2_nih_sbir.json"),
        solicitations=sbir_page(),
        enrich_limit=0,
    )

    page = await service.search(GrantSearch(keyword="sbir", agency="HHS"))

    assert transport.payloads("search2")[0]["oppStatuses"] == "posted"
    assert transport.queries("solicitations")[0]["open"] == ["1"]
    # The archived 2025 NASA solicitation in the fixture closed before TODAY.
    assert all(item.status is not GrantStatus.CLOSED for item in page.opportunities)
    assert "NASA SBIR 2025 Phase I (archived)" not in [item.title for item in page.opportunities]
    await service.aclose()


async def test_closed_opportunities_are_kept_when_open_only_is_off() -> None:
    service, transport = make_service(solicitations=sbir_page(), enrich_limit=0)

    page = await service.search(
        GrantSearch(keyword="sbir", agency="HHS", open_only=False, sources=SBIR_ONLY)
    )

    assert "open" not in transport.queries("solicitations")[0]
    assert any(item.status is GrantStatus.CLOSED for item in page.opportunities)
    await service.aclose()


async def test_closing_date_window_filters_locally() -> None:
    service, _ = make_service(solicitations=sbir_page(), enrich_limit=0)

    page = await service.search(
        GrantSearch(
            keyword="sbir",
            agency="HHS",
            closing_after=date(2026, 10, 1),
            closing_before=date(2026, 10, 31),
            sources=SBIR_ONLY,
        )
    )

    assert [item.close_date for item in page.opportunities] == [date(2026, 10, 27)]
    await service.aclose()


async def test_program_filter_keeps_combined_sbir_sttr_solicitations() -> None:
    service, _ = make_service(search2=fixture_response("search2_nih_sbir.json"), enrich_limit=0)

    page = await service.search(
        GrantSearch(keyword="sbir", program=GrantProgram.STTR, sources=GRANTS_ONLY)
    )

    programs = {item.program for item in page.opportunities}
    assert programs == {GrantProgram.STTR, GrantProgram.BOTH}
    await service.aclose()


async def test_results_are_ordered_by_soonest_deadline() -> None:
    service, _ = make_service(search2=fixture_response("search2_nih_sbir.json"), enrich_limit=0)

    page = await service.search(GrantSearch(keyword="sbir", sources=GRANTS_ONLY))

    deadlines = [item.close_date for item in page.opportunities if item.close_date]
    assert len(deadlines) == len(page.opportunities)
    assert deadlines == sorted(deadlines)
    await service.aclose()


async def test_enrichment_adds_topic_text_and_leaves_failed_details_summary_only() -> None:
    def flaky_fetch(request: httpx.Request) -> httpx.Response:
        opportunity_id = json.loads(request.content.decode())["opportunityId"]
        if opportunity_id == 359671:
            return httpx.Response(500, text="detail unavailable")
        return httpx.Response(200, json={"errorcode": 0, "data": {"synopsis": {}}})

    service, transport = make_service(
        search2=fixture_response("search2_nih_sbir.json"), fetch=flaky_fetch
    )

    page = await service.search(GrantSearch(keyword="sbir", sources=GRANTS_ONLY), page_size=5)

    assert len(transport.payloads("fetchOpportunity")) == 5
    assert len(page.opportunities) == 5
    failed = next(item for item in page.opportunities if item.opportunity_id == "359671")
    assert failed.topic_description == ""
    assert failed.title.startswith("NIH, CDC and FDA")
    await service.aclose()


async def test_pagination_offsets_each_provider() -> None:
    service, transport = make_service(
        search2=fixture_response("search2_nih_sbir.json"),
        solicitations=sbir_page(),
        enrich_limit=0,
    )

    await service.search(GrantSearch(keyword="sbir", agency="HHS"), page=2, page_size=10)

    assert transport.payloads("search2")[0]["startRecordNum"] == 20
    assert transport.queries("solicitations")[0]["start"] == ["20"]
    await service.aclose()


async def test_empty_results_produce_an_empty_page_not_an_error() -> None:
    service, _ = make_service(
        search2=json_response({"errorcode": 0, "data": {"hitCount": 0, "oppHits": []}}),
        solicitations=json_response([]),
        enrich_limit=0,
    )

    page = await service.search(GrantSearch(keyword="obscure", agency="HHS"))

    assert page.opportunities == []
    assert page.total_count == 0
    assert all(status.ok for status in page.sources)
    await service.aclose()


@pytest.mark.parametrize(
    "search",
    [
        GrantSearch(),
        GrantSearch(keyword="sbir", sources=[]),
        GrantSearch(
            keyword="sbir", closing_after=date(2027, 1, 1), closing_before=date(2026, 1, 1)
        ),
    ],
)
async def test_contradictory_or_empty_filters_are_rejected(search: GrantSearch) -> None:
    service, transport = make_service()

    with pytest.raises(InvalidQueryError):
        await service.search(search)

    assert transport.requests == []
    await service.aclose()


@pytest.mark.parametrize(("page", "page_size"), [(-1, 25), (0, 0), (0, 500)])
async def test_pagination_bounds_are_enforced(page: int, page_size: int) -> None:
    service, _ = make_service()

    with pytest.raises(InvalidQueryError):
        await service.search(GrantSearch(keyword="sbir"), page=page, page_size=page_size)
    await service.aclose()


async def test_one_provider_failing_degrades_the_page_instead_of_failing_it() -> None:
    service, _ = make_service(
        search2=error_response(503),
        solicitations=sbir_page(),
        enrich_limit=0,
    )

    page = await service.search(GrantSearch(keyword="sbir", agency="HHS"))

    grants_gov = next(item for item in page.sources if item.source is GrantSource.GRANTS_GOV)
    sbir = next(item for item in page.sources if item.source is GrantSource.SBIR)
    assert grants_gov.ok is False and "503" in grants_gov.error
    assert sbir.ok is True and sbir.returned > 0
    assert page.opportunities
    await service.aclose()


async def test_a_waf_block_on_sbir_is_reported_per_source() -> None:
    """SBIR.gov answers some hosting ranges with a CloudFront 403 despite being keyless."""
    service, _ = make_service(
        search2=fixture_response("search2_nih_sbir.json"),
        solicitations=error_response(403, '{"message":"Forbidden"}'),
        enrich_limit=0,
    )

    page = await service.search(GrantSearch(keyword="sbir", agency="HHS"))

    sbir = next(item for item in page.sources if item.source is GrantSource.SBIR)
    assert sbir.ok is False and "403" in sbir.error
    assert page.opportunities
    await service.aclose()


async def test_both_providers_failing_yields_an_empty_page_with_both_errors() -> None:
    service, _ = make_service(
        search2=transport_error(), solicitations=error_response(500), enrich_limit=0
    )

    page = await service.search(GrantSearch(keyword="sbir", agency="HHS"))

    assert page.opportunities == []
    assert [status.ok for status in page.sources] == [False, False]
    await service.aclose()


async def test_application_level_failure_with_http_200_is_treated_as_an_error() -> None:
    service, _ = make_service(
        search2=json_response({"errorcode": 1, "msg": "Invalid agency", "data": {}}),
        enrich_limit=0,
    )

    page = await service.search(GrantSearch(keyword="sbir", sources=GRANTS_ONLY))

    assert page.sources[0].ok is False
    assert "Invalid agency" in page.sources[0].error
    await service.aclose()


@pytest.mark.parametrize(
    "handler",
    [
        json_response({"errorcode": 0, "data": []}),
        json_response(["not an object"]),
        lambda _request: httpx.Response(200, text="<html>maintenance</html>"),
    ],
)
async def test_malformed_grants_gov_payloads_are_reported_not_raised(handler: object) -> None:
    service, _ = make_service(search2=handler, enrich_limit=0)  # type: ignore[arg-type]

    page = await service.search(GrantSearch(keyword="sbir", sources=GRANTS_ONLY))

    assert page.opportunities == []
    assert page.sources[0].ok is False
    await service.aclose()


async def test_malformed_sbir_payload_is_reported_not_raised() -> None:
    service, _ = make_service(solicitations=json_response({"message": "Forbidden"}), enrich_limit=0)

    page = await service.search(GrantSearch(keyword="sbir", agency="HHS", sources=SBIR_ONLY))

    assert page.sources[0].ok is False
    await service.aclose()


async def test_retryable_failures_are_retried_then_succeed(no_sleep: list[float]) -> None:
    service, transport = make_service(
        search2=[
            error_response(503),
            error_response(429),
            fixture_response("search2_nih_sbir.json"),
        ],
        max_attempts=3,
        enrich_limit=0,
    )

    page = await service.search(GrantSearch(keyword="sbir", sources=GRANTS_ONLY))

    assert len(transport.payloads("search2")) == 3
    assert page.sources[0].ok is True
    assert no_sleep  # backoff waited between attempts
    await service.aclose()


async def test_non_retryable_failures_are_not_retried(no_sleep: list[float]) -> None:
    service, transport = make_service(
        search2=[error_response(400), fixture_response("search2_nih_sbir.json")],
        max_attempts=3,
        enrich_limit=0,
    )

    page = await service.search(GrantSearch(keyword="sbir", sources=GRANTS_ONLY))

    assert len(transport.payloads("search2")) == 1
    assert page.sources[0].ok is False
    await service.aclose()


async def test_fetch_opportunity_rejects_a_non_numeric_id() -> None:
    service, _ = make_service()

    with pytest.raises(GrantsResponseError):
        await service.grants_gov.fetch_opportunity("PA-27-100")
    await service.aclose()


async def test_match_ranks_the_filtered_pool_and_reports_source_health() -> None:
    service, _ = make_service(
        search2=error_response(503),
        solicitations=sbir_page(),
        enrich_limit=0,
    )

    result = await service.match(
        "Automated potency assays for autologous cell therapy release testing",
        GrantSearch(keyword="sbir", agency="HHS"),
        limit=1,
        candidate_pool=10,
    )

    assert result.matcher == "lexical"
    assert result.candidates_considered == 2
    assert len(result.matches) == 1
    assert result.matches[0].opportunity.number == "PHS-2027-1"
    assert any(status.ok is False for status in result.sources)
    await service.aclose()


async def test_match_rejects_an_empty_focus_before_calling_a_provider() -> None:
    service, transport = make_service()

    with pytest.raises(InvalidQueryError):
        await service.match("   ", GrantSearch(keyword="sbir"))

    assert transport.requests == []
    await service.aclose()


async def test_match_returns_no_matches_when_the_filters_find_nothing() -> None:
    service, _ = make_service(
        search2=json_response({"errorcode": 0, "data": {"hitCount": 0, "oppHits": []}}),
        solicitations=json_response([]),
        enrich_limit=0,
    )

    result = await service.match("mRNA oncology", GrantSearch(keyword="sbir", agency="HHS"))

    assert result.matches == []
    assert result.candidates_considered == 0
    await service.aclose()


async def test_opportunities_are_dated_against_the_pinned_today() -> None:
    service, _ = make_service(solicitations=sbir_page(), enrich_limit=0)

    page = await service.search(
        GrantSearch(keyword="sbir", agency="HHS", open_only=False, sources=SBIR_ONLY)
    )

    soonest = page.opportunities[0]
    assert soonest.close_date is not None
    assert soonest.days_until_close(TODAY) == (soonest.close_date - TODAY).days
    await service.aclose()
