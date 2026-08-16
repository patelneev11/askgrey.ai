from __future__ import annotations

from app.services.pdf_extraction import (
    BoundingBox,
    CellStatus,
    Citation,
    ExtractionCell,
    ExtractionField,
    ExtractionTable,
    MatchQuality,
    PaperRow,
    RowStatus,
)

FIELDS = [
    ExtractionField(key="sample_size", label="sample size"),
    ExtractionField(key="dosing_regimen", label="dosing regimen"),
]


def citation(
    text: str = "73 patients were randomized",
    *,
    page: int = 1,
    match: MatchQuality = MatchQuality.EXACT,
    source_url: str = "https://example.org/paper.pdf",
) -> Citation:
    return Citation(
        document_id="doc-1",
        source_url=source_url,
        page_number=page,
        page_width=612.0,
        page_height=792.0,
        block_id=f"p{page}-b4",
        text=text,
        start_char=0,
        end_char=len(text),
        bbox=BoundingBox(x0=58.1, top=300.4, x1=296.1, bottom=312.2),
        rects=[BoundingBox(x0=58.1, top=300.4, x1=296.1, bottom=312.2)],
        match=match,
    )


def grounded(
    value: str,
    *,
    text: str = "73 patients were randomized",
    page: int = 1,
    match: MatchQuality = MatchQuality.EXACT,
) -> ExtractionCell:
    return ExtractionCell(
        value=value,
        citation=citation(text, page=page, match=match),
        status=CellStatus.GROUNDED,
    )


def ungrounded(value: str) -> ExtractionCell:
    return ExtractionCell(value=value, status=CellStatus.UNGROUNDED)


def paper(
    *,
    title: str = "A 6 Week Randomized Trial of Ziprasidone",
    document_id: str = "doc-1",
    source_url: str = "https://example.org/paper.pdf",
    cells: dict[str, ExtractionCell] | None = None,
    status: RowStatus = RowStatus.EXTRACTED,
) -> PaperRow:
    return PaperRow(
        document_id=document_id,
        title=title,
        source_url=source_url,
        filename="paper.pdf",
        page_count=3,
        status=status,
        cells=cells if cells is not None else {},
    )


def table(*rows: PaperRow, columns: list[ExtractionField] | None = None) -> ExtractionTable:
    return ExtractionTable(
        goal="sample size, dosing regimen",
        columns=columns if columns is not None else FIELDS,
        rows=list(rows),
    )


def sample_table() -> ExtractionTable:
    """Two papers: one fully cited, one with an unverified value and a missing cell."""
    return table(
        paper(
            cells={
                "sample_size": grounded("73 patients"),
                "dosing_regimen": grounded(
                    "40-160 mg/d for 6 weeks",
                    text="ziprasidone (40-160 mg/d) or placebo for 6 weeks",
                    page=2,
                ),
            }
        ),
        paper(
            title="Mipomersen in Familial Hypercholesterolaemia",
            document_id="doc-2",
            source_url="",
            cells={"sample_size": ungrounded("58 patients")},
        ),
    )
