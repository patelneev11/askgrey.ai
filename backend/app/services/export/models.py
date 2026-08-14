from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"

# Excel's own hard limits. A table this size is a bug upstream, not a user request.
MAX_ROWS = 100_000
MAX_COLUMNS = 512


class ExportFormat(str, Enum):
    XLSX = "xlsx"
    CSV = "csv"


class ExportOptions(BaseModel):
    """Knobs that change the shape of the file, not its content."""

    # Cited papers are written to a second sheet (xlsx) or extra columns (csv). Turning this
    # off produces a plain values-only grid for pasting elsewhere.
    include_citations: bool = True
    # Per-paper columns that precede the extracted fields.
    include_metadata: bool = True
    # CSV only: prefix a UTF-8 BOM. Excel on Windows assumes the local codepage without it
    # and mangles every non-ASCII character; every other consumer tolerates the BOM.
    bom: bool = True
    filename_stem: str = Field(default="review-table", max_length=120)


class ExportFile(BaseModel):
    """A rendered file, ready to be streamed to the client."""

    filename: str
    media_type: str
    content: bytes

    @property
    def size(self) -> int:
        return len(self.content)
