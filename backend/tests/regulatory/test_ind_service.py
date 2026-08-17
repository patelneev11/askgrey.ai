from __future__ import annotations

import pytest

from app.services.regulatory import REVIEW_NOTICE
from app.services.regulatory.ind import (
    DraftedIndSection,
    EvidenceKind,
    EvidenceRecord,
    GapKind,
    IndDrafterUnavailableError,
    IndDraftRequest,
    IndRequestError,
    IndSectionDrafter,
    IndService,
    SectionRequest,
    SectionStatus,
)


class StubDrafter:
    """Returns fixed text so the assembly, not a model, is what is under test."""

    name = "stub"

    def __init__(self, *sections: DraftedIndSection, error: Exception | None = None) -> None:
        self._sections = list(sections)
        self._error = error
        self.calls: list[list[str]] = []

    async def draft(
        self, request: IndDraftRequest, sections: list[SectionRequest]
    ) -> list[DraftedIndSection]:
        self.calls.append([entry.section.id for entry in sections])
        if self._error is not None:
            raise self._error
        return list(self._sections)


def as_drafter(stub: StubDrafter) -> IndSectionDrafter:
    return stub


def batch_evidence() -> list[EvidenceRecord]:
    return [
        EvidenceRecord(kind=EvidenceKind.BATCH, label="Batch AG-4471-01", value="1.2", unit="kg"),
        EvidenceRecord(
            kind=EvidenceKind.ASSAY_RESULT,
            label="Assay by HPLC",
            value="99.2",
            unit="%",
            batch_id="AG-4471-01",
        ),
    ]


def request_for(*section_ids: str, evidence: list[EvidenceRecord] | None = None) -> IndDraftRequest:
    return IndDraftRequest(
        program_name="AG-4471",
        substance_name="agrelizumab",
        section_ids=list(section_ids),
        evidence=evidence or [],
    )


@pytest.mark.anyio
async def test_a_drafted_section_carries_the_review_notice_and_its_source() -> None:
    stub = StubDrafter(
        DraftedIndSection(section_id="3.2.S.4.4", text="Batch AG-4471-01 assayed at 99.2 %.")
    )
    service = IndService(as_drafter(stub))

    draft = await service.draft(request_for("3.2.S.4.4", evidence=batch_evidence()))

    assert draft.review_notice == REVIEW_NOTICE
    assert draft.requires_expert_review is True
    section = draft.sections[0]
    assert section.review_notice == REVIEW_NOTICE
    assert section.requires_expert_completion is True
    assert section.status == SectionStatus.DRAFTED
    assert section.source_reference.startswith("M4Q(R1)")
    assert draft.reference.version == service.structure.version


@pytest.mark.anyio
async def test_a_section_with_no_submitted_data_comes_back_empty_and_flagged() -> None:
    stub = StubDrafter()
    service = IndService(as_drafter(stub))

    draft = await service.draft(request_for("3.2.S.4.4"))

    section = draft.sections[0]
    assert section.status == SectionStatus.NOT_DRAFTED
    assert section.text == ""
    assert [gap.kind for gap in section.gaps] == [GapKind.NO_EVIDENCE_SUBMITTED]
    assert stub.calls == [], "no data means nothing to send to the model"


@pytest.mark.anyio
async def test_a_partly_covered_section_names_the_kind_that_is_missing() -> None:
    stub = StubDrafter(
        DraftedIndSection(section_id="3.2.S.4.4", text="Batch AG-4471-01 was manufactured.")
    )
    service = IndService(as_drafter(stub))

    draft = await service.draft(
        request_for("3.2.S.4.4", evidence=[batch_evidence()[0]]),
    )

    section = draft.sections[0]
    assert section.status == SectionStatus.DRAFTED_WITH_GAPS
    missing = [gap.evidence_kind for gap in section.gaps]
    assert EvidenceKind.ASSAY_RESULT in missing


@pytest.mark.anyio
async def test_gaps_the_drafter_reports_are_kept_alongside_the_deterministic_ones() -> None:
    stub = StubDrafter(
        DraftedIndSection(
            section_id="3.2.S.4.4",
            text="Batch AG-4471-01 assayed at 99.2 %.",
            gaps=["No acceptance criterion was provided for the assay."],
        )
    )
    service = IndService(as_drafter(stub))

    draft = await service.draft(request_for("3.2.S.4.4", evidence=batch_evidence()))

    kinds = [gap.kind for gap in draft.sections[0].gaps]
    assert kinds == [GapKind.DRAFTER_REPORTED]
    assert draft.sections[0].status == SectionStatus.DRAFTED_WITH_GAPS


