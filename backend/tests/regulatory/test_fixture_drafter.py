"""
The development-only fixture drafter, which exists so the audit's flagged view is reachable.

These tests pin the two properties that make it safe to run behind a flag: it always produces
flags (otherwise it does not serve its purpose), and it always announces itself as a fixture in
the report and in every section's gaps (otherwise it is fabricated content presented as a draft).
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.regulatory.preclinical import (
    FIXTURE_DRAFTER_NAME,
    FIXTURE_GAP,
    DiscrepancyKind,
    FixtureNarrativeDrafter,
    PreclinicalService,
    Severity,
    StudyTable,
)


@pytest.mark.asyncio
async def test_the_fixture_narrative_is_flagged_by_the_auditor(study: StudyTable) -> None:
    service = PreclinicalService(FixtureNarrativeDrafter())

    report = await service.draft_report(study)

    assert report.discrepancies, "the fixture drafter must produce something for the audit to flag"
    kinds = {flag.kind for flag in report.discrepancies}
    assert DiscrepancyKind.CONTRADICTED_VALUE in kinds
    assert DiscrepancyKind.UNSUPPORTED_NUMBER in kinds
    assert report.audit.numbers_flagged == len(report.discrepancies)


@pytest.mark.asyncio
async def test_the_contradicted_value_names_the_source_it_disagrees_with(
    study: StudyTable,
) -> None:
    service = PreclinicalService(FixtureNarrativeDrafter())

    report = await service.draft_report(study)

    contradicted = next(
        flag for flag in report.discrepancies if flag.kind is DiscrepancyKind.CONTRADICTED_VALUE
    )
    assert contradicted.severity is Severity.CRITICAL
    assert contradicted.source_label == "NOAEL"
    assert contradicted.source_value == "25 mg/kg/day"
    # Double the recorded 25 mg/kg/day, which is what the fixture writes.
    assert contradicted.narrative_value.startswith("50")
    assert contradicted.context
    assert contradicted.explanation


@pytest.mark.asyncio
async def test_the_report_and_every_section_say_the_text_is_fixture_output(
    study: StudyTable,
) -> None:
    service = PreclinicalService(FixtureNarrativeDrafter())

    report = await service.draft_report(study)

    assert report.fixture_draft is True
    assert report.drafter == FIXTURE_DRAFTER_NAME
    assert all(FIXTURE_GAP in section.gaps for section in report.sections)
    assert all(section.requires_expert_review for section in report.sections)


@pytest.mark.asyncio
async def test_a_sparse_study_table_still_produces_flags() -> None:
    """A table with no named values and no findings must not silently produce a clean report."""
    service = PreclinicalService(FixtureNarrativeDrafter())
    sparse = StudyTable.model_validate(
        {
            "study_id": "TOX-9",
            "groups": [{"label": "High", "dose": {"value": "10", "unit": "mg/kg/day"}}],
        }
    )

    report = await service.draft_report(sparse)

    assert report.discrepancies
    assert report.fixture_draft is True


def test_a_claude_backed_report_is_not_marked_as_a_fixture(study: StudyTable) -> None:
    settings = Settings(anthropic_api_key="test-key")
    service = PreclinicalService.from_settings(settings)

    report = service.build_report(study, [])

    assert report.fixture_draft is False
    assert report.drafter == "claude"


def test_the_fixture_flag_selects_the_fixture_drafter_in_development() -> None:
    settings = Settings(environment="development", regulatory_fixture_drafter=True)

    service = PreclinicalService.from_settings(settings)

    assert isinstance(service.drafter, FixtureNarrativeDrafter)


def test_the_fixture_flag_cannot_be_enabled_outside_development() -> None:
    with pytest.raises(ValueError, match="development-only"):
        Settings(
            environment="production",
            regulatory_fixture_drafter=True,
            jwt_secret="a" * 64,
            database_url="postgresql://user:pw@db.internal/askgrey",
            cors_origins="https://app.askgrey.ai",
        )
