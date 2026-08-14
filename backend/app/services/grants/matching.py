from __future__ import annotations

import json
import math
import re
from collections import Counter
from typing import Any, Protocol

import httpx

from .errors import InvalidQueryError, MatchingError
from .models import GrantOpportunity, OpportunityMatch

MAX_FOCUS_LENGTH = 2000
# Enough of a topic description for the model to judge fit without paying for the whole call.
CANDIDATE_CHARS = 1200

SYSTEM_PROMPT = """\
You rank federal funding opportunities against a company's research focus.

You receive the focus, then a numbered list of open opportunities (title, agency, deadline,
topic description). Judge how well each opportunity's *topic* fits the company's science.

Return ONLY a JSON array, one object per opportunity you consider relevant, ordered from most
to least relevant:
  [{"index": <int>, "score": <0-100>, "rationale": "<one sentence>"}]

Rules:
- `index` must be one of the numbers shown; never invent one.
- Score on scientific fit with the topic description, not on funding size or deadline.
- Score below 40 means a weak fit; omit opportunities that are plainly unrelated.
- Cite the specific technology or disease overlap in the rationale, not generic praise.
- Emit only the JSON array, with no code fence and no commentary.
"""

STOPWORDS = frozenset(
    """
    a an and any are as at be being by can company could develop developing development do does
    for from has have how in into is it its of on or our over research so team technology that
    the their them there these this to us use using was we were what when where which who why
    will with would you your platform novel new approach approaches based
    """.split()
)


class MatchRanker(Protocol):
    """Scores candidate opportunities against a company research focus."""

    name: str

    async def rank(
        self, focus: str, candidates: list[GrantOpportunity]
    ) -> list[OpportunityMatch]: ...


def normalize_focus(focus: str) -> str:
    """Validate and canonicalize the research-focus description."""
    if not isinstance(focus, str):
        raise InvalidQueryError("focus must be a string")
    normalized = " ".join(focus.split())
    if not normalized:
        raise InvalidQueryError("focus must not be empty")
    if len(normalized) > MAX_FOCUS_LENGTH:
        raise InvalidQueryError(f"focus must be at most {MAX_FOCUS_LENGTH} characters")
    return normalized


def tokenize(text: str) -> list[str]:
    """Content words only, lowercased, hyphenated compounds kept intact."""
    words = re.findall(r"[a-z0-9][a-z0-9\-]*", text.lower())
    return [word.strip("-") for word in words if len(word) > 2 and word not in STOPWORDS]


class LexicalMatchRanker:
    """
    Deterministic fallback ranker.

    Scores each candidate by the IDF-weighted share of the focus's vocabulary it covers, so a
    rare term ("organoid") counts for far more than one every solicitation contains ("clinical").
    Title hits are weighted above body hits because a solicitation's title is what actually
    scopes it. Used whenever no LLM key is configured, which also keeps tests network-free.
    """

    name = "lexical"

    TITLE_WEIGHT = 2.0

    async def rank(self, focus: str, candidates: list[GrantOpportunity]) -> list[OpportunityMatch]:
        normalized = normalize_focus(focus)
        focus_terms = list(dict.fromkeys(tokenize(normalized)))
        if not focus_terms or not candidates:
            return []

        documents = [tokenize(candidate.match_text()) for candidate in candidates]
        document_frequency = Counter(
            term for document in documents for term in set(document) if term in set(focus_terms)
        )
        total = len(documents)
        # Smoothed IDF: a term in every candidate carries no discriminating signal.
        idf = {
            term: math.log((total + 1) / (document_frequency.get(term, 0) + 1)) + 1.0
            for term in focus_terms
        }
        best_possible = sum(idf.values()) * self.TITLE_WEIGHT

        matches: list[OpportunityMatch] = []
        for candidate, document in zip(candidates, documents, strict=True):
            title_terms = set(tokenize(candidate.title))
            body_terms = set(document)
            earned = 0.0
            hits: list[str] = []
            for term in focus_terms:
                if term in title_terms:
                    earned += idf[term] * self.TITLE_WEIGHT
                    hits.append(term)
                elif term in body_terms:
                    earned += idf[term]
                    hits.append(term)
            if not hits:
                continue
            score = round(min(earned / best_possible, 1.0), 4)
            matches.append(
                OpportunityMatch(
                    opportunity=candidate,
                    score=score,
                    rationale=(
                        f"Lexical overlap on {', '.join(hits[:6])}; "
                        "no LLM configured, so this is term matching rather than semantic fit."
                    ),
                    matched_terms=hits,
                )
            )

        matches.sort(key=lambda match: (-match.score, match.opportunity.title))
        return matches


