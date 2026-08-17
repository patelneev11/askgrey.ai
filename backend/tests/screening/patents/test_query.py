from __future__ import annotations

import pytest

from app.services.screening import InvalidStructureError
from app.services.screening.patents import (
    InvalidKeywordError,
    PatentSearch,
    QueryDerivation,
    build_query,
    derive_terms,
    keyword_terms,
    normalize_keywords,
    query_string,
)
from app.services.screening.patents.query import MAX_KEYWORD_LENGTH, MAX_TERMS

ASPIRIN = "CC(=O)OC1=CC=CC=C1C(=O)O"


def test_normalize_keywords_collapses_whitespace() -> None:
    assert normalize_keywords("  kinase   inhibitor \n scaffold ") == "kinase inhibitor scaffold"


@pytest.mark.parametrize(
    "value",
    [
        "ab",
        "x" * (MAX_KEYWORD_LENGTH + 1),
        'kinase" OR title:(*)',
        "kinase AND (abstract:foo)",
        "select * from patents;",
    ],
)
def test_normalize_keywords_rejects_unusable_or_syntactic_input(value: str) -> None:
    with pytest.raises(InvalidKeywordError):
        normalize_keywords(value)


def test_normalize_keywords_rejects_non_strings() -> None:
    with pytest.raises(InvalidKeywordError):
        normalize_keywords(42)


def test_keyword_terms_deduplicates_case_insensitively_and_caps_length() -> None:
    assert keyword_terms("Kinase kinase KINASE inhibitor") == ["Kinase", "inhibitor"]
    assert len(keyword_terms(" ".join(f"term{index}" for index in range(40)))) == MAX_TERMS


def test_keyword_terms_drops_one_character_tokens() -> None:
    assert keyword_terms("a b3 cd") == ["b3", "cd"]


def test_query_string_marks_every_term_required() -> None:
    # The live API defaults to OR and searches a literal `AND` as a word, so `+` is the operator.
    assert query_string(["C9H8O4", "salicylate"]) == "+C9H8O4 +salicylate"


def test_a_term_can_never_carry_the_required_operator_itself() -> None:
    # `+` passes the keyword gate but is not a term character, so it cannot reach the query DSL.
    assert keyword_terms("anti+inflammatory") == ["anti", "inflammatory"]
    assert query_string(keyword_terms("anti+inflammatory")) == "+anti +inflammatory"


def test_derive_terms_from_a_structure_uses_the_molecular_formula() -> None:
    derived = derive_terms(ASPIRIN, "")

    assert derived.terms == ["C9H8O4"]
    assert derived.structure is not None
    assert derived.structure.molecular_formula == "C9H8O4"


def test_derive_terms_merges_structure_and_keywords_without_duplicating() -> None:
    derived = derive_terms(ASPIRIN, "c9h8o4 salicylate prodrug")

    assert derived.terms == ["C9H8O4", "salicylate", "prodrug"]


def test_derive_terms_rejects_input_with_no_searchable_term() -> None:
    with pytest.raises(InvalidKeywordError):
        derive_terms("", "")


def test_derive_terms_rejects_an_invalid_structure() -> None:
    with pytest.raises(InvalidStructureError):
        derive_terms("C1CC", "")


def test_build_query_from_keywords_states_that_no_structure_was_submitted() -> None:
    query = build_query(PatentSearch(keywords="salicylate prodrug"))

    assert query.derived_from is QueryDerivation.KEYWORDS
    assert query.query_used == "+salicylate +prodrug"
    assert query.structure is None
    assert "No structure was submitted" in query.derivation


def test_build_query_from_a_structure_says_the_structure_itself_was_not_searched() -> None:
    query = build_query(PatentSearch(smiles=ASPIRIN))

    assert query.derived_from is QueryDerivation.STRUCTURE_FORMULA
    assert query.query_used == "+C9H8O4"
    assert query.structure is not None
    assert query.structure.searched_by_structure is False
    assert query.structure.canonical_smiles
    # A formula-only query is honest about usually matching nothing, so a zero-hit landscape
    # cannot be read as "nobody has patented this compound".
    assert "formula-only query usually returns nothing" in query.structure.note
    assert "not on the structure itself" in query.derivation
    assert "not chemical structures" in query.structure.note


def test_build_query_from_both_reports_the_combined_derivation() -> None:
    query = build_query(PatentSearch(smiles=ASPIRIN, keywords="co-crystal"))

    assert query.derived_from is QueryDerivation.STRUCTURE_FORMULA_AND_KEYWORDS
    assert query.query_used == "+C9H8O4 +co-crystal"
    assert "co-crystal" in query.derivation


def test_build_query_never_carries_user_query_syntax_into_the_query_string() -> None:
    query = build_query(PatentSearch(keywords="kinase inhibitor, EGFR/HER2"))

    assert query.query_used == "+kinase +inhibitor +EGFR +HER2"
    assert not set('":()*[]') & set(query.query_used)
