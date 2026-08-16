from __future__ import annotations


class ExportError(Exception):
    """Base class for every failure raised by the export service."""


class EmptyTableError(ExportError):
    """The table has no columns, so there is nothing to write."""


class TableTooLargeError(ExportError):
    """The table exceeds the row or column budget for a single workbook."""