def _strip_code_fence(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    return stripped.strip()


def render_candidates(candidates: list[GrantOpportunity]) -> str:
    """The numbered candidate list the model ranks; indices are positions in `candidates`."""
    blocks: list[str] = []
    for index, candidate in enumerate(candidates):
        description = candidate.topic_description[:CANDIDATE_CHARS]
        if candidate.topics:
            topics = "; ".join(candidate.topics[:8])
            description = f"Topics: {topics}\n{description}".strip()
        blocks.append(
            f"[{index}] {candidate.title}\n"
            f"Agency: {candidate.agency or 'unknown'} | "
            f"Program: {candidate.program.value if candidate.program else 'unspecified'} | "
            f"Deadline: {candidate.deadline_label}\n"
            f"{description or '(no topic description published)'}"
        )
    return "\n\n".join(blocks)


class ClaudeMatchRanker:
    """
    Semantic ranker backed by Anthropic's Messages API.

    The whole candidate list goes in one request so the model ranks comparatively rather than
    scoring each opportunity in isolation, and the assistant turn is prefilled with `[` to
    suppress a prose preamble (the Messages API has no JSON response mode).
    """

    name = "claude"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com/v1",
        anthropic_version: str = "2023-06-01",
        max_tokens: int = 2048,
        timeout: float = 45.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.anthropic_version = anthropic_version
        self.max_tokens = max_tokens
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _complete(self, prompt: str) -> str:
        response = await self._client.post(
            f"{self.base_url}/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.anthropic_version,
                "content-type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": self.max_tokens,
                "temperature": 0,
                "system": SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": prompt},
                    {"role": "assistant", "content": "["},
                ],
            },
        )
        if response.status_code >= 400:
            raise MatchingError(f"Claude returned HTTP {response.status_code}")
        try:
            blocks = response.json()["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise MatchingError("Claude response had an unexpected shape") from exc
        text = "".join(
            block["text"]
            for block in blocks
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
        if not text.strip():
            raise MatchingError("Claude returned no text content")
        return text

    async def rank(self, focus: str, candidates: list[GrantOpportunity]) -> list[OpportunityMatch]:
        normalized = normalize_focus(focus)
        if not candidates:
            return []

        prompt = (
            f"Company research focus:\n{normalized}\n\n"
            f"Open opportunities:\n\n{render_candidates(candidates)}"
        )
        try:
            raw = await self._complete(prompt)
        except httpx.HTTPError as exc:
            raise MatchingError(f"Claude request failed: {exc}") from exc

        body = _strip_code_fence(raw)
        if not body.startswith("["):
            # Re-attach the prefilled bracket that Claude's completion continues from.
            body = "[" + body
        try:
            parsed = json.loads(body)
        except ValueError as exc:
            raise MatchingError("Claude did not return valid JSON") from exc
        if not isinstance(parsed, list):
            raise MatchingError("Claude did not return a JSON array")

        matches: list[OpportunityMatch] = []
        seen: set[int] = set()
        for item in parsed:
            match = _parse_ranking(item, candidates)
            if match is None or id(match.opportunity) in seen:
                continue
            seen.add(id(match.opportunity))
            matches.append(match)
        if not matches:
            raise MatchingError("Claude ranked none of the candidates")
        matches.sort(key=lambda match: (-match.score, match.opportunity.title))
        return matches


def _parse_ranking(item: Any, candidates: list[GrantOpportunity]) -> OpportunityMatch | None:
    """One `{index, score, rationale}` object, or `None` when the model went off-script."""
    if not isinstance(item, dict):
        return None
    index = item.get("index")
    if not isinstance(index, int) or not 0 <= index < len(candidates):
        return None
    raw_score = item.get("score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, int | float):
        return None
    # The prompt asks for 0-100; a model that answers 0-1 anyway should not be silently floored.
    score = float(raw_score)
    score = score / 100.0 if score > 1.0 else score
    rationale = item.get("rationale")
    return OpportunityMatch(
        opportunity=candidates[index],
        score=round(min(max(score, 0.0), 1.0), 4),
        rationale=rationale.strip() if isinstance(rationale, str) else "",
    )


class FallbackMatchRanker:
    """Tries `primary`, and on any matching failure re-ranks with `fallback`."""

    def __init__(self, primary: MatchRanker, fallback: MatchRanker) -> None:
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}+{fallback.name}"

    async def rank(self, focus: str, candidates: list[GrantOpportunity]) -> list[OpportunityMatch]:
        # An unusable focus is the caller's problem regardless of ranker, so it propagates.
        normalized = normalize_focus(focus)
        try:
            return await self.primary.rank(normalized, candidates)
        except MatchingError:
            return await self.fallback.rank(normalized, candidates)
