from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .. import REVIEW_NOTICE

# Bounds keep one request from becoming an unbounded prompt.
MAX_RECORDS_PER_KIND = 120
MAX_SECTIONS_REQUESTED = 12


class EvidenceKind(str, Enum):
    """
    The kinds of submitted data a section can be drafted from.

    This is the service's own vocabulary for the caller's data, not a regulatory list of what
    a section must contain. `reference/ctd_structure.json` maps each section to the kinds it
    is drafted from, and that mapping is what produces gaps when a kind is absent.
    """

    SUBSTANCE_IDENTITY = "substance_identity"
    MANUFACTURING_SITE = "manufacturing_site"
    MANUFACTURING_STEP = "manufacturing_step"
    MATERIAL_CONTROL = "material_control"
    SPECIFICATION = "specification"
    ANALYTICAL_METHOD = "analytical_method"
    ASSAY_RESULT = "assay_result"
    BATCH = "batch"
    IMPURITY = "impurity"
    STABILITY_RESULT = "stability_result"
    REFERENCE_STANDARD = "reference_standard"
    CONTAINER_CLOSURE = "container_closure"
    FORMULATION = "formulation"
    NONCLINICAL_STUDY = "nonclinical_study"


class EvidenceRecord(BaseModel):
    """
    One item of submitted data, tagged with what kind of thing it is.

    Deliberately a flat label/value/detail shape rather than a schema per kind: the caller's
    data comes out of their own systems, and a rigid per-kind schema would push them into
    inventing values for fields they do not have. `value` is kept as the string they sent —
    this service never reformats a reported number.
    """

    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind
    label: str = Field(min_length=1, max_length=200)
    value: str = Field(default="", max_length=400)
    unit: str = Field(default="", max_length=40)
    batch_id: str = Field(default="", max_length=80)
    method: str = Field(default="", max_length=200)
    acceptance_criterion: str = Field(default="", max_length=200)
    study_id: str = Field(default="", max_length=80)
    section_id: str = Field(default="", max_length=20)
    detail: str = Field(default="", max_length=1200)

    def render(self) -> str:
        parts = [self.label]
        if self.value:
            parts.append(f"value: {self.value} {self.unit}".strip())
        for name, field in (
            ("batch", self.batch_id),
            ("method", self.method),
            ("acceptance criterion", self.acceptance_criterion),
            ("study", self.study_id),
        ):
            if field:
                parts.append(f"{name}: {field}")
        if self.detail:
            parts.append(self.detail)
        return " | ".join(parts)


class IndDraftRequest(BaseModel):
    """What the caller submits: an identified programme, some evidence, and sections to draft."""

    model_config = ConfigDict(extra="forbid")

    program_name: str = Field(min_length=1, max_length=200)
    substance_name: str = Field(default="", max_length=200)
    dosage_form: str = Field(default="", max_length=200)
    section_ids: list[str] = Field(min_length=1, max_length=MAX_SECTIONS_REQUESTED)
    evidence: list[EvidenceRecord] = Field(default_factory=list, max_length=MAX_RECORDS_PER_KIND)


class SectionStatus(str, Enum):
    """
    How far a section got.

    `NOT_DRAFTED` exists so a section the caller asked for but submitted nothing for comes
    back visible and empty. Filling it with plausible prose is the failure mode this whole
    service is built to avoid.
    """

    DRAFTED = "drafted"
    DRAFTED_WITH_GAPS = "drafted_with_gaps"
    NOT_DRAFTED = "not_drafted"


class GapKind(str, Enum):
    NO_EVIDENCE_SUBMITTED = "no_evidence_submitted"
    MISSING_EVIDENCE_KIND = "missing_evidence_kind"
    AUTHOR_MUST_SUPPLY = "author_must_supply"
    DRAFTER_REPORTED = "drafter_reported"


class Gap(BaseModel):
    """Something the draft does not contain, stated rather than papered over."""

    model_config = ConfigDict(extra="forbid")

    kind: GapKind
    description: str
    evidence_kind: EvidenceKind | None = None


class IndSection(BaseModel):
    """
    One drafted CTD section.

    The review markers are on the section itself, not only on the response envelope, because
    a section is what gets copied out of the UI into someone's document.
    """

    model_config = ConfigDict(extra="forbid")

    section_id: str
    title: str
    module: str
    status: SectionStatus
    text: str = ""
    gaps: list[Gap] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    requires_expert_completion: bool = True
    requires_expert_review: bool = True
    review_notice: str = REVIEW_NOTICE
    source_reference: str = ""


class ReferenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    url: str
    document_date: str
    covers: str = ""


class ReferenceInfo(BaseModel):
    """Which dated transcription of the CTD tree produced this draft."""

    model_config = ConfigDict(extra="forbid")

    version: str
    retrieved: str
    sources: list[ReferenceSource]
    notes: list[str] = Field(default_factory=list)


class IndDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_name: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sections: list[IndSection] = Field(default_factory=list)
    unknown_section_ids: list[str] = Field(default_factory=list)
    unused_evidence: list[str] = Field(default_factory=list)
    reference: ReferenceInfo
    requires_expert_review: bool = True
    review_notice: str = REVIEW_NOTICE


class SectionOutline(BaseModel):
    """A node of the CTD tree as the frontend needs it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    module: str
    title: str
    requires: list[EvidenceKind] = Field(default_factory=list)
    draftable: bool


class StructureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference: ReferenceInfo
    sections: list[SectionOutline]
    requires_expert_review: bool = True
    review_notice: str = REVIEW_NOTICE
