"""Preclinical study narrative drafting with a deterministic numeric audit of the result."""

from .audit import AUDITOR_VERSION, audit_narrative, collect_source_values, extract_numbers
from .drafter import ClaudeNarrativeDrafter, DraftedSection, NarrativeDrafter
from .errors import (
    DrafterError,
    DrafterUnavailableError,
    PreclinicalError,
    PreclinicalRequestError,
)
from .models import (
    SECTION_HEADINGS,
    AuditSummary,
    Discrepancy,
    DiscrepancyKind,
    DoseGroup,
    DraftStatus,
    Finding,
    GlpStatus,
    Incidence,
    Measurement,
    NarrativeSection,
    PreclinicalReport,
    Quantity,
    SectionKey,
    Severity,
    Sex,
    StudyTable,
)
from .service import PreclinicalService

__all__ = [
    "AUDITOR_VERSION",
    "SECTION_HEADINGS",
    "AuditSummary",
    "ClaudeNarrativeDrafter",
    "Discrepancy",
    "DiscrepancyKind",
    "DoseGroup",
    "DraftStatus",
    "DrafterError",
    "DrafterUnavailableError",
    "DraftedSection",
    "Finding",
    "GlpStatus",
    "Incidence",
    "Measurement",
    "NarrativeDrafter",
    "NarrativeSection",
    "PreclinicalError",
    "PreclinicalReport",
    "PreclinicalRequestError",
    "PreclinicalService",
    "Quantity",
    "SectionKey",
    "Severity",
    "Sex",
    "StudyTable",
    "audit_narrative",
    "collect_source_values",
    "extract_numbers",
]
