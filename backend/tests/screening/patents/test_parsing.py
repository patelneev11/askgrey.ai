from __future__ import annotations

from app.services.screening.patents import parse_record, parse_records, total_found
from tests.screening.patents.conftest import load_json_fixture


def test_parses_a_recorded_search_response() -> None:
    hits = parse_records(load_json_fixture("search_page1.json"))

    assert len(hits) == 2
    first, second = hits
    assert first.application_number == "16123456"
    assert first.patent_number == "10945998"
    assert first.publication_number == "US20200078317A1"
    assert first.title.startswith("Acetylsalicylic acid co-crystal")
    assert first.filing_date == "2018-09-06"
    assert first.grant_date == "2021-03-16"
    assert first.status == "Patented Case"
    assert first.applicants == ["Example Therapeutics, Inc."]
    assert first.inventors == ["Dana R. Whitfield", "Priya Raghavan"]
    assert first.cpc_classifications == ["A61K31/616", "C07C69/157"]
    assert first.url == "https://data.uspto.gov/ui/patent/applications/16123456"
    # Published but not granted: the absent fields stay empty rather than being invented.
    assert second.patent_number == ""
    assert second.grant_date == ""
    assert second.applicants == ["Example University"]
    assert second.cpc_classifications == ["A61K31/60"]


def test_missing_metadata_yields_an_empty_hit_rather_than_a_guess() -> None:
    hit = parse_record({"applicationNumberText": "16000000"})

    assert hit.application_number == "16000000"
    assert hit.title == ""
    assert hit.abstract == ""
    assert hit.applicants == []
    assert hit.url == "https://data.uspto.gov/ui/patent/applications/16000000"


def test_a_record_without_an_application_number_gets_no_url() -> None:
    assert parse_record({"applicationMetaData": {"inventionTitle": "Untitled"}}).url == ""


def test_unexpected_shapes_are_skipped_rather_than_raising() -> None:
    payload = {"patentFileWrapperDataBag": ["not-a-record", {"applicationNumberText": "1"}]}

    assert len(parse_records(payload)) == 1
    assert parse_records({"patentFileWrapperDataBag": {}}) == []
    assert parse_records({}) == []


def test_total_found_reads_the_upstream_count() -> None:
    assert total_found(load_json_fixture("search_page1.json")) == 37
    assert total_found({"totalNumFound": "37"}) == 37


def test_total_found_ignores_the_page_count() -> None:
    assert total_found({"count": 2}) is None


def test_total_found_is_none_when_upstream_reported_no_count() -> None:
    assert total_found({}) is None
    assert total_found({"totalNumFound": True}) is None
