from __future__ import annotations

import pytest

from app.services.pdf_extraction import (
    CellStatus,
    ExtractionField,
    ExtractionRequestError,
    ExtractorError,
    ExtractorUnavailableError,
    ParsedDocument,
    PdfExtractionService,
    RawDataPoint,
    RowStatus,
    fields_from_goal,
)
from app.services.records import RecordSource
from tests.pdf_extraction.conftest import StubExtractor, fixture_bytes, parse_fixture

pytestmark = pytest.mark.asyncio

GOAL = "sample size, dosing regimen, primary efficacy endpoint"
SAMPLE_SIZE_QUOTE = "73 patients were randomized in a double-blinded, placebo-controlled study"
DOSING_QUOTE = "ziprasidone (40-160 mg/d) or"
ENDPOINT_QUOTE = "The primary outcome analysis indicated efficacy of ziprasidone versus placebo"


def points() -> list[RawDataPoint]:
    return [
        RawDataPoint(field="sample_size", value="73 patients", quote=SAMPLE_SIZE_QUOTE),
        RawDataPoint(field="dosing_regimen", value="40-160 mg/d", quote=DOSING_QUOTE),
        RawDataPoint(
            field="primary_efficacy_endpoint",
            value="MADRS response, p = 0.0038",
            quote=ENDPOINT_QUOTE,
        ),
    ]


def service(*args: RawDataPoint, error: Exception | None = None) -> PdfExtractionService:
    return PdfExtractionService(StubExtractor(*args, error=error))


async def test_every_cell_carries_a_citation(ziprasidone: ParsedDocument) -> None:
    table = await service(*points()).extract_from_bytes(
        fixture_bytes("trial_ziprasidone"), goal=GOAL, filename="trial.pdf"
    )

    assert [column.key for column in table.columns] == [
        "sample_size",
        "dosing_regimen",
        "primary_efficacy_endpoint",
    ]
    row = table.rows[0]
    assert row.status is RowStatus.EXTRACTED
    assert row.document_id == ziprasidone.document_id
    assert row.page_count == 3
    assert row.warnings == []
    for key in table.columns:
        cell = row.cells[key.key]
        assert cell.status is CellStatus.GROUNDED
        assert cell.value
        assert cell.citation is not None
        assert cell.citation.page_number >= 1
        assert cell.citation.rects


async def test_missing_field_becomes_an_empty_not_found_cell() -> None:
    table = await service(points()[0]).extract_from_bytes(
        fixture_bytes("trial_ziprasidone"), goal=GOAL
    )

    cell = table.rows[0].cells["dosing_regimen"]
    assert cell.status is CellStatus.NOT_FOUND
    assert cell.value is None
    assert cell.citation is None


async def test_unquotable_value_is_kept_but_marked_ungrounded() -> None:
    hallucinated = RawDataPoint(
        field="sample_size",
        value="4,812 patients",
        quote="4,812 astronauts were enrolled across nine lunar sites",
    )

    table = await service(hallucinated).extract_from_bytes(
        fixture_bytes("trial_ziprasidone"), goal="sample size"
    )

    cell = table.rows[0].cells["sample_size"]
    assert cell.status is CellStatus.UNGROUNDED
    assert cell.value == "4,812 patients"
    assert cell.citation is None
    assert table.rows[0].warnings == ["sample_size: quoted text was not found in the parsed PDF"]


async def test_scanned_pdf_is_rejected_before_the_llm_is_called() -> None:
    stub = StubExtractor(*points())

    with pytest.raises(Exception, match="no extractable text layer"):
        await PdfExtractionService(stub).extract_from_bytes(
            fixture_bytes("scanned_no_text_layer"), goal=GOAL
        )
    assert stub.calls == []


async def test_empty_goal_is_rejected() -> None:
    with pytest.raises(ExtractionRequestError):
        await service().extract_from_bytes(fixture_bytes("trial_ziprasidone"), goal="  ")


async def test_too_many_fields_are_rejected() -> None:
    fields = [ExtractionField(key=f"f{index}", label=f"f{index}") for index in range(26)]

    with pytest.raises(ExtractionRequestError):
        await service().extract_from_bytes(fixture_bytes("trial_ziprasidone"), fields=fields)


async def test_without_credentials_extraction_is_unavailable(ziprasidone: ParsedDocument) -> None:
    with pytest.raises(ExtractorUnavailableError):
        await PdfExtractionService(None).extract_row(ziprasidone, fields_from_goal(GOAL))


async def test_table_keeps_its_shape_when_one_paper_fails(ziprasidone: ParsedDocument) -> None:
    other = parse_fixture("trial_mipomersen")
    failing = PdfExtractionService(StubExtractor(error=ExtractorError("Claude returned HTTP 529")))

    table = await failing.extract_table([ziprasidone, other], goal=GOAL)

    assert len(table.rows) == 2
    assert {row.status for row in table.rows} == {RowStatus.FAILED}
    assert table.rows[0].cells == {}
    assert "529" in table.rows[0].warnings[0]


async def test_row_projects_into_the_shared_review_record() -> None:
    table = await service(*points()).extract_from_bytes(
        fixture_bytes("trial_ziprasidone"), goal=GOAL, source_url="https://example.org/paper.pdf"
    )

    record = table.rows[0].to_source_record()
    assert record.source is RecordSource.PDF
    assert record.url == "https://example.org/paper.pdf"
    assert record.fields["sample_size"] == "73 patients"


async def test_serialized_cell_is_value_plus_citation() -> None:
    table = await service(points()[0]).extract_from_bytes(
        fixture_bytes("trial_ziprasidone"), goal="sample size"
    )

    payload = table.model_dump(mode="json")
    cell = payload["rows"][0]["cells"]["sample_size"]
    assert cell["value"] == "73 patients"
    citation = cell["citation"]
    assert set(citation) == {
        "document_id",
        "source_url",
        "page_number",
        "page_width",
        "page_height",
        "block_id",
        "text",
        "start_char",
        "end_char",
        "bbox",
        "rects",
        "match",
    }
    assert set(citation["bbox"]) == {"x0", "top", "x1", "bottom"}
