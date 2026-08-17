from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest

from app.services.grants.review_board import (
    ClaudePersonaReviewer,
    CriterionScore,
    PersonaReview,
    PersonaSpec,
    ProposalSection,
    ReviewBoard,
    ReviewBoardError,
)

# A draft in the register the personas are prompted to read: specific enough to score, and
# deliberately missing the sample-size justification the biostatistician persona asks for.
APPROACH_TEXT = """\
Aim 1 tests whether patient-derived pancreatic organoids predict response to our mRNA
neoantigen construct. Organoids from resected PDAC specimens will be expanded and exposed to
autologous T cells primed with the construct, with cytotoxicity read out by live-cell imaging
at 24, 48 and 72 hours. Responders and non-responders will be compared against the donor's
recorded clinical course. Aim 2 establishes a dose-response relationship in an orthotopic
murine model, with tumour volume as the primary endpoint and survival as a secondary endpoint.
Animals will be randomized to vehicle, low dose and high dose arms, and the analysis will use
standard statistics on adequately powered groups. Aim 3 prepares the IND-enabling package:
manufacturing will be transferred to a contract manufacturer and a GLP toxicology study will
follow the murine work. Commercially, the assay is expected to be adopted by academic centres
and by pharmaceutical partners running immunotherapy trials.
"""


def section(**overrides: Any) -> ProposalSection:
    """The section every test reviews, so a test changes exactly one thing about the input."""
    base: dict[str, Any] = {
        "section_name": "Approach",
        "program": "SBIR",
        "phase": "Phase I",
        "text": APPROACH_TEXT,
    }
    base.update(overrides)
    return ProposalSection(**base)


def claude_reply(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 900, "output_tokens": 300},
        },
    )


def requested_criteria(prompt: str) -> list[str]:
    """The criteria the board asked this persona for, read back out of the rendered prompt."""
    block = re.search(r"<criteria>\n(.*?)\n</criteria>", prompt, re.DOTALL)
    assert block, "the prompt carried no <criteria> block"
    return [line.removeprefix("- ") for line in block.group(1).splitlines() if line.strip()]


class ScriptedClaude(httpx.AsyncBaseTransport):
    """
    Stands in for Anthropic: one well-formed review per persona, never a network call.

    Each reply scores exactly the criteria that persona's prompt asked for, so a test that
    changes the configured criteria does not also have to rewrite a recorded response. `extra`
    entries are appended verbatim, which is how the malformed-score tests inject a bad score.
    """

    def __init__(
        self,
        *,
        score: int = 4,
        extra: list[dict[str, Any]] | None = None,
        replace_scores: list[dict[str, Any]] | None = None,
        body: str | None = None,
        status_code: int = 200,
        error: Exception | None = None,
    ) -> None:
        self.score = score
        self.extra = extra or []
        self.replace_scores = replace_scores
        self.body = body
        self.status_code = status_code
        self.error = error
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.status_code >= 400:
            return httpx.Response(self.status_code, json={"error": {"message": "boom"}})
        payload = json.loads(request.content.decode())
        prompt = payload["messages"][0]["content"]
        if self.body is not None:
            return claude_reply(self.body)
        scores: list[dict[str, Any]] = (
            list(self.replace_scores)
            if self.replace_scores is not None
            else [
                {
                    "criterion": criterion,
                    "score": self.score,
                    "reasoning": f"{criterion} is argued but thinly evidenced.",
                }
                for criterion in requested_criteria(prompt)
            ]
        )
        return claude_reply(
            json.dumps(
                {
                    "scores": scores + self.extra,
                    "strengths": ["The organoid readout is concrete and measurable."],
                    "weaknesses": ["No power calculation is given for any aim."],
                    "comment": "Reviewable, but the plan is asserted rather than shown.",
                }
            )
        )

    def systems(self) -> list[str]:
        return [json.loads(request.content.decode())["system"] for request in self.requests]

    def prompts(self) -> list[str]:
        return [
            json.loads(request.content.decode())["messages"][0]["content"]
            for request in self.requests
        ]


def reviewer(transport: httpx.AsyncBaseTransport) -> ClaudePersonaReviewer:
    return ClaudePersonaReviewer(api_key="test-key", model="claude-sonnet-4-5", transport=transport)


def make_board(transport: httpx.AsyncBaseTransport | None = None) -> ReviewBoard:
    """The shipped personas, reviewed by a scripted Claude unless a transport is given."""
    return ReviewBoard.from_config_file(reviewer=reviewer(transport or ScriptedClaude()))


class StubReviewer:
    """A reviewer with no HTTP at all, for the endpoint tests."""

    def __init__(self, *, model: str = "claude-sonnet-4-5", error: Exception | None = None) -> None:
        self.model = model
        self.error = error
        self.calls: list[str] = []

    async def review(
        self, persona: PersonaSpec, criteria: list[str], section: ProposalSection
    ) -> PersonaReview:
        self.calls.append(persona.id)
        if self.error is not None:
            raise self.error
        scores = [
            CriterionScore(criterion=criterion, score=4, reasoning="Argued but thinly evidenced.")
            for criterion in criteria
        ]
        return PersonaReview(
            persona_id=persona.id,
            persona_name=persona.name,
            focus=persona.focus,
            scores=scores,
            overall_score=4.0,
            strengths=["The organoid readout is concrete."],
            weaknesses=["No power calculation is given."],
            comment="Reviewable, but the quantitative plan is asserted rather than shown.",
        )


@pytest.fixture
def board() -> ReviewBoard:
    return make_board()


@pytest.fixture
def failing_reviewer() -> StubReviewer:
    return StubReviewer(error=ReviewBoardError("Claude returned HTTP 529"))
