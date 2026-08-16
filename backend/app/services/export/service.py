from __future__ import annotations

from app.services.pdf_extraction import ExtractionTable

from .csv_writer import write_csv
from .models import ExportFile, ExportFormat, ExportOptions
from .xlsx_writer import write_xlsx


class ExportService:
    """
    Renders a review table into a downloadable file.

    Stateless and synchronous: rendering is pure CPU over an in-memory table, with no I/O and
    nothing to configure, so unlike the provider services there is no `from_settings()` or
    client to close.
    """

    def render(
        self,
        table: ExtractionTable,
        fmt: ExportFormat,
        options: ExportOptions | None = None,
    ) -> ExportFile:
        options = options or ExportOptions()
        if fmt is ExportFormat.CSV:
            return write_csv(table, options)
        return write_xlsx(table, options)

    def xlsx(self, table: ExtractionTable, options: ExportOptions | None = None) -> ExportFile:
        return write_xlsx(table, options)

    def csv(self, table: ExtractionTable, options: ExportOptions | None = None) -> ExportFile:
        return write_csv(table, options)
