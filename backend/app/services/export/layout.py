from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.pdf_extraction import CellStatus, ExtractionCell, ExtractionTable, PaperRow

from .errors import EmptyTableError, TableTooLargeError
from .models import MAX_COLUMNS, MAX_ROWS, ExportOptions

# Excel refuses to open a workbook containing these, and they carry no meaning in exported
# prose anyway. \t \n \r are legal and preserved.
_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# A leading one of these makes Excel/Sheets evaluate the cell as a formula on open.
_FORMULA_LEAD = ("=", "+", "-", "@", "\t", "\r")

# Excel's per-cell character ceiling.
MAX_CELL_CHARS = 32_767
# Quotes are prose and can run long; keep the sources sheet readable.
MAX_QUOTE_CHARS = 1_000

METADATA_HEADERS = ("Paper", "Source", "Pages", "Row status")
SOURCES_HEADERS = (
    "Ref",
    "Paper",
    "Column",
    "Value",
    "Page",
    "Match",
    "Quote",
    "Block",
    "Position (x0, top, x1, bottom)",
    "Source",
)


def clean(text: str, *, limit: int = MAX_CELL_CHARS) -> str:
    """Strip characters no spreadsheet accepts, and cap length."""
    stripped = _ILLEGAL.sub("", text)
    if len(stripped) > limit:
        return stripped[: limit - 1] + "…"
    return stripped


def escape_formula(text: str) -> str:
    """
    Neutralize CSV formula injection by prefixing a quote.

    A cell reading `=HYPERLINK("http://…")` is executed on open by Excel, Sheets and
    LibreOffice, and an extracted value is untrusted text from a third-party PDF. The xlsx
    writer does not need this — it writes cells with an explicit string type instead, which
    preserves the text exactly.
    """
    if text.startswith(_FORMULA_LEAD):
        return "'" + text
    return text


@dataclass(frozen=True)
class CitationEntry:
    """One grounded cell, denormalized into a row of the sources sheet."""

    ref: str
    row_index: int
    column_key: str
    paper: str
    column_label: str
    value: str
    page: int
    match: str
    quote: str
    block_id: str
    position: str
    source_url: str

    def as_row(self) -> list[str | int]:
        return [
            self.ref,
            self.paper,
            self.column_label,
            self.value,
            self.page,
            self.match,
            self.quote,
            self.block_id,
            self.position,
            self.source_url,
        ]


def paper_name(row: PaperRow) -> str:
    return row.title or row.filename or row.document_id


def cell_of(row: PaperRow, key: str) -> ExtractionCell:
    """A key missing from `cells` is equivalent to a not-found cell."""
    return row.cells.get(key) or ExtractionCell()


def cell_text(cell: ExtractionCell) -> str:
    """
    Render a cell's value for a spreadsheet.

    An ungrounded value is marked inline: the file is read away from the app, where the
    `status` field is invisible, so unverified values must not look identical to cited ones.
    """
    if cell.value is None or not cell.value.strip():
        return ""
    if cell.status is CellStatus.UNGROUNDED:
        return f"{cell.value} (unverified)"
    return cell.value


def headers(table: ExtractionTable, options: ExportOptions) -> list[str]:
    leading = list(METADATA_HEADERS) if options.include_metadata else ["Paper"]
    return leading + [column.label or column.key for column in table.columns]


def validate(table: ExtractionTable, options: ExportOptions) -> None:
    if not table.columns and not options.include_metadata:
        raise EmptyTableError("table has no columns to export")
    if len(table.rows) > MAX_ROWS:
        raise TableTooLargeError(f"table has more than {MAX_ROWS} rows")
    if len(table.columns) > MAX_COLUMNS:
        raise TableTooLargeError(f"table has more than {MAX_COLUMNS} columns")


def citation_entries(table: ExtractionTable) -> list[CitationEntry]:
    """
    One entry per grounded cell, in reading order.

    Refs are positional (`C1`, `C2`, …) and stable for a given table, which is what lets the
    data sheet point at a sources row without duplicating the citation into every cell.
    """
    entries: list[CitationEntry] = []
    for row_index, row in enumerate(table.rows, start=1):
        for column in table.columns:
            cell = cell_of(row, column.key)
            citation = cell.citation
            if cell.status is not CellStatus.GROUNDED or citation is None:
                continue
            box = citation.bbox
            entries.append(
                CitationEntry(
                    ref=f"C{len(entries) + 1}",
                    row_index=row_index,
                    column_key=column.key,
                    paper=clean(paper_name(row)),
                    column_label=clean(column.label or column.key),
                    value=clean(cell.value or ""),
                    page=citation.page_number,
                    match=citation.match.value,
                    quote=clean(citation.text, limit=MAX_QUOTE_CHARS),
                    block_id=citation.block_id,
                    position=(f"{box.x0:.1f}, {box.top:.1f}, {box.x1:.1f}, {box.bottom:.1f}"),
                    source_url=clean(citation.source_url or row.source_url),
                )
            )
    return entries


def refs_by_cell(entries: list[CitationEntry]) -> dict[tuple[int, str], CitationEntry]:
    return {(entry.row_index, entry.column_key): entry for entry in entries}
