from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from pydantic import BaseModel

# Hyphens, dashes, slashes and underscores become spaces so "non-clinical", "non clinical" and
# "non\u2011clinical" are one phrase. Everything else is left alone: dropping punctuation would
# also drop the dots in "3.2.S.4" and in "ICH S10".
_SEPARATORS = dict.fromkeys(map(ord, "-\u2010\u2011\u2012\u2013\u2014\u2015\u2212_/\\\u00a0"), " ")
_QUOTES = {ord("\u2018"): "'", ord("\u2019"): "'", ord("\u201c"): '"', ord("\u201d"): '"'}


class PhraseMatch(BaseModel):
    """Where a phrase was found, so a reviewer can check the engine rather than trust it.

    `offset` is a character offset into the *normalised* text, not the submitted draft: the
    normalisation collapses whitespace, so the two do not share coordinates.
    """

    phrase: str
    offset: int
    context: str


def normalise(text: str) -> str:
    """Case-fold, unify dashes and quotes, and collapse whitespace. No stemming, no synonyms."""
    folded = unicodedata.normalize("NFKC", text).lower()
    folded = folded.translate(_SEPARATORS).translate(_QUOTES)
    return " ".join(folded.split())


def word_count(normalised_text: str) -> int:
    return len(normalised_text.split()) if normalised_text else 0


@lru_cache(maxsize=2048)
def _pattern(normalised_phrase: str) -> re.Pattern[str]:
    """Match on word boundaries, so "glp" does not match "glphosphate"."""
    return re.compile(rf"(?<!\w){re.escape(normalised_phrase)}(?!\w)")


def find_phrase(
    normalised_text: str, phrase: str, *, context_chars: int = 60
) -> PhraseMatch | None:
    """First occurrence of `phrase` in already-normalised text, or None. Literal, not fuzzy."""
    needle = normalise(phrase)
    if not needle:
        return None
    found = _pattern(needle).search(normalised_text)
    if found is None:
        return None
    start = max(0, found.start() - context_chars)
    end = min(len(normalised_text), found.end() + context_chars)
    return PhraseMatch(phrase=needle, offset=found.start(), context=normalised_text[start:end])
