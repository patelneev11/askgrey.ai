from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from app.services.grants.errors import InvalidQueryError, MatchingError
from app.services.grants.matching import (
    ClaudeMatchRanker,
    FallbackMatchRanker,
    LexicalMatchRanker,
)
from tests.grants.conftest import opportunity

pytestmark = pytest.mark.asyncio

FOCUS = "mRNA cancer immunotherapy screened in patient-derived pancreatic organoids"

ON_TOPIC = opportunity(
    "Pancreatic organoid models for immunotherapy response",
    opportunity_id="on",
    topic_description="Patient-derived organoids to predict mRNA immunotherapy response.",
)
ADJACENT = opportunity(
    "Cancer biomarker assay validation",
    opportunity_id="adj",
    topic_description="Validation of immunotherapy response biomarkers in clinical studies.",
)
OFF_TOPIC = opportunity(
    "Rural broadband infrastructure deployment",
    opportunity_id="off",
    topic_description="Fixed wireless backhaul for underserved counties.",
)


Handler = Callable[[httpx.Request], httpx.Response]


def claude_ranker(handler: Handler) -> ClaudeMatchRanker:
    return ClaudeMatchRanker(
        api_key="test-key",
        model="claude-sonnet-4-5",
        transport=httpx.MockTransport(handler),
    )


def claude_reply(text: str, status_code: int = 200) -> Handler:
    def handler(_request: httpx.Request) -> httpx.Response:
        if status_code >= 400:
            return httpx.Response(status_code, json={"error": {"message": "boom"}})
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})

    return handler


async def test_lexical_ranks_topical_overlap_above_incidental_overlap() -> None:
    matches = await LexicalMatchRanker().rank(FOCUS, [ADJACENT, OFF_TOPIC, ON_TOPIC])

    assert [match.opportunity.opportunity_id for match in matches] == ["on", "adj"]
    assert matches[0].score > matches[1].score
    assert "organoids" in matches[0].matched_terms
    # An opportunity sharing no vocabulary with the focus is dropped, not scored zero.
    assert all(match.opportunity.opportunity_id != "off" for match in matches)


async def test_lexical_weights_title_hits_above_body_hits() -> None:
    in_title = opportunity("Organoid screening platforms", opportunity_id="title")
    in_body = opportunity(
        "Assay development program",
        opportunity_id="body",
        topic_description="Organoid screening of candidate compounds.",
    )

    matches = await LexicalMatchRanker().rank("organoid screening", [in_body, in_title])

    assert [match.opportunity.opportunity_id for match in matches] == ["title", "body"]


async def test_lexical_returns_nothing_without_candidates() -> None:
    assert await LexicalMatchRanker().rank(FOCUS, []) == []


@pytest.mark.parametrize("focus", ["", "   ", "\n\t"])
async def test_empty_focus_is_rejected(focus: str) -> None:
    with pytest.raises(InvalidQueryError):
        await LexicalMatchRanker().rank(focus, [ON_TOPIC])


async def test_claude_scores_are_normalized_and_ordered() -> None:
    ranker = claude_ranker(
        claude_reply(
            '[{"index": 1, "score": 55, "rationale": "Adjacent biomarker work."},'
            ' {"index": 0, "score": 92, "rationale": "Direct organoid overlap."}]'
        )
    )

    matches = await ranker.rank(FOCUS, [ON_TOPIC, ADJACENT])

    assert [match.opportunity.opportunity_id for match in matches] == ["on", "adj"]
    assert [match.score for match in matches] == [0.92, 0.55]
    assert matches[0].rationale == "Direct organoid overlap."
    await ranker.aclose()


async def test_claude_accepts_a_prefill_continuation_and_a_code_fence() -> None:
    # The assistant turn is prefilled with "[", so the completion legitimately starts mid-array.
    ranker = claude_ranker(claude_reply('{"index": 0, "score": 0.8, "rationale": "fit"}]'))
    matches = await ranker.rank(FOCUS, [ON_TOPIC])
    assert [match.score for match in matches] == [0.8]
    await ranker.aclose()

    fenced = claude_ranker(claude_reply('```json\n[{"index": 0, "score": 70}]\n```'))
    assert (await fenced.rank(FOCUS, [ON_TOPIC]))[0].score == 0.7
    await fenced.aclose()


@pytest.mark.parametrize(
    "body",
    [
        '[{"index": 9, "score": 90}]',
        '[{"index": -1, "score": 90}]',
        '[{"index": "0", "score": 90}]',
        '[{"index": 0, "score": "high"}]',
        '["not an object"]',
    ],
)
async def test_claude_rankings_that_go_off_script_are_discarded(body: str) -> None:
    ranker = claude_ranker(claude_reply(body))

    with pytest.raises(MatchingError):
        await ranker.rank(FOCUS, [ON_TOPIC])
    await ranker.aclose()


async def test_claude_keeps_the_valid_half_of_a_partly_invalid_ranking() -> None:
    ranker = claude_ranker(
        claude_reply('[{"index": 7, "score": 99}, {"index": 1, "score": 60, "rationale": "ok"}]')
    )

    matches = await ranker.rank(FOCUS, [ON_TOPIC, ADJACENT])

    assert [match.opportunity.opportunity_id for match in matches] == ["adj"]
    await ranker.aclose()


@pytest.mark.parametrize(
    "handler",
    [claude_reply("not json at all"), claude_reply("{}", 500), claude_reply("")],
)
async def test_claude_failures_raise_matching_error(handler: Handler) -> None:
    ranker = claude_ranker(handler)

    with pytest.raises(MatchingError):
        await ranker.rank(FOCUS, [ON_TOPIC])
    await ranker.aclose()


async def test_claude_transport_failure_raises_matching_error() -> None:
    def explode(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection reset")

    ranker = claude_ranker(explode)

    with pytest.raises(MatchingError):
        await ranker.rank(FOCUS, [ON_TOPIC])
    await ranker.aclose()


async def test_fallback_uses_lexical_when_claude_fails() -> None:
    ranker = FallbackMatchRanker(claude_ranker(claude_reply("{}", 503)), LexicalMatchRanker())

    matches = await ranker.rank(FOCUS, [ON_TOPIC, OFF_TOPIC])

    assert ranker.name == "claude+lexical"
    assert [match.opportunity.opportunity_id for match in matches] == ["on"]


async def test_fallback_prefers_claude_when_it_answers() -> None:
    ranker = FallbackMatchRanker(
        claude_ranker(claude_reply('[{"index": 1, "score": 88, "rationale": "claude"}]')),
        LexicalMatchRanker(),
    )

    matches = await ranker.rank(FOCUS, [ON_TOPIC, OFF_TOPIC])

    assert [match.opportunity.opportunity_id for match in matches] == ["off"]
    assert matches[0].rationale == "claude"


async def test_fallback_propagates_an_unusable_focus_without_calling_a_ranker() -> None:
    def unreachable(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Claude should not be called for an invalid focus")

    ranker = FallbackMatchRanker(claude_ranker(unreachable), LexicalMatchRanker())

    with pytest.raises(InvalidQueryError):
        await ranker.rank("   ", [ON_TOPIC])
