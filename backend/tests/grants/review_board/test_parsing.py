from __future__ import annotations

import pytest

from app.services.grants.review_board import PersonaSpec, ReviewBoardError, parse_review

from .conftest import make_board

BIOSTATISTICIAN = "strict_biostatistician"
CORE = ["Significance", "Innovation", "Approach"]


def persona(**overrides: object) -> PersonaSpec:
    base: dict[str, object] = {
        "id": "p",
        "name": "Test Persona",
        "focus": "everything",
        "system_prompt": "You review.",
    }
    base.update(overrides)
    return PersonaSpec(**base)


def test_a_completion_of_the_prefilled_brace_is_parsed() -> None:
    body = '"scores": [{"criterion": "Approach", "score": 5, "reasoning": "Thin."}]}'

    review = parse_review(body, persona(), CORE)

    assert [(s.criterion, s.score) for s in review.scores] == [("Approach", 5)]
    assert review.overall_score == 5.0


def test_code_fenced_json_is_parsed() -> None:
    body = '```json\n{"scores": [{"criterion": "Innovation", "score": 2}]}\n```'

    assert parse_review(body, persona(), CORE).scores[0].criterion == "Innovation"


def test_a_criterion_is_matched_case_insensitively_and_reported_as_configured() -> None:
    body = '{"scores": [{"criterion": "approach", "score": 3}]}'

    assert parse_review(body, persona(), CORE).scores[0].criterion == "Approach"


@pytest.mark.parametrize(
    "score",
    ["0", "10", "-3", '"high"', "null", "true", "4.5", '"5"'],
    ids=["below", "above", "negative", "text", "null", "bool", "fractional", "stringy"],
)
def test_a_score_outside_one_to_nine_is_discarded_rather_than_coerced(score: str) -> None:
    body = (
        '{"scores": ['
        f'{{"criterion": "Significance", "score": {score}}},'
        '{"criterion": "Approach", "score": 6}]}'
    )

    review = parse_review(body, persona(), CORE)

    assert [(s.criterion, s.score) for s in review.scores] == [("Approach", 6)]
    assert review.overall_score == 6.0


def test_a_criterion_that_was_not_asked_for_is_dropped() -> None:
    body = (
        '{"scores": [{"criterion": "Vibes", "score": 1},' '{"criterion": "Approach", "score": 7}]}'
    )

    assert [s.criterion for s in parse_review(body, persona(), CORE).scores] == ["Approach"]


def test_a_repeated_criterion_is_scored_once() -> None:
    body = (
        '{"scores": [{"criterion": "Approach", "score": 3},'
        '{"criterion": "Approach", "score": 8}]}'
    )

    review = parse_review(body, persona(), CORE)

    assert [(s.criterion, s.score) for s in review.scores] == [("Approach", 3)]


def test_scores_are_reported_in_the_configured_criterion_order() -> None:
    body = (
        '{"scores": [{"criterion": "Approach", "score": 3},'
        '{"criterion": "Significance", "score": 4},'
        '{"criterion": "Innovation", "score": 5}]}'
    )

    assert [s.criterion for s in parse_review(body, persona(), CORE).scores] == CORE


def test_a_reply_with_no_usable_score_is_a_failed_review_not_an_empty_one() -> None:
    body = '{"scores": [{"criterion": "Approach", "score": 99}], "comment": "hmm"}'

    with pytest.raises(ReviewBoardError, match="no score"):
        parse_review(body, persona(), CORE)


def test_a_reply_that_is_not_json_is_a_failed_review() -> None:
    with pytest.raises(ReviewBoardError, match="valid JSON"):
        parse_review("I would rather write prose.", persona(), CORE)


def test_a_reply_without_a_scores_array_is_a_failed_review() -> None:
    with pytest.raises(ReviewBoardError, match="scores array"):
        parse_review('{"comment": "looks fine"}', persona(), CORE)


def test_non_string_strengths_are_dropped_without_failing_the_review() -> None:
    body = (
        '{"scores": [{"criterion": "Approach", "score": 4}],'
        '"strengths": ["Concrete readout", 7, "  "], "weaknesses": "not a list"}'
    )

    review = parse_review(body, persona(), CORE)

    assert review.strengths == ["Concrete readout"]
    assert review.weaknesses == []


def test_the_persona_listing_does_not_expose_prompt_text() -> None:
    listing = make_board().personas()

    assert [entry.id for entry in listing] == [
        BIOSTATISTICIAN,
        "commercialization_critic",
        "translational_safety_reviewer",
    ]
    for entry in listing:
        assert entry.criteria[:3] == CORE
        assert "system_prompt" not in entry.model_dump()
