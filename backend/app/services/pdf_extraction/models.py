from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field

from app.services.records import RecordSource, SourceRecord


class BoundingBox(BaseModel):
    """
    A rectangle in PDF-page coordinates, in points (1/72 inch).

    The origin is the **top-left** corner of the page and `top` grows downwards — this is
    pdfplumber's convention, and it matches how a browser lays out a rendered page, so a
    viewer only has to scale by `rendered_width / page_width` to place a highlight.
    """

    x0: float
    top: float
    x1: float
    bottom: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.bottom - self.top

    def union(self, other: BoundingBox) -> BoundingBox:
        return BoundingBox(
            x0=min(self.x0, other.x0),
            top=min(self.top, other.top),
            x1=max(self.x1, other.x1),
            bottom=max(self.bottom, other.bottom),
        )


class TextLine(BaseModel):
    """One physical line of a block, kept so a citation can be highlighted line by line."""

    text: str
    bbox: BoundingBox
    start_char: int
    end_char: int
    # x boundary of every character in `text`, length len(text) + 1. Used to narrow a
    # highlight to the exact characters of a quote; too large to be worth serializing.
    char_offsets: list[float] = Field(default_factory=list, exclude=True, repr=False)


class TextBlock(BaseModel):
    """
    A paragraph-sized run of lines sharing a column and separated from its neighbours by
    vertical whitespace. Blocks are the unit the LLM cites, and `block_id` is stable for a
    given file: `p<page>-b<index>`, both one-based within their scope.
    """

    block_id: str
    page_number: int
    text: str
    bbox: BoundingBox
    lines: list[TextLine] = Field(default_factory=list)


class PageInfo(BaseModel):
    """Page geometry, so a viewer can normalize citation boxes against its own rendering."""

    page_number: int
    width: float
    height: float
    block_count: int
    char_count: int


class ParsedDocument(BaseModel):
    """A PDF flattened into position-aware text blocks."""

    document_id: str
    source_url: str = ""
    filename: str = ""
    title: str = ""
    pages: list[PageInfo] = Field(default_factory=list)
    blocks: list[TextBlock] = Field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def char_count(self) -> int:
        return sum(page.char_count for page in self.pages)

    def block(self, block_id: str) -> TextBlock | None:
        for block in self.blocks:
            if block.block_id == block_id:
                return block
        return None

    def page(self, page_number: int) -> PageInfo | None:
        for page in self.pages:
            if page.page_number == page_number:
                return page
        return None


class MatchQuality(str, Enum):
    """How the quoted span was located in the parsed text."""

    EXACT = "exact"
    NORMALIZED = "normalized"
    FUZZY = "fuzzy"


class Citation(BaseModel):
    """
    A pointer from an extracted value back to the exact span it came from.

    **This schema is a stable frontend contract — fields are only ever added, never
    renamed or removed.** To highlight: open `source_url` (or the uploaded file behind
    `document_id`), scroll to `page_number`, and paint `rects` scaled by the page geometry
    in `page_width` / `page_height`. `bbox` is the union of `rects` and is enough on its own
    for a coarse scroll-to.
    """

    document_id: str
    source_url: str = ""
    page_number: int
    page_width: float
    page_height: float
    block_id: str
    text: str
    start_char: int
    end_char: int
    bbox: BoundingBox
    rects: list[BoundingBox] = Field(default_factory=list)
    match: MatchQuality = MatchQuality.EXACT


class CellStatus(str, Enum):
    """
    Outcome for one field on one paper.

    `GROUNDED` is the only status with a citation attached. `UNGROUNDED` means the model
    proposed a value whose quote could not be found in the parsed text — it is surfaced,
    never silently dropped, but must be rendered as unverified.
    """

    GROUNDED = "grounded"
    UNGROUNDED = "ungrounded"
    NOT_FOUND = "not_found"


class ExtractionCell(BaseModel):
    """One table cell: `{value, citation}` plus the provenance status of that pair."""

    value: str | None = None
    citation: Citation | None = None
    status: CellStatus = CellStatus.NOT_FOUND
    note: str = ""


class ExtractionField(BaseModel):
    """One user-requested column."""

    key: str
    label: str
    description: str = ""


class RowStatus(str, Enum):
    EXTRACTED = "extracted"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class PaperRow(BaseModel):
    """
    One paper's row in the Dynamic Column Generator table.

    `cells` is keyed by `ExtractionField.key`; a key missing from `cells` is equivalent to a
    `NOT_FOUND` cell.
    """

    document_id: str
    title: str = ""
    source_url: str = ""
    filename: str = ""
    page_count: int = 0
    status: RowStatus = RowStatus.EXTRACTED
    cells: dict[str, ExtractionCell] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    def to_source_record(self) -> SourceRecord:
        """Project into the shared review-table row used by the other providers."""
        return SourceRecord(
            source=RecordSource.PDF,
            record_id=self.document_id,
            title=self.title or self.filename,
            subtitle=f"{self.page_count} pages",
            url=self.source_url,
            fields={key: cell.value or "" for key, cell in self.cells.items()},
        )


class ExtractionTable(BaseModel):
    """Rows (papers) x columns (requested fields), the shape the frontend renders."""

    goal: str = ""
    columns: list[ExtractionField] = Field(default_factory=list)
    rows: list[PaperRow] = Field(default_factory=list)


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_GOAL_SPLIT = re.compile(r"[,;\n]| and (?=[a-z])")


def slugify(label: str) -> str:
    return _SLUG_STRIP.sub("_", label.strip().lower()).strip("_")


def fields_from_goal(goal: str) -> list[ExtractionField]:
    """
    Split a free-text extraction goal into columns.

    Splitting is deliberately deterministic (commas, semicolons, newlines, a trailing "and")
    rather than model-driven, so the same goal always produces the same column keys and a
    table can be re-run or extended without its columns shifting underneath the user.
    """
    fields: list[ExtractionField] = []
    seen: set[str] = set()
    for part in _GOAL_SPLIT.split(goal):
        label = " ".join(part.split())
        key = slugify(label)
        if not key or key in seen:
            continue
        seen.add(key)
        fields.append(ExtractionField(key=key, label=label))
    return fields
