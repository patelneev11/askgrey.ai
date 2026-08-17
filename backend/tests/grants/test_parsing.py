from __future__ import annotations

from datetime import date

import pytest

from app.services.grants.agencies import resolve_agency
from app.services.grants.grants_gov import apply_detail, parse_hit
from app.services.grants.models import GrantProgram, GrantStatus, ProgramProvenance
from app.services.grants.parsing import (
    clean_text,
    infer_program,
    parse_date,
    parse_money,
    parse_program,
    parse_status,
)
from app.services.grants.sbir import parse_solicitation
from app.services.records import RecordSource
from tests.grants.conftest import TODAY, load_fixture, search2_fixture


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("04/05/2027", date(2027, 4, 5)),
        ("2026-11-03", date(2026, 11, 3)),
        # fetchOpportunity appends a clock and timezone that strptime cannot read.
        ("Apr 05, 2027 12:00:00 AM EDT", date(2027, 4, 5)),
        ("September 30, 2026", date(2026, 9, 30)),
        ("none", None),
        ("", None),
        (None, None),
        ("not a date", None),
    ],
)
def test_parse_date_handles_every_shape_the_providers_publish(
    value: object, expected: date | None
) -> None:
    assert parse_date(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("450000", 450000), ("$1,500,000", 1500000), (275000, 275000), ("none", None), (None, None)],
)
def test_parse_money(value: object, expected: int | None) -> None:
    assert parse_money(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("SBIR", GrantProgram.SBIR),
        ("STTR", GrantProgram.STTR),
        ("BOTH", GrantProgram.BOTH),
        ("Innovative Research", GrantProgram.OTHER),
        ("", None),
    ],
)
def test_parse_program(value: str, expected: GrantProgram | None) -> None:
    assert parse_program(value) == expected


def test_infer_program_reads_the_set_aside_out_of_a_grants_gov_title() -> None:
    assert infer_program("Parent SBIR (R43/R44)") is GrantProgram.SBIR
    assert infer_program("Small Business Technology Transfer Grant") is GrantProgram.STTR
    assert infer_program("SBIR/STTR Commercialization Readiness Pilot") is GrantProgram.BOTH
    assert infer_program("Research Education Program") is None


def test_program_provenance_separates_a_stated_set_aside_from_an_inferred_one() -> None:
    hit = search2_fixture()["data"]["oppHits"][0]
    inferred = parse_hit(hit, TODAY)
    assert inferred.program is GrantProgram.SBIR
    assert inferred.program_provenance is ProgramProvenance.INFERRED
    assert inferred.program_label == "SBIR (inferred)"

    stated = parse_solicitation(load_fixture("sbir_solicitations.json")[0], TODAY)
    assert stated.program is not None
    assert stated.program_provenance is ProgramProvenance.STATED
    assert stated.program_label == stated.program.value


def test_no_program_carries_no_provenance() -> None:
    parsed = parse_hit({"id": "1", "title": "Research Education Program"}, TODAY)
    assert parsed.program is None
    assert parsed.program_provenance is None
    assert parsed.program_label == ""


def test_parse_status_falls_back_to_the_deadline_for_unknown_strings() -> None:
    assert parse_status("posted", None, TODAY) is GrantStatus.OPEN
    assert parse_status("archived", None, TODAY) is GrantStatus.CLOSED
    assert parse_status("", date(2026, 1, 1), TODAY) is GrantStatus.CLOSED
    assert parse_status("", date(2027, 1, 1), TODAY) is GrantStatus.OPEN
    assert parse_status("", None, TODAY) is None


def test_clean_text_strips_provider_markup() -> None:
    assert clean_text("<p>Phase&nbsp;I\n  awards</p>") == "Phase I awards"
    assert clean_text("Navigation &amp; Positioning") == "Navigation & Positioning"
    # Entities are unescaped after tag stripping, so escaped markup cannot become a live tag.
    assert clean_text("&lt;b&gt;bold&lt;/b&gt;") == "<b>bold</b>"
    assert clean_text("x" * 50, limit=10) == "x" * 10
    assert clean_text(None) == ""


def test_grants_gov_hit_normalizes_into_the_shared_schema() -> None:
    hit = search2_fixture()["data"]["oppHits"][0]

    parsed = parse_hit(hit, TODAY)

    assert parsed.opportunity_id == "359671"
    assert parsed.number == "PA-27-100"
    assert parsed.agency == "National Institutes of Health"
    assert parsed.agency_code == "HHS-NIH11"
    assert parsed.close_date == date(2027, 4, 5)
    assert parsed.status is GrantStatus.OPEN
    assert parsed.program is GrantProgram.SBIR
    assert parsed.url == "https://www.grants.gov/search-results-detail/359671"


