from __future__ import annotations

from typing import Any

import pytest

from app.services.regulatory.guidelines import (
    GuidelineChecker,
    GuidelineDataset,
    GuidelineInputError,
    Jurisdiction,
    RequirementStatus,
    normalise,
)

# The engine is tested against fixture datasets rather than the shipped ones, so refreshing the
# reference data for a guidance change cannot turn these tests red.
FIXTURE_CITATION = {
    "document": "Fixture guidance, not a real document",
    "url": "https://example.invalid/fixture",
    "document_date": "1 January 2026",
}


def requirement(
    requirement_id: str,
    *,
    ctd_sections: list[str],
    signals: list[list[str]],
    negative_signals: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": requirement_id,
        "title": f"Fixture requirement {requirement_id}",
        "ctd_sections": ctd_sections,
        "citation": FIXTURE_CITATION,
        "expectation": "What a fixture reviewer would look for.",
        "signals": [{"all_of": group} for group in signals],
        "negative_signals": negative_signals or [],
    }


def dataset(*requirements: dict[str, Any], jurisdiction: str = "fda") -> GuidelineDataset:
    return GuidelineDataset.model_validate(
        {
            "jurisdiction": jurisdiction,
            "version": "fixture-1",
            "retrieved": "2026-08-16",
            "notes": "fixture",
            "requirements": list(requirements),
        }
    )


def checker(*requirements: dict[str, Any], min_words: int = 5) -> GuidelineChecker:
    return GuidelineChecker(
        {Jurisdiction.FDA: dataset(*requirements)}, min_words_to_judge=min_words
    )


def filler(words: int) -> str:
    return " ".join(["padding"] * words)


def only(report: Any) -> Any:
    findings = report.jurisdictions[0].findings
    assert len(findings) == 1
    return findings[0]


def test_requirement_is_addressed_and_records_where_each_phrase_matched() -> None:
    engine = checker(
        requirement(
            "stability",
            ctd_sections=["3.2.S.7"],
            signals=[["stability data", "storage condition"]],
        )
    )

    text = f"{filler(20)} Stability data for three batches at the intended storage condition."
    finding = only(engine.check("3.2.S.7", text, [Jurisdiction.FDA]))

    assert finding.status is RequirementStatus.ADDRESSED
    assert finding.matched_signal is not None
    assert finding.matched_signal.group_index == 0
    assert [match.phrase for match in finding.matched_signal.phrases] == [
        "stability data",
        "storage condition",
    ]
    normalised = normalise(text)
    for match in finding.matched_signal.phrases:
        assert normalised[match.offset : match.offset + len(match.phrase)] == match.phrase
        assert match.phrase in match.context


def test_a_group_matches_only_when_every_phrase_is_present() -> None:
    engine = checker(
        requirement(
            "stability",
            ctd_sections=["3.2.S.7"],
            signals=[["stability data", "storage condition"], ["retest period"]],
        )
    )

    partial = only(
        engine.check("3.2.S.7", f"{filler(20)} Stability data are on file.", [Jurisdiction.FDA])
    )
    assert partial.status is RequirementStatus.MISSING
    assert partial.matched_signal is None

    second_group = only(
        engine.check(
            "3.2.S.7", f"{filler(20)} A retest period of 24 months applies.", [Jurisdiction.FDA]
        )
    )
    assert second_group.status is RequirementStatus.ADDRESSED
    assert second_group.matched_signal is not None
    assert second_group.matched_signal.group_index == 1


def test_requirement_is_missing_when_no_group_matches() -> None:
    engine = checker(
        requirement("glp", ctd_sections=["4.2"], signals=[["good laboratory practice"], ["glp"]])
    )

    finding = only(
        engine.check(
            "4.2.3",
            f"{filler(30)} The studies were performed to a high standard.",
            [Jurisdiction.FDA],
        )
    )

    assert finding.status is RequirementStatus.MISSING
    assert "engine does not look for" in finding.explanation


def test_negative_signal_suppresses_an_otherwise_addressed_requirement() -> None:
    engine = checker(
        requirement(
            "glp",
            ctd_sections=["4.2"],
            signals=[["glp"]],
            negative_signals=["glp status to be confirmed"],
        )
    )

    finding = only(
        engine.check(
            "4.2.3",
            f"{filler(20)} GLP compliance: GLP status to be confirmed before submission.",
            [Jurisdiction.FDA],
        )
    )

    assert finding.status is RequirementStatus.INDETERMINATE
    assert finding.suppressed_by is not None
    assert finding.suppressed_by.phrase == "glp status to be confirmed"
    # The positive match is still reported, so a reviewer can see what was overridden.
    assert finding.matched_signal is not None


def test_negative_signal_alone_also_yields_indeterminate() -> None:
    engine = checker(
        requirement(
            "glp",
            ctd_sections=["4.2"],
            signals=[["good laboratory practice"]],
            negative_signals=["glp status to be confirmed"],
        )
    )

    finding = only(
        engine.check("4.2.3", f"{filler(20)} GLP status to be confirmed.", [Jurisdiction.FDA])
    )

    assert finding.status is RequirementStatus.INDETERMINATE
    assert finding.matched_signal is None
    assert finding.suppressed_by is not None


@pytest.mark.parametrize("words", [0, 1, 39])
def test_short_sections_are_indeterminate_even_when_a_signal_matches(words: int) -> None:
    """A stub section must never read as addressed: 40 words is the shipped floor."""
    engine = GuidelineChecker(
        {Jurisdiction.FDA: dataset(requirement("glp", ctd_sections=["4.2"], signals=[["glp"]]))}
    )
    text = ("GLP " + filler(max(0, words - 1))).strip()

    report = engine.check("4.2.3", text or "x", [Jurisdiction.FDA])
    finding = only(report)

    assert report.min_words_to_judge == 40
    assert finding.status is RequirementStatus.INDETERMINATE
    assert "too short" in finding.explanation


