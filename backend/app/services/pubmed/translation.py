from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any, Protocol

import httpx

from .errors import InvalidQueryError, TranslationError
from .models import DateRangeFilter, PublicationTypeFilter, TranslatedQuery

MAX_QUERY_LENGTH = 1000

SYSTEM_PROMPT = """\
You translate a biomedical researcher's question into an NCBI Entrez (PubMed) query.

Return ONLY a JSON object with these keys:
  "term": string — the complete Entrez query, Boolean-optimized, using field tags
          such as [MeSH Terms], [tiab], [Publication Type] and [Date - Publication].
  "mesh_terms": string[] — the MeSH descriptors you used.
  "keywords": string[] — free-text concepts you used for terms with no MeSH descriptor.
  "publication_types": string[] — e.g. ["Review"], ["Randomized Controlled Trial"]. May be empty.
  "date_start": string|null — "YYYY-MM-DD" lower bound, or null.
  "date_end": string|null — "YYYY-MM-DD" upper bound, or null.
  "rationale": string — one sentence on how the question was decomposed.

Rules:
- Group each concept in parentheses, OR synonyms within a concept, AND concepts together.
- Pair every MeSH descriptor with a [tiab] synonym so recent, unindexed records are still found.
- Never invent a MeSH descriptor you are not confident exists; use [tiab] instead.
- Emit only the JSON object, with no code fence and no commentary.
"""

STOPWORDS = frozenset(
    """
    a an and are as at be by can could do does for from give had has have how i in into is it
    its me my of on or over please recent should show some studies study tell that the their
    there these this to us was we were what when where which who why will with would you your
    about any anything article articles literature paper papers pubmed research find search
    """.split()
)

PUBLICATION_TYPE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bsystematic review\b", "Systematic Review"),
    (r"\bmeta[- ]analys[ie]s\b", "Meta-Analysis"),
    (r"\brandomi[sz]ed controlled trials?\b|\brcts?\b", "Randomized Controlled Trial"),
    (r"\bclinical trials?\b", "Clinical Trial"),
    (r"\breviews?\b", "Review"),
    (r"\bcase reports?\b", "Case Reports"),
)


class QueryTranslator(Protocol):
    """Turns a natural-language question into a structured, Entrez-ready query."""

    name: str

    async def translate(self, query: str) -> TranslatedQuery: ...


def normalize_query(query: str) -> str:
    """Validate and canonicalize raw user input before any translation happens."""
    if not isinstance(query, str):
        raise InvalidQueryError("query must be a string")
    normalized = " ".join(query.split())
    if not normalized:
        raise InvalidQueryError("query must not be empty")
    if len(normalized) > MAX_QUERY_LENGTH:
        raise InvalidQueryError(f"query must be at most {MAX_QUERY_LENGTH} characters")
    if not re.search(r"[a-zA-Z0-9]", normalized):
        raise InvalidQueryError("query must contain at least one alphanumeric character")
    return normalized


def _extract_publication_types(query: str) -> list[str]:
    lowered = query.lower()
    found: list[str] = []
    for pattern, label in PUBLICATION_TYPE_PATTERNS:
        if re.search(pattern, lowered) and label not in found:
            found.append(label)
    # "Systematic Review" already implies the narrower intent behind a bare "review".
    if "Systematic Review" in found and "Review" in found:
        found.remove("Review")
    return found


def _extract_date_range(query: str, today: date) -> DateRangeFilter:
    lowered = query.lower()

    match = re.search(r"\b(?:last|past|previous)\s+(\d{1,2})\s+(year|month)s?\b", lowered)
    if match:
        amount = int(match.group(1))
        days = amount * (365 if match.group(2) == "year" else 30)
        return DateRangeFilter(start=today - timedelta(days=days), end=today)

    match = re.search(r"\bbetween\s+(\d{4})\s+and\s+(\d{4})\b", lowered)
    if match:
        first, second = sorted((int(match.group(1)), int(match.group(2))))
        return DateRangeFilter(start=date(first, 1, 1), end=date(second, 12, 31))

    match = re.search(r"\b(?:since|after|from)\s+(\d{4})\b", lowered)
    if match:
        return DateRangeFilter(start=date(int(match.group(1)), 1, 1), end=today)

    match = re.search(r"\b(?:before|until|up to)\s+(\d{4})\b", lowered)
    if match:
        return DateRangeFilter(end=date(int(match.group(1)), 12, 31))

    return DateRangeFilter()


def _extract_keywords(query: str) -> list[str]:
    """
    Keep quoted phrases intact and reduce the rest to content words.

    Order is preserved so the generated query reads like the question it came from.
    """
    keywords: list[str] = []
    remainder = query
    for phrase in re.findall(r'"([^"]+)"', query):
        cleaned = " ".join(phrase.split())
        if cleaned:
            keywords.append(cleaned)
        remainder = remainder.replace(f'"{phrase}"', " ")

    # Drop the phrases that only expressed a filter, so they aren't searched as content.
    for pattern, _ in PUBLICATION_TYPE_PATTERNS:
        remainder = re.sub(pattern, " ", remainder, flags=re.IGNORECASE)
    remainder = re.sub(
        r"\b(?:last|past|previous)\s+\d{1,2}\s+(?:year|month)s?\b", " ", remainder, flags=re.I
    )
    remainder = re.sub(
        r"\b(?:between\s+\d{4}\s+and|since|after|from|before|until|up to)\s+\d{4}\b",
        " ",
        remainder,
        flags=re.IGNORECASE,
    )

    for raw in re.split(r"[^\w\-+]+", remainder):
        word = raw.strip("-")
        if len(word) < 2 or word.lower() in STOPWORDS or word.isdigit():
            continue
        if word.lower() not in {existing.lower() for existing in keywords}:
            keywords.append(word)
    return keywords


