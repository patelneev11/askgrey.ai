from __future__ import annotations

import csv
import io

import pytest

from app.services.export import EmptyTableError, ExportOptions, write_csv
from app.services.export.csv_writer import BOM
from app.services.pdf_extraction import ExtractionTable, MatchQuality
from tests.export.conftest import grounded, paper, sample_table, table, ungrounded


def read_back(content: bytes) -> list[list[str]]:
    text = content.decode("utf-8")
    assert text.startswith(BOM) or not text
    return list(csv.reader(io.StringIO(text.lstrip(BOM), newline="")))


def test_header_pairs_every_column_with_a_source_column() -> None:
    rows = read_back(write_csv(sample_table()).content)

    assert rows[0] == [
        "Paper",
        "Source",
        "Pages",
        "Row status",
        "sample size",
        "sample size — source",
        "dosing regimen",
        "dosing regimen — source",
    ]


def test_cited_value_carries_page_and_quote() -> None:
    rows = read_back(write_csv(sample_table()).content)

    assert rows[1][:4] == [
        "A 6 Week Randomized Trial of Ziprasidone",
        "https://example.org/paper.pdf",
        "3",
        "extracted",
    ]
    assert rows[1][4] == "73 patients"
    assert rows[1][5] == 'p1 · "73 patients were randomized"'
    assert rows[1][7].startswith("p2 · ")


def test_unverified_and_missing_cells_are_distinguishable() -> None:
    rows = read_back(write_csv(sample_table()).content)

    assert rows[2][4] == "58 patients (unverified)"
    assert rows[2][5] == ""
    assert rows[2][6:] == ["", ""]


def test_fuzzy_matches_are_labelled() -> None:
    fuzzy = table(paper(cells={"sample_size": grounded("73", match=MatchQuality.FUZZY)}))

    assert "fuzzy match" in read_back(write_csv(fuzzy).content)[1][5]


def test_citations_and_metadata_can_be_dropped() -> None:
    options = ExportOptions(include_citations=False, include_metadata=False)

    rows = read_back(write_csv(sample_table(), options).content)

    assert rows[0] == ["Paper", "sample size", "dosing regimen"]
    assert rows[1] == [
        "A 6 Week Randomized Trial of Ziprasidone",
        "73 patients",
        "40-160 mg/d for 6 weeks",
    ]


def test_the_record_column_can_be_relabelled_for_non_paper_exports() -> None:
    options = ExportOptions(record_label="Section")

    rows = read_back(write_csv(sample_table(), options).content)

    assert rows[0][:4] == ["Section", "Source", "Pages", "Row status"]


def test_bom_can_be_disabled() -> None:
    content = write_csv(sample_table(), ExportOptions(bom=False)).content

    assert not content.startswith(BOM.encode("utf-8"))
    assert content.startswith(b"Paper,")


def test_crlf_line_endings() -> None:
    assert write_csv(sample_table()).content.count(b"\r\n") == 3


@pytest.mark.parametrize(
    "value",
    ["=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tlead", "\rlead"],
)
def test_formula_like_values_are_escaped(value: str) -> None:
    injected = table(paper(cells={"sample_size": ungrounded(value)}))

    cell = read_back(write_csv(injected).content)[1][4]

    assert cell.startswith("'")
    assert value.strip("\t\r") in cell


def test_special_characters_survive_the_round_trip() -> None:
    awkward = 'IC₅₀ 3.4 µM ± 0.2, "high dose" — 中文, emoji 🧪\nsecond line\ttab'
    row = table(paper(title=awkward, cells={"sample_size": ungrounded("n=1")}))

    rows = read_back(write_csv(row).content)

    assert rows[1][0] == awkward


def test_control_characters_are_stripped() -> None:
    row = table(paper(cells={"sample_size": ungrounded("73\x00 patients\x07")}))

    assert read_back(write_csv(row).content)[1][4] == "73 patients (unverified)"


def test_five_hundred_rows_render() -> None:
    big = table(
        *[
            paper(
                document_id=f"doc-{index}",
                title=f"Paper {index}",
                cells={"sample_size": grounded(str(index))},
            )
            for index in range(500)
        ]
    )

    rows = read_back(write_csv(big).content)

    assert len(rows) == 501
    assert rows[500][0] == "Paper 499"
    assert rows[500][5].startswith("p1 · ")


def test_a_table_with_no_columns_at_all_is_rejected() -> None:
    empty = ExtractionTable()

    with pytest.raises(EmptyTableError):
        write_csv(empty, ExportOptions(include_metadata=False))


def test_a_table_with_no_rows_still_has_a_header() -> None:
    assert read_back(write_csv(table()).content) == [
        [
            "Paper",
            "Source",
            "Pages",
            "Row status",
            "sample size",
            "sample size — source",
            "dosing regimen",
            "dosing regimen — source",
        ]
    ]
