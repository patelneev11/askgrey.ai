from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .models import BoundingBox, Citation, MatchQuality, ParsedDocument, TextBlock

# Below this similarity a fuzzy candidate is treated as no match at all.
FUZZY_THRESHOLD = 0.82
MIN_QUOTE_CHARS = 4

_LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl"}
_DASHES = {"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-"}
_QUOTES = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}
_WHITESPACE = re.compile(r"\s+")


@dataclass
class _Normalized:
    """Normalized text plus, per normalized character, its index in the original string."""

    text: str
    offsets: list[int]


def _normalize(text: str) -> _Normalized:
    """
    Fold away the artefacts PDF text extraction introduces.

    Ligatures, dash and quote variants, case and runs of whitespace are all collapsed, and a
    hyphen at a line break is dropped so a word split across two lines matches the word the
    model quoted. Every surviving character keeps the index it came from, so a match in
    normalized space maps back to an exact span in the original block text.
    """
    out: list[str] = []
    offsets: list[int] = []
    pending_space = False
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            pending_space = bool(out)
            index += 1
            continue
        if char == "-" and index + 1 < len(text) and text[index + 1] == "\n":
            index += 2
            pending_space = False
            continue
        if pending_space:
            out.append(" ")
            offsets.append(index)
            pending_space = False
        replacement = _LIGATURES.get(char) or _DASHES.get(char) or _QUOTES.get(char) or char
        for expanded in replacement.lower():
            out.append(expanded)
            offsets.append(index)
        index += 1
    offsets.append(len(text))
    return _Normalized("".join(out), offsets)


def normalize_for_match(text: str) -> str:
    return _normalize(text).text


@dataclass
class SpanMatch:
    block: TextBlock
    start_char: int
    end_char: int
    quality: MatchQuality


def _best_fuzzy(needle: str, haystack: str) -> tuple[int, int, float]:
    """Longest common run, expanded to the needle's length, scored by similarity."""
    matcher = SequenceMatcher(None, haystack, needle, autojunk=False)
    block = matcher.find_longest_match(0, len(haystack), 0, len(needle))
    if not block.size:
        return 0, 0, 0.0
    start = max(0, block.a - block.b)
    end = min(len(haystack), start + len(needle))
    ratio = SequenceMatcher(None, haystack[start:end], needle, autojunk=False).ratio()
    return start, end, ratio


def find_span(document: ParsedDocument, quote: str, *, block_id: str = "") -> SpanMatch | None:
    """
    Locate `quote` in the parsed text.

    The block the model cited is tried first; failing that every block is searched, so a
    misattributed `block_id` degrades to a slower search rather than a lost citation.
    Matching is exact first, then normalized, then fuzzy — the quality is reported on the
    citation so the frontend can mark an approximate highlight.
    """
    if len(quote.strip()) < MIN_QUOTE_CHARS:
        return None

    hinted = document.block(block_id) if block_id else None
    candidates = [hinted, *document.blocks] if hinted else list(document.blocks)

    for block in candidates:
        if block is None:
            continue
        position = block.text.find(quote)
        if position >= 0:
            return SpanMatch(block, position, position + len(quote), MatchQuality.EXACT)

    needle = _normalize(quote)
    if not needle.text:
        return None

    normalized_blocks = [(block, _normalize(block.text)) for block in candidates if block]
    for block, haystack in normalized_blocks:
        position = haystack.text.find(needle.text)
        if position >= 0:
            return SpanMatch(
                block,
                haystack.offsets[position],
                haystack.offsets[position + len(needle.text)],
                MatchQuality.NORMALIZED,
            )

    best: tuple[float, SpanMatch] | None = None
    for block, haystack in normalized_blocks:
        start, end, ratio = _best_fuzzy(needle.text, haystack.text)
        if ratio < FUZZY_THRESHOLD or end <= start:
            continue
        match = SpanMatch(block, haystack.offsets[start], haystack.offsets[end], MatchQuality.FUZZY)
        if best is None or ratio > best[0]:
            best = (ratio, match)
    return best[1] if best else None


def _line_rect(line_bbox: BoundingBox, offsets: list[float], start: int, end: int) -> BoundingBox:
    if not offsets or end <= start:
        return line_bbox
    left = offsets[max(0, min(start, len(offsets) - 1))]
    right = offsets[max(0, min(end, len(offsets) - 1))]
    if right <= left:
        return line_bbox
    return BoundingBox(x0=left, top=line_bbox.top, x1=right, bottom=line_bbox.bottom)


def build_citation(document: ParsedDocument, match: SpanMatch) -> Citation:
    """Turn a located span into the citation object the frontend highlights from."""
    block = match.block
    page = document.page(block.page_number)
    rects: list[BoundingBox] = []
    for line in block.lines:
        if line.end_char <= match.start_char or line.start_char >= match.end_char:
            continue
        rects.append(
            _line_rect(
                line.bbox,
                line.char_offsets,
                match.start_char - line.start_char,
                match.end_char - line.start_char,
            )
        )
    if not rects:
        rects = [block.bbox]

    bbox = rects[0]
    for rect in rects[1:]:
        bbox = bbox.union(rect)

    return Citation(
        document_id=document.document_id,
        source_url=document.source_url,
        page_number=block.page_number,
        page_width=page.width if page else 0.0,
        page_height=page.height if page else 0.0,
        block_id=block.block_id,
        text=block.text[match.start_char : match.end_char],
        start_char=match.start_char,
        end_char=match.end_char,
        bbox=bbox,
        rects=rects,
        match=match.quality,
    )


def cite(document: ParsedDocument, quote: str, *, block_id: str = "") -> Citation | None:
    match = find_span(document, quote, block_id=block_id)
    return build_citation(document, match) if match else None


def collapse_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()
