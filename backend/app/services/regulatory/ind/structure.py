from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .models import EvidenceKind, ReferenceInfo, SectionOutline

REFERENCE_DIR = Path(__file__).resolve().parent / "reference"
STRUCTURE_FILE = REFERENCE_DIR / "ctd_structure.json"

# 21 CFR 312.23(a)(8) asks who evaluated the nonclinical results and concluded it is reasonably
# safe to begin, and where the studies were run and the records are kept. Those are facts about
# people and places; a drafter that invents them is fabricating. They are emitted as gaps.
AUTHOR_SUPPLIED_BY_SECTION: dict[str, tuple[str, ...]] = {
    "4.2": (
        "Identification and qualifications of the individuals who evaluated these results and "
        "concluded it is reasonably safe to begin the proposed investigations "
        "(21 CFR 312.23(a)(8)).",
        "Where the studies were conducted and where the records are available for inspection "
        "(21 CFR 312.23(a)(8)).",
    ),
    "3.2.S.2.1": ("Name, address and responsibility of each manufacturing site.",),
    "3.2.P.3.1": ("Name, address and responsibility of each manufacturing site.",),
    "3.2.A.1": ("Facility and equipment detail for each named site.",),
}


class Section(BaseModel):
    """One heading from the transcribed CTD tree."""

    model_config = ConfigDict(extra="forbid")

    id: str
    module: str
    title: str
    requires: list[EvidenceKind] = Field(default_factory=list)

    @property
    def draftable(self) -> bool:
        return bool(self.requires)

    def author_supplied(self) -> tuple[str, ...]:
        """Facts no drafter can supply, inherited from the nearest ancestor that declares any."""
        parts = self.id.split(".")
        for cut in range(len(parts), 0, -1):
            ancestor = ".".join(parts[:cut])
            if ancestor in AUTHOR_SUPPLIED_BY_SECTION:
                return AUTHOR_SUPPLIED_BY_SECTION[ancestor]
        return ()


class CtdStructure(BaseModel):
    """
    The dated transcription of the Module 3 and Module 4 heading trees.

    Held as data in `reference/ctd_structure.json` rather than in a prompt so a draft can say
    which version of the tree produced it, and so refreshing the tree is a data change.
    """

    model_config = ConfigDict(extra="forbid")

    version: str
    retrieved: str
    sources: list[dict[str, str]]
    notes: list[str] = Field(default_factory=list)
    sections: list[Section]

    def reference_info(self) -> ReferenceInfo:
        return ReferenceInfo.model_validate(
            {
                "version": self.version,
                "retrieved": self.retrieved,
                "sources": self.sources,
                "notes": self.notes,
            }
        )

    def get(self, section_id: str) -> Section | None:
        wanted = section_id.strip()
        return next((section for section in self.sections if section.id == wanted), None)

    def outline(self) -> list[SectionOutline]:
        return [
            SectionOutline(
                id=section.id,
                module=section.module,
                title=section.title,
                requires=section.requires,
                draftable=section.draftable,
            )
            for section in self.sections
        ]

    def source_reference(self, section: Section) -> str:
        """The document a heading was transcribed from, carried on every drafted section."""
        for source in self.sources:
            if source.get("covers", "").startswith(f"Module {section.module}"):
                return f"{source['id']} ({source['document_date']}) — {source['url']}"
        return ""


@lru_cache(maxsize=1)
def load_structure() -> CtdStructure:
    return CtdStructure.model_validate(json.loads(STRUCTURE_FILE.read_text(encoding="utf-8")))
