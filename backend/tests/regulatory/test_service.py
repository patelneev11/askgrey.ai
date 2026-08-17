from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.regulatory import REVIEW_NOTICE
from app.services.regulatory.preclinical import (
    AUDITOR_VERSION,
    DiscrepancyKind,
    DraftedSection,
    DrafterUnavailableError,
    DraftStatus,
    PreclinicalRequestError,
    PreclinicalService,
    SectionKey,
    StudyTable,
)
from tests.regulatory.conftest import StubDrafter, as_drafter

DESIGN = DraftedSection(
    key=SectionKey.STUDY_DESIGN,
    text="Rats received AG-4471 by oral gavage for 28 days at 0, 25, 75 and 150 mg/kg/day.",
)
RESULTS = DraftedSection(
    key=SectionKey.RESULTS,
    text="ALT was increased 2.4 x in 7/20 animals at 150 mg/kg/day.",
    gaps=["Histopathology tables were not submitted."],
)
BAD_INTERPRETATION = DraftedSection(
    key=SectionKey.INTERPRETATION, text="The NOAEL was 50 mg/kg/day."
)


@pytest.mark.asyncio
async def test_a_report_carries_the_review_notice_on_itself_and_on_every_section(
    study: StudyTable,
) -> None:
    service = PreclinicalService(as_drafter(StubDrafter(DESIGN, RESULTS, BAD_INTERPRETATION)))

    report = await service.draft_report(study)

    assert report.requires_expert_review is True
    assert report.review_notice == REVIEW_NOTICE
    assert [section.key for section in report.sections] == list(SectionKey)
    for section in report.sections:
        assert section.requires_expert_review is True
        assert section.review_notice == REVIEW_NOTICE
        assert section.draft_status is DraftStatus.FIRST_DRAFT


@pytest.mark.asyncio
async def test_the_audit_runs_over_the_assembled_report(study: StudyTable) -> None:
    service = PreclinicalService(as_drafter(StubDrafter(DESIGN, RESULTS, BAD_INTERPRETATION)))

    report = await service.draft_report(study)

    assert [flag.kind for flag in report.discrepancies] == [DiscrepancyKind.CONTRADICTED_VALUE]
    assert report.discrepancies[0].section is SectionKey.INTERPRETATION
    assert report.audit.auditor_version == AUDITOR_VERSION
    assert report.audit.numbers_flagged == 1
    assert report.audit.source_values > 0


@pytest.mark.asyncio
async def test_a_section_the_drafter_skipped_is_reported_as_a_gap_not_dropped(
    study: StudyTable,
) -> None:
    service = PreclinicalService(as_drafter(StubDrafter(DESIGN)))

    report = await service.draft_report(study)

    skipped = [section for section in report.sections if section.key is not SectionKey.STUDY_DESIGN]
    assert len(skipped) == 2
    for section in skipped:
        assert section.text == ""
        assert section.gaps == ["The drafter returned no text for this section."]


@pytest.mark.asyncio
async def test_gaps_the_drafter_reported_are_preserved(study: StudyTable) -> None:
    service = PreclinicalService(as_drafter(StubDrafter(DESIGN, RESULTS)))

    report = await service.draft_report(study)

    results = next(section for section in report.sections if section.key is SectionKey.RESULTS)
    assert results.gaps == ["Histopathology tables were not submitted."]


@pytest.mark.asyncio
async def test_an_empty_study_table_is_refused_before_any_llm_call() -> None:
    stub = StubDrafter(DESIGN)
    service = PreclinicalService(as_drafter(stub))

    with pytest.raises(PreclinicalRequestError):
        await service.draft_report(StudyTable(study_id="TOX-4"))

    assert stub.calls == []


@pytest.mark.asyncio
async def test_without_credentials_the_service_refuses_rather_than_inventing_a_narrative(
    study: StudyTable,
) -> None:
    service = PreclinicalService.from_settings(Settings(anthropic_api_key=""))

    with pytest.raises(DrafterUnavailableError):
        await service.draft_report(study)
    await service.aclose()


def test_configured_credentials_produce_a_claude_drafter() -> None:
    service = PreclinicalService.from_settings(Settings(anthropic_api_key="test-key"))

    assert service.drafter is not None
    assert service.drafter.name == "claude"
