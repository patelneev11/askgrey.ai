from __future__ import annotations

import io

import pdfplumber
import pytest

from app.services.pdf_extraction import Citation, MatchQuality, ParsedDocument, cite, find_span
from app.services.pdf_extraction.parsing import WORD_X_TOLERANCE
from tests.pdf_extraction.conftest import fixture_bytes, parse_fixture

QUOTE = "73 patients were randomized in a double-blinded, placebo-controlled study"


def tuple_of(citation: Citation) -> tuple[float, float, float, float]:
    return (citation.bbox.x0, citation.bbox.top, citation.bbox.x1, citation.bbox.bottom)


def crop_text(name: str, page_number: int, box: tuple[float, float, float, float]) -> str:
    """Read back the text that actually sits inside a citation rectangle."""
    with pdfplumber.open(io.BytesIO(fixture_bytes(name))) as pdf:
        page = pdf.pages[page_number - 1]
        cropped = page.crop((box[0] - 1, box[1] - 1, box[2] + 1, box[3] + 1))
        return " ".join((cropped.extract_text(x_tolerance=WORD_X_TOLERANCE) or "").split())


def test_exact_quote_is_located(ziprasidone: ParsedDocument) -> None:
    match = find_span(ziprasidone, QUOTE)

    assert match is not None
    assert match.quality is MatchQuality.EXACT
    assert match.block.text[match.start_char : match.end_char] == QUOTE


def test_citation_points_at_the_text_it_quotes(ziprasidone: ParsedDocument) -> None:
    citation = cite(ziprasidone, QUOTE)

    assert citation is not None
    assert citation.document_id == ziprasidone.document_id
    assert citation.page_number == 1
    assert citation.text == QUOTE
    assert citation.page_width > 0 and citation.page_height > 0

    inside = crop_text("trial_ziprasidone", citation.page_number, tuple_of(citation))
    assert "73 patients were randomized" in inside
    assert "placebo-controlled study" in inside


def test_rects_stay_inside_the_page_and_the_quoted_lines(ziprasidone: ParsedDocument) -> None:
    citation = cite(ziprasidone, QUOTE)

    assert citation is not None
    assert 1 <= len(citation.rects) <= 3
    for rect in citation.rects:
        assert 0 <= rect.x0 < rect.x1 <= citation.page_width
        assert 0 <= rect.top < rect.bottom <= citation.page_height
        assert rect.height < 30
    # A single quote occupies a small share of the page, not the whole column.
    assert citation.bbox.height < citation.page_height / 3


def test_a_wrong_block_hint_still_resolves(ziprasidone: ParsedDocument) -> None:
    citation = cite(ziprasidone, QUOTE, block_id="p3-b1")

    assert citation is not None
    assert citation.block_id != "p3-b1"
    assert citation.text == QUOTE


def test_whitespace_and_ligature_differences_match_as_normalized(
    ziprasidone: ParsedDocument,
) -> None:
    reflowed = "73   patients were randomized\nin a double-blinded, placebo–controlled study"

    citation = cite(ziprasidone, reflowed)

    assert citation is not None
    assert citation.match is MatchQuality.NORMALIZED
    assert "73 patients were randomized" in " ".join(citation.text.split())


def test_small_typo_matches_fuzzily(ziprasidone: ParsedDocument) -> None:
    citation = cite(ziprasidone, "73 patients were randomised in a double-blinded, placebo study")

    assert citation is not None
    assert citation.match is MatchQuality.FUZZY
    assert "73 patients" in citation.text


def test_invented_quote_is_not_grounded(ziprasidone: ParsedDocument) -> None:
    assert cite(ziprasidone, "the trial enrolled 4,812 astronauts across nine lunar sites") is None


def test_trivially_short_quote_is_rejected(ziprasidone: ParsedDocument) -> None:
    assert cite(ziprasidone, "73") is None


@pytest.mark.parametrize(
    ("name", "quote"),
    [
        ("trial_mipomersen", "Randomized, double-blind, placebo-controlled, multicenter trial"),
        ("trial_silymarin", "Participants were randomly assigned"),
    ],
)
def test_citations_are_accurate_across_papers(name: str, quote: str) -> None:
    document = parse_fixture(name)

    citation = cite(document, quote)

    assert citation is not None
    inside = crop_text(name, citation.page_number, tuple_of(citation))
    first_word = quote.split()[0].strip(",")
    last_word = quote.split()[-1].strip(",")
    assert first_word in inside and last_word in inside