def test_a_long_enough_section_crosses_the_floor() -> None:
    engine = GuidelineChecker(
        {Jurisdiction.FDA: dataset(requirement("glp", ctd_sections=["4.2"], signals=[["glp"]]))}
    )

    finding = only(engine.check("4.2.3", f"GLP {filler(39)}", [Jurisdiction.FDA]))

    assert finding.status is RequirementStatus.ADDRESSED


def test_module_three_requirements_are_not_evaluated_against_a_module_four_section() -> None:
    engine = checker(
        requirement("quality", ctd_sections=["3.2.S.4"], signals=[["specification"]]),
        requirement("nonclinical", ctd_sections=["4.2.3"], signals=[["specification"]]),
    )

    text = f"{filler(20)} The specification is appended."
    module_four = engine.check("4.2.3", text, [Jurisdiction.FDA]).jurisdictions[0]

    assert [finding.requirement_id for finding in module_four.findings] == ["nonclinical"]
    assert module_four.out_of_scope_requirement_ids == ["quality"]


def test_scoping_matches_subsections_and_parent_sections_in_both_directions() -> None:
    engine = checker(requirement("tox", ctd_sections=["4.2.3"], signals=[["toxicology"]]))

    for section_id in ("4.2.3", "4.2.3.2", "4.2", "4"):
        findings = engine.check(section_id, filler(50), [Jurisdiction.FDA]).jurisdictions[0]
        assert [finding.requirement_id for finding in findings.findings] == ["tox"], section_id
        assert findings.findings[0].matched_scope == "4.2.3"

    assert engine.check("4.3", filler(50), [Jurisdiction.FDA]).jurisdictions[0].findings == []


def test_section_ids_are_compared_case_insensitively() -> None:
    engine = checker(requirement("ds", ctd_sections=["3.2.S.4"], signals=[["specification"]]))

    findings = engine.check("3.2.s.4.1", filler(50), [Jurisdiction.FDA]).jurisdictions[0].findings

    assert [finding.requirement_id for finding in findings] == ["ds"]


@pytest.mark.parametrize(
    "written",
    [
        "non-clinical overview",
        "Non-Clinical Overview",
        "non\u2011clinical   overview",
        "non clinical\noverview",
        "NON-CLINICAL\tOVERVIEW",
    ],
)
def test_normalisation_folds_case_hyphenation_and_whitespace(written: str) -> None:
    engine = checker(
        requirement("overview", ctd_sections=["2.4"], signals=[["non-clinical overview"]])
    )

    finding = only(engine.check("2.4", f"{filler(20)} {written} follows.", [Jurisdiction.FDA]))

    assert finding.status is RequirementStatus.ADDRESSED


def test_phrases_match_on_word_boundaries_only() -> None:
    engine = checker(requirement("glp", ctd_sections=["4.2"], signals=[["glp"]]))

    finding = only(
        engine.check("4.2.3", f"{filler(30)} The GLPS registry is unrelated.", [Jurisdiction.FDA])
    )

    assert finding.status is RequirementStatus.MISSING


def test_report_carries_the_review_marker_limitations_and_reference_vintage() -> None:
    engine = checker(requirement("glp", ctd_sections=["4.2"], signals=[["glp"]]))

    report = engine.check("4.2.3", filler(50), [Jurisdiction.FDA])

    assert report.requires_expert_review is True
    assert "qualified regulatory affairs" in report.review_notice
    assert "dated snapshot" in report.limitations
    assert report.jurisdictions[0].version == "fixture-1"
    assert report.jurisdictions[0].retrieved.isoformat() == "2026-08-16"
    assert report.counts()[RequirementStatus.MISSING] == 1


def test_repeated_jurisdictions_are_evaluated_once() -> None:
    engine = checker(requirement("glp", ctd_sections=["4.2"], signals=[["glp"]]))

    report = engine.check("4.2.3", filler(50), [Jurisdiction.FDA, Jurisdiction.FDA])

    assert [block.jurisdiction for block in report.jurisdictions] == [Jurisdiction.FDA]


def test_checking_is_deterministic() -> None:
    engine = checker(
        requirement("glp", ctd_sections=["4.2"], signals=[["glp"]]),
        requirement("tox", ctd_sections=["4.2.3"], signals=[["integrated summary"]]),
    )
    text = f"{filler(40)} GLP compliant studies, no integrated summary yet."

    first = engine.check("4.2.3", text, [Jurisdiction.FDA])
    second = engine.check("4.2.3", text, [Jurisdiction.FDA])

    assert first.model_dump() == second.model_dump()


def test_unknown_and_empty_inputs_are_rejected() -> None:
    engine = checker(requirement("glp", ctd_sections=["4.2"], signals=[["glp"]]))

    with pytest.raises(GuidelineInputError):
        engine.check("   ", filler(50), [Jurisdiction.FDA])
    with pytest.raises(GuidelineInputError):
        engine.check("4.2.3", filler(50), [])
    with pytest.raises(GuidelineInputError):
        engine.check("4.2.3", filler(50), [Jurisdiction.PMDA])


def test_a_signal_phrase_that_normalises_to_nothing_is_rejected() -> None:
    with pytest.raises(ValueError):
        dataset(requirement("empty", ctd_sections=["4.2"], signals=[["---"]]))


def test_duplicate_requirement_ids_are_rejected() -> None:
    with pytest.raises(ValueError):
        dataset(
            requirement("same", ctd_sections=["4.2"], signals=[["glp"]]),
            requirement("same", ctd_sections=["4.2"], signals=[["glp"]]),
        )
