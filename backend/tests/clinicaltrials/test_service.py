from __future__ import annotations

import pytest

from app.services.clinicaltrials.client import ClinicalTrialsClient
from app.services.clinicaltrials.errors import (
    ClinicalTrialsRequestError,
    ClinicalTrialsResponseError,
    InvalidQueryError,
)
from app.services.clinicaltrials.models import TrialPhase, TrialSearch, TrialStatus
from app.services.clinicaltrials.service import ClinicalTrialsService
from app.services.rate_limit import RateLimiter
from tests.clinicaltrials.conftest import (
    Handler,
    RecordingTransport,
    error_response,
    fixture_response,
    json_response,
    transport_error,
)

pytestmark = pytest.mark.asyncio


def make_service(
    *handlers: Handler, max_attempts: int = 1
) -> tuple[ClinicalTrialsService, RecordingTransport]:
    transport = RecordingTransport(*handlers)
    client = ClinicalTrialsClient(
        transport=transport, rate_limiter=RateLimiter(1000.0), max_attempts=max_attempts
    )
    return ClinicalTrialsService(client), transport


async def test_combined_filters_are_sent_together() -> None:
    service, transport = make_service(fixture_response("search_page1.json"))

    await service.search(
        TrialSearch(
            sponsor="Merck",
            condition="melanoma",
            intervention="pembrolizumab",
            phases=[TrialPhase.PHASE3],
            statuses=[TrialStatus.ACTIVE_NOT_RECRUITING],
        ),
        page_size=2,
    )

    query = transport.queries[0]
    assert query["query.spons"] == ["Merck"]
    assert query["query.cond"] == ["melanoma"]
    assert query["query.intr"] == ["pembrolizumab"]
    assert query["filter.advanced"] == ["AREA[Phase]PHASE3"]
    assert query["filter.overallStatus"] == ["ACTIVE_NOT_RECRUITING"]
    assert query["pageSize"] == ["2"]
    assert query["countTotal"] == ["true"]
    assert "pageToken" not in query


async def test_search_normalizes_a_page_of_results() -> None:
    service, _ = make_service(fixture_response("search_page1.json"))

    page = await service.search(TrialSearch(condition="melanoma"), page_size=2)

    assert page.total_count == 29
    assert [trial.nct_id for trial in page.trials] == ["NCT03553836", "NCT04657991"]
    assert page.has_more is True
    assert page.trials[1].sponsor == "Pfizer"


async def test_sponsor_filter_returns_a_trial_with_no_reported_phase() -> None:
    service, transport = make_service(fixture_response("search_sponsor.json"))

    page = await service.search(
        TrialSearch(sponsor="Pfizer", statuses=[TrialStatus.RECRUITING]), page_size=1
    )

    assert transport.queries[0]["query.spons"] == ["Pfizer"]
    trial = page.trials[0]
    assert trial.sponsor == "Pfizer"
    assert trial.phases == []
    assert trial.phase_label == "N/A"
    assert trial.status is TrialStatus.RECRUITING


async def test_pagination_carries_the_cursor_into_the_next_request() -> None:
    service, transport = make_service(
        fixture_response("search_page1.json"), fixture_response("search_page2.json")
    )
    search = TrialSearch(condition="melanoma", intervention="pembrolizumab")

    first = await service.search(search, page_size=2)
    second = await service.search(search, page_size=2, page_token=first.next_page_token)

    assert transport.queries[1]["pageToken"] == [first.next_page_token]
    assert [trial.nct_id for trial in second.trials] == ["NCT02752074", "NCT06320353"]
    assert set(t.nct_id for t in first.trials).isdisjoint(t.nct_id for t in second.trials)


async def test_iter_pages_stops_when_the_cursor_runs_out() -> None:
    last_page = {"totalCount": 3, "studies": [{"protocolSection": {}}]}
    service, transport = make_service(
        fixture_response("search_page1.json"), json_response(last_page)
    )

    pages = [page async for page in service.iter_pages(TrialSearch(condition="melanoma"))]

    assert len(pages) == 2
    assert len(transport.requests) == 2
    assert pages[-1].has_more is False


async def test_iter_pages_respects_max_pages() -> None:
    service, transport = make_service(fixture_response("search_page1.json"))

    pages = [
        page async for page in service.iter_pages(TrialSearch(condition="melanoma"), max_pages=3)
    ]

    assert len(pages) == 3
    assert len(transport.requests) == 3


async def test_empty_result_set_is_a_page_not_an_error() -> None:
    service, _ = make_service(fixture_response("search_empty.json"))

    page = await service.search(TrialSearch(condition="zzzznotarealcondition"))

    assert page.trials == []
    assert page.total_count == 0
    assert page.has_more is False


async def test_search_without_filters_is_rejected_before_any_request() -> None:
    service, transport = make_service(fixture_response("search_page1.json"))

    with pytest.raises(InvalidQueryError):
        await service.search(TrialSearch())
    assert transport.requests == []


@pytest.mark.parametrize("page_size", [0, 101])
async def test_out_of_range_page_size_is_rejected(page_size: int) -> None:
    service, _ = make_service(fixture_response("search_page1.json"))

    with pytest.raises(InvalidQueryError):
        await service.search(TrialSearch(condition="melanoma"), page_size=page_size)


async def test_rejected_filter_expression_surfaces_as_invalid_query() -> None:
    service, _ = make_service(error_response(400, "Error parsing query in advanced filter"))

    with pytest.raises(InvalidQueryError, match="advanced filter"):
        await service.search(TrialSearch(condition="melanoma"))


async def test_server_error_is_retried_then_reported(no_sleep: list[float]) -> None:
    service, transport = make_service(error_response(503), max_attempts=3)

    with pytest.raises(ClinicalTrialsRequestError) as excinfo:
        await service.search(TrialSearch(condition="melanoma"))

    assert excinfo.value.status_code == 503
    assert len(transport.requests) == 3
    assert [delay for delay in no_sleep if delay >= 0.5] == [0.5, 1.0]


async def test_transport_failure_is_retried_and_can_succeed() -> None:
    service, transport = make_service(
        transport_error(), fixture_response("search_page1.json"), max_attempts=3
    )

    page = await service.search(TrialSearch(condition="melanoma"), page_size=2)

    assert len(transport.requests) == 2
    assert len(page.trials) == 2


async def test_client_error_is_not_retried() -> None:
    service, transport = make_service(error_response(404), max_attempts=3)

    with pytest.raises(ClinicalTrialsRequestError):
        await service.search(TrialSearch(condition="melanoma"))
    assert len(transport.requests) == 1


async def test_unparseable_payload_is_a_response_error() -> None:
    service, _ = make_service(json_response({"unexpected": True}))

    with pytest.raises(ClinicalTrialsResponseError):
        await service.search(TrialSearch(condition="melanoma"))
