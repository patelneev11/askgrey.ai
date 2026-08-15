from __future__ import annotations

import csv
import io

from app.services.pdf_extraction import ExtractionTable

from .layout import (
    CitationEntry,
    cell_of,
    cell_text,
    citation_entries,
    clean,
    escape_formula,
    leading_headers,
    paper_name,
    refs_by_cell,
    validate,
)
from .models import CSV_MEDIA_TYPE, ExportFile, ExportOptions

SOURCE_SUFFIX = " — source"
BOM = "\ufeff"


def _source_text(entry: CitationEntry | None) -> str:
    """
    Flatten a citation into one cell.

    CSV has nowhere to put a hyperlink or a comment, so the page and the supporting quote go
    inline — enough for a reader to find the passage by hand, which is the point of exporting
    citations at all.
    """
    if entry is None:
        return ""
    parts = [f"p{entry.page}"]
    if entry.quote:
        parts.append(f'"{entry.quote}"')
    if entry.match != "exact":
        parts.append(f"{entry.match} match")
    return " · ".join(parts)


def build_rows(table: ExtractionTable, options: ExportOptions) -> list[list[str]]:
    """The full grid, header row first. Shared with the tests, which assert on it directly."""
    validate(table, options)
    entries = refs_by_cell(citation_entries(table)) if options.include_citations else {}

    header = leading_headers(options)
    for column in table.columns:
        label = column.label or column.key
        header.append(label)
        if options.include_citations:
            header.append(label + SOURCE_SUFFIX)

    rows = [header]
    for row_index, row in enumerate(table.rows, start=1):
        record = [paper_name(row)]
        if options.include_metadata:
            record += [row.source_url, str(row.page_count), row.status.value]
        for column in table.columns:
            record.append(cell_text(cell_of(row, column.key)))
            if options.include_citations:
                record.append(_source_text(entries.get((row_index, column.key))))
        rows.append([escape_formula(clean(field)) for field in record])
    return rows


def write_csv(table: ExtractionTable, options: ExportOptions | None = None) -> ExportFile:
    """Render a review table as RFC 4180 CSV."""
    options = options or ExportOptions()
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerows(build_rows(table, options))

    text = (BOM if options.bom else "") + buffer.getvalue()
    return ExportFile(
        filename=f"{options.filename_stem}.csv",
        media_type=CSV_MEDIA_TYPE,
        content=text.encode("utf-8"),
    )
