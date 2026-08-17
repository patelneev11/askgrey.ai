"""
IND Module 3 / Module 4 section drafting against a dated transcription of the CTD tree.

A drafting aid: sections come back marked as first drafts requiring expert completion, and
anything the submitted data does not cover is reported as a gap rather than written as prose.
"""

from .drafter import ClaudeIndDrafter, DraftedIndSection, IndSectionDrafter, SectionRequest
from .errors import IndDrafterError, IndDrafterUnavailableError, IndError, IndRequestError
from .models import (
    EvidenceKind,
    EvidenceRecord,
    Gap,
    GapKind,
    IndDraft,
    IndDraftRequest,
    IndSection,
    ReferenceInfo,
    SectionOutline,
    SectionStatus,
    StructureResponse,
)
from .service import IndService
from .structure import CtdStructure, Section, load_structure

__all__ = [
    "ClaudeIndDrafter",
    "CtdStructure",
    "DraftedIndSection",
    "EvidenceKind",
    "EvidenceRecord",
    "Gap",
    "GapKind",
    "IndDraft",
    "IndDraftRequest",
    "IndDrafterError",
    "IndDrafterUnavailableError",
    "IndError",
    "IndRequestError",
    "IndSection",
    "IndSectionDrafter",
    "IndService",
    "ReferenceInfo",
    "Section",
    "SectionOutline",
    "SectionRequest",
    "SectionStatus",
    "StructureResponse",
    "load_structure",
]