def test_fetch_opportunity_detail_supplies_the_topic_text_search_omits() -> None:
    hit = search2_fixture()["data"]["oppHits"][0]
    detail = load_fixture("fetch_opportunity_359671.json")["data"]

    enriched = apply_detail(parse_hit(hit, TODAY), detail, TODAY)

    assert "Small Business Innovation Research" in enriched.topic_description
    assert enriched.posted_date == date(2026, 5, 28)
    assert enriched.close_date == date(2027, 4, 5)
    # NIH parent announcements publish no ceiling; "none" must not become 0.
    assert enriched.funding_ceiling is None


def test_enrichment_keeps_the_search_agency_over_the_synopsis_contact() -> None:
    # `synopsis.agencyName` is frequently the grantor contact person, so it may only fill a gap.
    hit = search2_fixture()["data"]["oppHits"][0]
    detail = load_fixture("fetch_opportunity_359671.json")["data"]
    detail["synopsis"]["agencyName"] = "Jane Doe"

    enriched = apply_detail(parse_hit(hit, TODAY), detail, TODAY)

    assert enriched.agency == "National Institutes of Health"

    unattributed = parse_hit({**hit, "agency": ""}, TODAY)
    assert apply_detail(unattributed, detail, TODAY).agency == "Jane Doe"


def test_fetch_opportunity_detail_carries_the_funding_ceiling_when_published() -> None:
    hit = {"id": "300997", "title": "MUSIC", "number": "NNH18ZHA002N-MUSIC"}
    detail = load_fixture("fetch_opportunity_300997.json")["data"]

    enriched = apply_detail(parse_hit(hit, TODAY), detail, TODAY)

    assert enriched.funding_ceiling == 450000
    assert enriched.funding_floor == 0
    assert enriched.funding_label == "$450,000"


def test_sbir_solicitation_normalizes_topics_into_one_matchable_description() -> None:
    solicitation = load_fixture("sbir_solicitations.json")[0]

    parsed = parse_solicitation(solicitation, TODAY)

    assert parsed.number == "PHS-2027-1"
    assert parsed.program is GrantProgram.SBIR
    assert parsed.branch == "NIH"
    assert parsed.posted_date == date(2026, 9, 1)
    # A topic due date earlier than the solicitation's own close date wins.
    assert parsed.close_date == date(2026, 10, 27)
    assert parsed.topics[:2] == [
        "Immunotherapy manufacturing platforms",
        "Potency assay automation",
    ]
    assert "closed-system bioreactors" in parsed.topic_description
    assert "shorten lot release" in parsed.topic_description


def test_sbir_solicitation_without_topics_still_normalizes() -> None:
    parsed = parse_solicitation(load_fixture("sbir_solicitations.json")[2], TODAY)

    assert parsed.topics == []
    assert parsed.topic_description == ""
    assert parsed.status is GrantStatus.CLOSED


def test_opportunity_projects_into_the_shared_review_row() -> None:
    detail = load_fixture("fetch_opportunity_359671.json")["data"]
    hit = search2_fixture()["data"]["oppHits"][0]

    record = apply_detail(parse_hit(hit, TODAY), detail, TODAY).to_source_record()

    assert record.source is RecordSource.GRANTS
    assert record.record_id == "grants_gov:359671"
    assert record.fields["Agency"] == "National Institutes of Health"
    assert record.fields["Deadline"] == "2027-04-05"
    # grants.gov publishes no set-aside field, so the export has to mark the guess as one.
    assert record.fields["Program"] == "SBIR (inferred)"


def test_agency_aliases_resolve_to_provider_specific_codes() -> None:
    nih = resolve_agency("nih")
    assert nih is not None and nih.grants_gov_codes == ["HHS-NIH11"]
    # SBIR.gov only knows departments, so NIH has no code there.
    assert nih.sbir_code == ""

    dod = resolve_agency("Department of Defense")
    assert dod is not None and dod.sbir_code == "DOW"

    barda = resolve_agency("BARDA")
    assert barda is not None and "HHS-ASPR" in barda.grants_gov_codes
    assert "ASPR" in barda.note

    # An unknown value is passed through as a literal provider code rather than rejected.
    unknown = resolve_agency("HHS-NIH99")
    assert unknown is not None and unknown.grants_gov_codes == ["HHS-NIH99"]


def test_program_values_are_accepted_in_any_case() -> None:
    # Callers type these into a query string, where "sbir" is the natural spelling.
    assert GrantProgram("sbir") is GrantProgram.SBIR
    assert GrantProgram(" Sttr ") is GrantProgram.STTR
    with pytest.raises(ValueError):
        GrantProgram("phase-iii")