@pytest.mark.anyio
async def test_facts_only_a_person_can_supply_are_flagged_on_module_four_sections() -> None:
    evidence = [
        EvidenceRecord(
            kind=EvidenceKind.NONCLINICAL_STUDY,
            label="28-day rat repeat-dose",
            study_id="TOX-2024-014",
            detail="NOAEL 25 mg/kg/day",
        )
    ]
    stub = StubDrafter(
        DraftedIndSection(section_id="4.2.3.2", text="Study TOX-2024-014 was conducted in rats.")
    )
    service = IndService(as_drafter(stub))

    draft = await service.draft(request_for("4.2.3.2", evidence=evidence))

    author_gaps = [gap for gap in draft.sections[0].gaps if gap.kind == GapKind.AUTHOR_MUST_SUPPLY]
    assert len(author_gaps) == 2
    assert any("312.23(a)(8)" in gap.description for gap in author_gaps)


@pytest.mark.anyio
async def test_data_filed_under_one_section_is_not_reused_elsewhere() -> None:
    evidence = [
        EvidenceRecord(
            kind=EvidenceKind.BATCH,
            label="Batch AG-4471-01",
            section_id="3.2.S.4.4",
        )
    ]
    stub = StubDrafter(DraftedIndSection(section_id="3.2.S.4.4", text="Batch AG-4471-01."))
    service = IndService(as_drafter(stub))

    draft = await service.draft(request_for("3.2.S.4.4", "3.2.P.3.2", evidence=evidence))

    by_id = {section.section_id: section for section in draft.sections}
    assert by_id["3.2.S.4.4"].evidence_used == ["Batch AG-4471-01"]
    assert by_id["3.2.P.3.2"].evidence_used == []
    assert by_id["3.2.P.3.2"].status == SectionStatus.NOT_DRAFTED


@pytest.mark.anyio
async def test_submitted_data_that_no_requested_section_uses_is_reported_back() -> None:
    evidence = [
        *batch_evidence(),
        EvidenceRecord(kind=EvidenceKind.STABILITY_RESULT, label="6-month 25C/60%RH"),
    ]
    stub = StubDrafter(DraftedIndSection(section_id="3.2.S.4.4", text="Batch AG-4471-01."))
    service = IndService(as_drafter(stub))

    draft = await service.draft(request_for("3.2.S.4.4", evidence=evidence))

    assert draft.unused_evidence == ["stability_result: 6-month 25C/60%RH"]


@pytest.mark.anyio
async def test_a_heading_this_service_does_not_draft_is_returned_as_unknown() -> None:
    stub = StubDrafter(DraftedIndSection(section_id="3.2.S.4.4", text="Batch AG-4471-01."))
    service = IndService(as_drafter(stub))

    draft = await service.draft(request_for("3.2.S.4.4", "3.3", "9.9.9", evidence=batch_evidence()))

    assert draft.unknown_section_ids == ["3.3", "9.9.9"]
    assert [section.section_id for section in draft.sections] == ["3.2.S.4.4"]


@pytest.mark.anyio
async def test_a_request_naming_only_undraftable_sections_is_rejected() -> None:
    service = IndService(as_drafter(StubDrafter()))

    with pytest.raises(IndRequestError):
        await service.draft(request_for("3.3", "4.1"))


@pytest.mark.anyio
async def test_a_section_the_drafter_skipped_is_reported_rather_than_dropped() -> None:
    stub = StubDrafter(DraftedIndSection(section_id="3.2.S.4.4", text="Batch AG-4471-01."))
    service = IndService(as_drafter(stub))

    draft = await service.draft(
        request_for(
            "3.2.S.4.4",
            "3.2.S.5",
            evidence=[
                *batch_evidence(),
                EvidenceRecord(
                    kind=EvidenceKind.REFERENCE_STANDARD, label="Primary standard lot 3"
                ),
            ],
        )
    )

    skipped = next(s for s in draft.sections if s.section_id == "3.2.S.5")
    assert skipped.status == SectionStatus.NOT_DRAFTED
    assert [gap.kind for gap in skipped.gaps] == [GapKind.DRAFTER_REPORTED]


@pytest.mark.anyio
async def test_without_credentials_nothing_is_drafted_and_the_failure_is_explicit() -> None:
    service = IndService(None)

    with pytest.raises(IndDrafterUnavailableError):
        await service.draft(request_for("3.2.S.4.4", evidence=batch_evidence()))


def test_the_structure_response_exposes_the_reference_version_and_notice() -> None:
    service = IndService(as_drafter(StubDrafter()))

    response = service.structure_response()

    assert response.review_notice == REVIEW_NOTICE
    assert response.reference.version == service.structure.version
    assert any(section.draftable for section in response.sections)
    assert any(not section.draftable for section in response.sections)
