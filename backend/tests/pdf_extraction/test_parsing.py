from __future__ import annotations

import pytest

from app.services.pdf_extraction import (
    ParsedDocument,
    PdfParseError,
    UnsupportedPdfError,
    parse_pdf,
)
from tests.pdf_extraction.conftest import REAL_PAPERS, fixture_bytes, parse_fixture


@pytest.mark.parametrize("name", REAL_PAPERS)
def test_real_papers_parse_into_positioned_blocks(name: str) -> None:
    document = parse_fixture(name)

    assert document.page_count == 3
    assert document.blocks
    assert document.char_count > 3000
    for block in document.blocks:
        page = document.page(block.page_number)
        assert page is not None
        assert block.text.strip()
        assert 0 <= block.bbox.x0 < block.bbox.x1 <= page.width + 1
        assert 0 <= block.bbox.top < block.bbox.bottom <= page.height + 1
        assert block.lines
        assert block.text == "\n".join(line.text for line in block.lines)


@pytest.mark.parametrize("name", REAL_PAPERS)
def test_block_ids_are_unique_and_page_scoped(name: str) -> None:
    document = parse_fixture(name)

    ids = [block.block_id for block in document.blocks]
    assert len(ids) == len(set(ids))
    for block in document.blocks:
        assert block.block_id.startswith(f"p{block.page_number}-b")
        assert document.block(block.block_id) is block


def test_line_char_offsets_cover_every_character(ziprasidone: ParsedDocument) -> None:
    for block in ziprasidone.blocks:
        for line in block.lines:
            assert len(line.char_offsets) == len(line.text) + 1
            assert line.char_offsets == sorted(line.char_offsets)
            assert line.char_offsets[0] == pytest.approx(line.bbox.x0)
            assert line.char_offsets[-1] == pytest.approx(line.bbox.x1)


def test_title_is_recovered_from_the_first_page(ziprasidone: ParsedDocument) -> None:
    assert ziprasidone.title.startswith("A 6 Week Randomized Double-Blind Placebo-Controlled")


@pytest.mark.parametrize(
    ("name", "phrase"),
    [
        ("trial_ziprasidone", "73 patients were randomized"),
        ("trial_mipomersen", "double-blind, placebo-controlled, multicenter trial"),
        ("trial_linaclotide", "linaclotide (145 or 290"),
        ("trial_silymarin", "randomly assigned"),
    ],
)
def test_known_trial_details_survive_extraction(name: str, phrase: str) -> None:
    document = parse_fixture(name)

    text = " ".join(" ".join(block.text.split()) for block in document.blocks)
    assert phrase in text


def test_scanned_pdf_is_flagged_as_unsupported() -> None:
    with pytest.raises(UnsupportedPdfError, match="no extractable text layer"):
        parse_pdf(fixture_bytes("scanned_no_text_layer"))


def test_non_pdf_bytes_are_unsupported() -> None:
    with pytest.raises(UnsupportedPdfError, match="not a PDF"):
        parse_pdf(b"PK\x03\x04 this is a zip file")


def test_truncated_pdf_raises_a_parse_error() -> None:
    with pytest.raises(PdfParseError):
        parse_pdf(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n")


def test_max_pages_limits_parsing(ziprasidone: ParsedDocument) -> None:
    limited = parse_pdf(fixture_bytes("trial_ziprasidone"), max_pages=1)

    assert limited.page_count == 1
    assert ziprasidone.page_count == 3
    assert {block.page_number for block in limited.blocks} == {1}


def test_document_id_is_content_addressed() -> None:
    first = parse_fixture("trial_ziprasidone")
    again = parse_fixture("trial_ziprasidone")
    other = parse_fixture("trial_mipomersen")

    assert first.document_id == again.document_id
    assert first.document_id != other.document_id
