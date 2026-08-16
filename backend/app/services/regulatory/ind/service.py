from __future__ import annotations

from app.core.config import Settings, get_settings

from .drafter import ClaudeIndDrafter, DraftedIndSection, IndSectionDrafter, SectionRequest
from .errors import IndDrafterUnavailableError, IndRequestError
from .gaps import evidence_for, gaps_for, unused
from .models import (
    Gap,
    GapKind,
    IndDraft,
    IndDraftRequest,
    IndSection,
    SectionStatus,
    StructureResponse,
)
from .structure import CtdStructure, Section, load_structure


class IndService:
    """
    Drafts CTD-shaped IND sections from submitted data, and says what is missing.

    A drafting aid, not an autofill. Which sections exist comes from a dated transcription of
    ICH M4Q/M4S; whether a section could be drafted at all is decided from the submitted data
    before the model is called, so a section with no data behind it comes back visibly empty
    instead of plausibly full.
    """

    def __init__(
        self, drafter: IndSectionDrafter | None = None, structure: CtdStructure | None = None
    ) -> None:
        self.drafter = drafter
        self.structure = structure or load_structure()

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> IndService:
        settings = settings or get_settings()
        drafter: IndSectionDrafter | None = None
        if settings.anthropic_api_key:
            drafter = ClaudeIndDrafter(
                api_key=settings.anthropic_api_key,
                model=settings.llm_model,
                base_url=settings.anthropic_base_url,
                anthropic_version=settings.anthropic_version,
                max_tokens=settings.regulatory_max_tokens,
                timeout=settings.regulatory_timeout_seconds,
            )
        return cls(drafter)

    async def aclose(self) -> None:
        drafter = self.drafter
        if isinstance(drafter, ClaudeIndDrafter):
            await drafter.aclose()

    def structure_response(self) -> StructureResponse:
        return StructureResponse(
            reference=self.structure.reference_info(), sections=self.structure.outline()
        )

    async def draft(self, request: IndDraftRequest) -> IndDraft:
        known: list[Section] = []
        unknown: list[str] = []
        for section_id in request.section_ids:
            section = self.structure.get(section_id)
            if section is None or not section.draftable:
                unknown.append(section_id)
            elif all(section.id != seen.id for seen in known):
                known.append(section)
        if not known:
            raise IndRequestError(
                "none of the requested section ids are sections this service drafts; "
                "see GET /api/regulatory/ind/structure"
            )

        used: set[int] = set()
        to_draft: list[SectionRequest] = []
        empty: list[Section] = []
        for section in known:
            records = evidence_for(section, request.evidence)
            if records:
                used.update(
                    index
                    for index, record in enumerate(request.evidence)
                    if any(record is chosen for chosen in records)
                )
                to_draft.append(SectionRequest(section=section, records=records))
            else:
                empty.append(section)

        drafted: list[DraftedIndSection] = []
        if to_draft:
            if self.drafter is None:
                raise IndDrafterUnavailableError(
                    "no LLM credentials are configured; set ANTHROPIC_API_KEY"
                )
            drafted = await self.drafter.draft(request, to_draft)

        return self.build_draft(request, known, drafted, used)

    def build_draft(
        self,
        request: IndDraftRequest,
        known: list[Section],
        drafted: list[DraftedIndSection],
        used: set[int],
    ) -> IndDraft:
        """Assemble the response. Separate from the LLM call so tests can assemble fixed text."""
        by_id = {entry.section_id: entry for entry in drafted}
        sections: list[IndSection] = []
        for section in known:
            records = evidence_for(section, request.evidence)
            gaps = gaps_for(section, records)
            entry = by_id.get(section.id)
            if entry is None:
                status = SectionStatus.NOT_DRAFTED
                text = ""
                if records:
                    gaps.append(
                        Gap(
                            kind=GapKind.DRAFTER_REPORTED,
                            description="The drafter returned no text for this section.",
                        )
                    )
            else:
                text = entry.text
                gaps.extend(
                    Gap(kind=GapKind.DRAFTER_REPORTED, description=description)
                    for description in entry.gaps
                )
                status = SectionStatus.DRAFTED_WITH_GAPS if gaps else SectionStatus.DRAFTED
            sections.append(
                IndSection(
                    section_id=section.id,
                    title=section.title,
                    module=section.module,
                    status=status,
                    text=text,
                    gaps=gaps,
                    evidence_used=[record.label for record in records],
                    source_reference=self.structure.source_reference(section),
                )
            )

        unknown = [
            section_id
            for section_id in request.section_ids
            if all(section_id.strip() != section.id for section in known)
        ]
        return IndDraft(
            program_name=request.program_name,
            sections=sections,
            unknown_section_ids=unknown,
            unused_evidence=unused(request.evidence, used),
            reference=self.structure.reference_info(),
        )
