"""
Turning caller input into the one text query the upstream API is allowed to receive.

Two rules shape this module. First, the upstream index is text: a SMILES string cannot be
searched as a structure, so it is reduced to its molecular formula and the payload says so
rather than implying a structure search happened. Second, nothing the caller types is ever
interpolated into the query as-is — terms are *extracted* with a strict token pattern, so no
quote, colon, wildcard or boolean operator from user input can reach the upstream query DSL.
"""

from __future__ import annotations

import re

from ..smiles import ParsedStructure, parse_structure
from .errors import InvalidKeywordError

MAX_KEYWORD_LENGTH = 200
MIN_KEYWORD_LENGTH = 3
# A prior-art query is a scaffold or a mechanism, not a paragraph. More terms than this is a
# pasted abstract, which — with every term required — would match nothing anyway.
MAX_TERMS = 12
MIN_TERM_LENGTH = 2

# Syntactic gate on the raw keyword string. Deliberately narrow: chemistry and disease keywords
# need letters, digits, hyphens, apostrophes, commas, periods, slashes and plus signs, and
# nothing else. Newlines are excluded, so a pasted list cannot become one query.
ALLOWED_KEYWORD_CHARACTERS = re.compile(r"^[A-Za-z0-9 \-'’,\.\+/]+$")
# What may become a search term. Anything outside this class is dropped rather than escaped,
# which is why the constructed query cannot carry query-language syntax. `+` is excluded even
# though the keyword gate accepts it in the raw string, because `+` is the operator this module
# uses to mark a term as required: a term may never carry one of its own.
TERM_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-']*")


def normalize_keywords(value: object) -> str:
    """
    Syntactic gate for free-text keyword input: return the collapsed string, or raise.

    Raises `InvalidKeywordError` for a non-string, a string shorter than `MIN_KEYWORD_LENGTH`,
    one over `MAX_KEYWORD_LENGTH`, or one containing a character keyword search has no use for.
    """
    if not isinstance(value, str):
        raise InvalidKeywordError("keywords must be a string")
    collapsed = " ".join(value.split())
    if len(collapsed) < MIN_KEYWORD_LENGTH:
        raise InvalidKeywordError(
            f"keywords must be at least {MIN_KEYWORD_LENGTH} characters "
            f"(received {len(collapsed)})"
        )
    if len(collapsed) > MAX_KEYWORD_LENGTH:
        raise InvalidKeywordError(
            f"keywords must be at most {MAX_KEYWORD_LENGTH} characters (received {len(collapsed)})"
        )
    if not ALLOWED_KEYWORD_CHARACTERS.match(collapsed):
        raise InvalidKeywordError(
            "keywords may contain only letters, digits, spaces and - ' , . + / characters"
        )
    return collapsed


def keyword_terms(text: str) -> list[str]:
    """
    The searchable terms in `text`: extracted, de-duplicated case-insensitively, and capped.

    Extraction rather than escaping is the security boundary here — see the module docstring.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for match in TERM_PATTERN.finditer(text):
        term = match.group(0).strip("-+'")
        if len(term) < MIN_TERM_LENGTH:
            continue
        folded = term.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        terms.append(term)
        if len(terms) == MAX_TERMS:
            break
    return terms


def formula_term(structure: ParsedStructure) -> str:
    """
    The molecular formula as a single searchable token.

    RDKit reports charge as a trailing `+`/`-` (e.g. `C9H8O4-`); the sign is dropped because it
    is not part of how a formula is written in patent text.
    """
    return re.sub(r"[^A-Za-z0-9]", "", structure.molecular_formula)


class DerivedTerms:
    """The terms a query was built from, and the structure they came from (if any)."""

    def __init__(self, terms: list[str], structure: ParsedStructure | None) -> None:
        self.terms = terms
        self.structure = structure


def derive_terms(smiles: str, keywords: str) -> DerivedTerms:
    """
    Validate the caller's structure and/or keywords and return the terms to search.

    Raises `InvalidStructureError` or `InvalidKeywordError`; both become a 422 at the route.
    """
    structure = parse_structure(smiles) if smiles.strip() else None
    terms: list[str] = []
    if structure is not None:
        formula = formula_term(structure)
        if formula:
            terms.append(formula)
    if keywords.strip():
        normalized = normalize_keywords(keywords)
        for term in keyword_terms(normalized):
            if term.casefold() not in {existing.casefold() for existing in terms}:
                terms.append(term)
    if not terms:
        raise InvalidKeywordError(
            "no searchable term could be derived; supply a SMILES structure or "
            "keywords containing at least one word"
        )
    return DerivedTerms(terms[:MAX_TERMS], structure)


def query_string(terms: list[str]) -> str:
    """
    The terms as one upstream query where every term is required, e.g. `+C9H8O4 +kinase`.

    The upstream parser defaults to OR — `salicylate prodrug` returns the union, and a literal
    `AND` is searched as a word rather than read as an operator — so each term carries the `+`
    prefix that makes it mandatory. This is the string reported as `query_used`, because a
    researcher reproducing the search needs the query the API actually received.
    """
    return " ".join(f"+{term}" for term in terms)
