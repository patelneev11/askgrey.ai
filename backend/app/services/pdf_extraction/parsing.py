from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import pdfplumber
from pdfplumber.page import Page

from .errors import PdfParseError, UnsupportedPdfError
from .models import BoundingBox, PageInfo, ParsedDocument, TextBlock, TextLine

PDF_MAGIC = b"%PDF-"

# A row of words is split into separate lines when the horizontal gap between them exceeds
# this many points — that gap is a column gutter, not a wide space.
COLUMN_GUTTER_POINTS = 24.0
# pdfplumber's default 3pt word tolerance glues whole sentences together in the tightly
# kerned two-column layouts these papers use; 1.5pt recovers the spaces without shredding
# words into fragments.
WORD_X_TOLERANCE = 1.5
# Words belong to the same row while their baselines sit within this many points.
ROW_TOLERANCE_POINTS = 3.0
# A vertical gap larger than this multiple of the line height starts a new block.
BLOCK_GAP_RATIO = 0.65
# A page with fewer characters than this has no usable text layer.
MIN_CHARS_PER_PAGE = 40


@dataclass
class _Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


def _looks_like_pdf(data: bytes) -> bool:
    return data[:1024].lstrip().startswith(PDF_MAGIC)


def document_id_for(data: bytes) -> str:
    """Content-addressed id, so re-uploading the same paper reuses its citations."""
    return hashlib.sha256(data).hexdigest()[:16]


def _page_words(page: Page) -> list[_Word]:
    words = page.extract_words(
        use_text_flow=False, keep_blank_chars=False, x_tolerance=WORD_X_TOLERANCE
    )
    parsed: list[_Word] = []
    for word in words:
        text = str(word.get("text", ""))
        if not text:
            continue
        parsed.append(
            _Word(
                text=text,
                x0=float(word["x0"]),
                x1=float(word["x1"]),
                top=float(word["top"]),
                bottom=float(word["bottom"]),
            )
        )
    return parsed


def _rows(words: list[_Word]) -> list[list[_Word]]:
    rows: list[list[_Word]] = []
    for word in sorted(words, key=lambda item: (round(item.top, 1), item.x0)):
        if rows and abs(word.top - rows[-1][0].top) <= ROW_TOLERANCE_POINTS:
            rows[-1].append(word)
        else:
            rows.append([word])
    return [sorted(row, key=lambda item: item.x0) for row in rows]


def _segments(row: list[_Word]) -> list[list[_Word]]:
    """Split a row wherever a column gutter interrupts it."""
    segments: list[list[_Word]] = [[row[0]]]
    for word in row[1:]:
        if word.x0 - segments[-1][-1].x1 > COLUMN_GUTTER_POINTS:
            segments.append([word])
        else:
            segments[-1].append(word)
    return segments


def _line_from_words(words: list[_Word], start_char: int) -> TextLine:
    text_parts: list[str] = []
    offsets: list[float] = []
    for index, word in enumerate(words):
        if index:
            # The synthetic space between two words spans the gap between their boxes.
            offsets.append(words[index - 1].x1)
            text_parts.append(" ")
        width = max(word.x1 - word.x0, 0.0)
        step = width / len(word.text)
        for position, char in enumerate(word.text):
            offsets.append(word.x0 + position * step)
            text_parts.append(char)
    offsets.append(words[-1].x1)
    text = "".join(text_parts)
    return TextLine(
        text=text,
        bbox=BoundingBox(
            x0=min(word.x0 for word in words),
            top=min(word.top for word in words),
            x1=max(word.x1 for word in words),
            bottom=max(word.bottom for word in words),
        ),
        start_char=start_char,
        end_char=start_char + len(text),
        char_offsets=offsets,
    )


def _column_index(line: TextLine, page_width: float) -> int:
    """0 for the left column and anything spanning the page, 1 for the right column."""
    return 1 if line.bbox.x0 > page_width / 2 else 0


def _group_into_blocks(
    lines: list[TextLine], page_number: int, page_width: float
) -> list[TextBlock]:
    ordered = sorted(lines, key=lambda line: (_column_index(line, page_width), line.bbox.top))
    blocks: list[TextBlock] = []
    current: list[TextLine] = []

    def flush() -> None:
        if not current:
            return
        offset = 0
        rebuilt: list[TextLine] = []
        for line in current:
            rebuilt.append(
                line.model_copy(update={"start_char": offset, "end_char": offset + len(line.text)})
            )
            offset += len(line.text) + 1
        bbox = rebuilt[0].bbox
        for line in rebuilt[1:]:
            bbox = bbox.union(line.bbox)
        blocks.append(
            TextBlock(
                block_id=f"p{page_number}-b{len(blocks) + 1}",
                page_number=page_number,
                text="\n".join(line.text for line in rebuilt),
                bbox=bbox,
                lines=rebuilt,
            )
        )
        current.clear()

    for line in ordered:
        if current:
            previous = current[-1]
            gap = line.bbox.top - previous.bbox.bottom
            same_column = _column_index(line, page_width) == _column_index(previous, page_width)
            height = max(previous.bbox.height, 1.0)
            if not same_column or gap > BLOCK_GAP_RATIO * height or gap < -height:
                flush()
        current.append(line)
    flush()
    return blocks


def _parse_page(page: Page, page_number: int) -> tuple[PageInfo, list[TextBlock]]:
    words = _page_words(page)
    lines: list[TextLine] = []
    for row in _rows(words):
        for segment in _segments(row):
            lines.append(_line_from_words(segment, 0))
    blocks = _group_into_blocks(lines, page_number, float(page.width))
    info = PageInfo(
        page_number=page_number,
        width=float(page.width),
        height=float(page.height),
        block_count=len(blocks),
        char_count=sum(len(block.text) for block in blocks),
    )
    return info, blocks


def parse_pdf(
    data: bytes,
    *,
    filename: str = "",
    source_url: str = "",
    max_pages: int | None = None,
) -> ParsedDocument:
    """
    Flatten a PDF into position-aware text blocks.

    Raises `UnsupportedPdfError` when the file is not a PDF or carries no text layer (a
    scanned page is an image; recovering its text needs OCR, which this module does not do),
    and `PdfParseError` when the file is a structurally broken PDF.
    """
    if not _looks_like_pdf(data):
        raise UnsupportedPdfError("file is not a PDF")

    pages: list[PageInfo] = []
    blocks: list[TextBlock] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                if max_pages is not None and index > max_pages:
                    break
                info, page_blocks = _parse_page(page, index)
                pages.append(info)
                blocks.extend(page_blocks)
    except UnsupportedPdfError:
        raise
    except Exception as exc:  # pdfminer raises a wide, undocumented range of errors
        raise PdfParseError(f"could not read the PDF: {exc}") from exc

    if not pages:
        raise UnsupportedPdfError("PDF has no pages")
    if sum(page.char_count for page in pages) < MIN_CHARS_PER_PAGE * len(pages):
        raise UnsupportedPdfError(
            "PDF has no extractable text layer (scanned or image-only); OCR is not supported"
        )

    return ParsedDocument(
        document_id=document_id_for(data),
        source_url=source_url,
        filename=filename,
        title=_guess_title(blocks),
        pages=pages,
        blocks=blocks,
    )


def _guess_title(blocks: list[TextBlock]) -> str:
    """The first substantial block on page 1 is, on a research paper, the title."""
    for block in blocks:
        if block.page_number != 1:
            break
        text = " ".join(block.text.split())
        if len(text) >= 25:
            return text[:300]
    return ""
