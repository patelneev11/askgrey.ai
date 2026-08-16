from __future__ import annotations

from app.services.screening.patents import parse_record, parse_records, total_found
from tests.screening.patents.conftest import load_json_fixture


def test_parses_a_recorded_search_response() -> None:
    hits = parse_records(load_json_fixture("search_page1.json"))

    assert len(hits) == 3
    first = hits[0]
    assert first.application_number == "19389155"
    assert first.publication_number == "US20260137702A1"
    assert first.title == "Salicylate Compound Composition"
    assert first.filing_date == "2025-11-14"
    assert first.publication_date == "2026-05-21"
    assert first.status == "Docketed New Case - Ready for Examination"
    assert first.applicants == ["Innovate (EU) Limited"]
    assert first.inventors == ["James Stuart", "Simon Cohen", "Jan Cohen"]
    # Upstream pads CPC symbols to a fixed width; the padding is dropped, the symbol is not.
    assert first.cpc_classifications[:2] == ["A61K 31/616", "A61P 43/00"]
    assert first.url == "https://data.uspto.gov/ui/patent/applications/19389155"
    # Pending: the absent grant fields stay empty rather than being invented.
    assert first.patent_number == ""
    assert first.grant_date == ""


def test_parses_the_grant_fields_of_a_granted_record() -> None:
    hits = parse_records(load_json_fixture("search_granted.json"))

    assert (hits[0].patent_number, hits[0].grant_date) == ("12048708", "2024-07-30")
    assert hits[0].applicants == ["RHOSHAN PHARMACEUTICALS, INC."]
    assert hits[0].inventors == ["Nagesh R. PALEPU"]
    # The second record was published without a publication number in this dataset.
    assert hits[1].patent_number == "11911400"


def test_missing_metadata_yields_an_empty_hit_rather_than_a_guess() -> None:
    hit = parse_record({"applicationNumberText": "16000000"})

    assert hit.application_number == "16000000"
    assert hit.title == ""
    assert hit.applicants == []
    assert hit.url == "https://data.uspto.gov/ui/patent/applications/16000000"


def test_a_record_without_an_application_number_gets_no_url() -> None:
    assert parse_record({"applicationMetaData": {"inventionTitle": "Untitled"}}).url == ""


def test_unexpected_shapes_are_skipped_rather_than_raising() -> None:
    payload = {"patentFileWrapperDataBag": ["not-a-record", {"applicationNumberText": "1"}]}

    assert len(parse_records(payload)) == 1
    assert parse_records({"patentFileWrapperDataBag": {}}) == []
    assert parse_records({}) == []


def test_total_found_reads_the_whole_match_set_not_the_page() -> None:
    # `count: 7` over two returned records: the recorded proof that `count` is the total.
    granted = load_json_fixture("search_granted.json")
    assert len(granted["patentFileWrapperDataBag"]) == 2
    assert total_found(granted) == 7
    assert total_found(load_json_fixture("search_page1.json")) == 16
    assert total_found({"count": "16"}) == 16


def test_total_found_falls_back_to_the_other_odp_spelling() -> None:
    assert total_found({"totalNumFound": 37}) == 37


def test_total_found_is_none_when_upstream_reported_no_count() -> None:
    assert total_found({}) is None
    assert total_found({"count": True}) is None
    assert total_found({"count": "many"}) is None