def build_term(
    keywords: list[str],
    mesh_terms: list[str],
    publication_types: PublicationTypeFilter,
    date_range: DateRangeFilter,
) -> str:
    """Assemble the Entrez term: concepts ANDed together, then the filters."""
    clauses: list[str] = []
    for mesh in mesh_terms:
        clauses.append(f'("{mesh}"[MeSH Terms] OR "{mesh}"[tiab])')
    covered = {mesh.lower() for mesh in mesh_terms}
    for keyword in keywords:
        if keyword.lower() in covered:
            continue
        clauses.append(f'"{keyword}"[tiab]')

    term = " AND ".join(clauses)
    for filter_clause in (publication_types.to_entrez(), date_range.to_entrez()):
        if filter_clause:
            term = f"{term} AND {filter_clause}" if term else filter_clause
    return term


class RuleBasedQueryTranslator:
    """
    Deterministic fallback translator.

    It cannot infer MeSH descriptors, so it emits `[tiab]` clauses plus the publication-type
    and date filters it can recognize lexically. Used whenever no LLM key is configured,
    which also keeps the test suite free of network calls.
    """

    name = "rule-based"

    def __init__(self, *, today: date | None = None) -> None:
        self._today = today

    async def translate(self, query: str) -> TranslatedQuery:
        normalized = normalize_query(query)
        today = self._today or date.today()
        publication_types = PublicationTypeFilter(values=_extract_publication_types(normalized))
        date_range = _extract_date_range(normalized, today)
        keywords = _extract_keywords(normalized)
        term = build_term(keywords, [], publication_types, date_range)
        if not term:
            raise TranslationError("query contained no searchable terms")
        return TranslatedQuery(
            original=normalized,
            term=term,
            keywords=keywords,
            publication_types=publication_types,
            date_range=date_range,
            translator=self.name,
            rationale="Lexical translation: no MeSH mapping without an LLM.",
        )


def _parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _strip_code_fence(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    return stripped.strip()


class LLMQueryTranslator:
    """
    Translates through an OpenAI-compatible chat-completions endpoint.

    The model is asked for JSON rather than a bare query string so the structured filters
    stay inspectable in the UI, and so a malformed `term` can be rebuilt from its parts.
    """

    name = "llm"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        fallback: QueryTranslator | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.fallback = fallback or RuleBasedQueryTranslator()
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _complete(self, query: str) -> str:
        response = await self._client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
            },
        )
        if response.status_code >= 400:
            raise TranslationError(f"LLM returned HTTP {response.status_code}")
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise TranslationError("LLM response had an unexpected shape") from exc
        if not isinstance(content, str):
            raise TranslationError("LLM response content was not text")
        return content

    async def translate(self, query: str) -> TranslatedQuery:
        normalized = normalize_query(query)
        try:
            raw = await self._complete(normalized)
        except httpx.HTTPError as exc:
            raise TranslationError(f"LLM request failed: {exc}") from exc

        try:
            data = json.loads(_strip_code_fence(raw))
        except ValueError as exc:
            raise TranslationError("LLM did not return valid JSON") from exc
        if not isinstance(data, dict):
            raise TranslationError("LLM did not return a JSON object")

        mesh_terms = [str(item) for item in data.get("mesh_terms", []) if str(item).strip()]
        keywords = [str(item) for item in data.get("keywords", []) if str(item).strip()]
        publication_types = PublicationTypeFilter(
            values=[str(item) for item in data.get("publication_types", []) if str(item).strip()]
        )
        date_range = DateRangeFilter(
            start=_parse_iso_date(data.get("date_start")),
            end=_parse_iso_date(data.get("date_end")),
        )

        term = str(data.get("term", "")).strip()
        if not term:
            # The model gave us the parts but not the assembled query; assemble it ourselves.
            term = build_term(keywords, mesh_terms, publication_types, date_range)
        if not term:
            raise TranslationError("LLM produced an empty query")

        return TranslatedQuery(
            original=normalized,
            term=term,
            mesh_terms=mesh_terms,
            keywords=keywords,
            publication_types=publication_types,
            date_range=date_range,
            translator=self.name,
            rationale=str(data.get("rationale", "")),
        )


class FallbackQueryTranslator:
    """Tries `primary`, and on any translation failure retranslates with `fallback`."""

    def __init__(self, primary: QueryTranslator, fallback: QueryTranslator) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}+{fallback.name}"

    async def translate(self, query: str) -> TranslatedQuery:
        # An unusable query is the caller's problem regardless of translator, so it propagates.
        normalized = normalize_query(query)
        try:
            return await self.primary.translate(normalized)
        except TranslationError:
            return await self.fallback.translate(normalized)
