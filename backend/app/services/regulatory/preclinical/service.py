from __future__ import annotations

from app.core.config import Settings, get_settings

from .audit import AUDITOR_VERSION, audit_narrative
from .drafter import ClaudeNarrativeDrafter, DraftedSection, NarrativeDrafter
from .errors import DrafterUnavailableError, PreclinicalRequestError
from .models import SECTION_HEADINGS, NarrativeSection, PreclinicalReport, StudyTable


class PreclinicalService:
    """
    Drafts a preclinical study narrative, then audits its own output against the source table.

    Two stages, and the split matters: the drafting stage is a language model and is therefore
    treated as untrusted, while the auditing stage is deterministic decimal comparison against
    the submitted record. Every number the model wrote is checked, and anything the check
    cannot trace to the record comes back as a flag rather than being quietly accepted.
    """

    def __init__(self, drafter: NarrativeDrafter | None = None) -> None:
        self.drafter = drafter

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> PreclinicalService:
        settings = settings or get_settings()
        drafter: NarrativeDrafter | None = None
        if settings.anthropic_api_key:
            drafter = ClaudeNarrativeDrafter(
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
        if isinstance(drafter, ClaudeNarrativeDrafter):
            await drafter.aclose()

    async def draft_report(self, table: StudyTable) -> PreclinicalReport:
        if not table.groups and not table.findings and not table.measurements:
            raise PreclinicalRequestError(
                "the study table needs at least one dose group, finding or study-level value"
            )
        if self.drafter is None:
            raise DrafterUnavailableError(
                "no LLM credentials are configured; set ANTHROPIC_API_KEY"
            )
        drafted = await self.drafter.draft(table)
        return self.build_report(table, drafted)

    def build_report(self, table: StudyTable, drafted: list[DraftedSection]) -> PreclinicalReport:
        """
        Assemble the report. Kept separate from the LLM call so tests can audit fixed prose.

        A section the drafter skipped is reported as missing rather than dropped: a report
        showing two of three sections with no explanation reads as if the third was not needed.
        """
        by_key = {section.key: section for section in drafted}
        sections: list[NarrativeSection] = []
        for key, heading in SECTION_HEADINGS.items():
            source = by_key.get(key)
            if source is None:
                sections.append(
                    NarrativeSection(
                        key=key,
                        heading=heading,
                        text="",
                        gaps=["The drafter returned no text for this section."],
                    )
                )
                continue
            sections.append(
                NarrativeSection(key=key, heading=heading, text=source.text, gaps=source.gaps)
            )

        discrepancies, summary = audit_narrative(sections, table)
        return PreclinicalReport(
            study_id=table.study_id,
            sections=sections,
            discrepancies=discrepancies,
            audit=summary,
        )


__all__ = ["AUDITOR_VERSION", "PreclinicalService"]
