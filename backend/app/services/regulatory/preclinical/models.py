from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .. import REVIEW_NOTICE

# Bounds exist so one request cannot turn into an unbounded prompt or an unbounded audit.
MAX_GROUPS = 40
MAX_FINDINGS = 200
MAX_MEASUREMENTS = 60
MAX_ALIASES = 6


class Sex(str, Enum):
    MALE = "male"
    FEMALE = "female"
    BOTH = "both"
    NOT_REPORTED = "not_reported"


class GlpStatus(str, Enum):
    """Whether the study was run under GLP. Required as a statement in the EU (Annex I ¶44)."""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    NOT_REPORTED = "not_reported"


class Quantity(BaseModel):
    """
    One number from the source table, with the unit it was reported in.

    `Decimal` rather than `float`: the auditor compares the narrative's digits against these
    digits, so `12.40` must not silently become `12.4` and `0.1` must not become
    `0.1000000000000000055`. Pydantic serialises it as a JSON string, which is also what the
    UI should display — reformatting a reported value is how false precision gets introduced.
    """

    model_config = ConfigDict(extra="forbid")

    value: Decimal
    unit: str = Field(default="", max_length=40)

    def render(self) -> str:
        return f"{self.value} {self.unit}".strip()


class Incidence(BaseModel):
    """An affected/examined count, e.g. 4/10 animals."""

    model_config = ConfigDict(extra="forbid")

    affected: int = Field(ge=0, le=100_000)
    examined: int = Field(ge=1, le=100_000)

    def render(self) -> str:
        return f"{self.affected}/{self.examined}"


class DoseGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=120)
    dose: Quantity | None = None
    sex: Sex = Sex.NOT_REPORTED
    animals_per_sex: int | None = Field(default=None, ge=0, le=10_000)
    notes: str = Field(default="", max_length=600)


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_label: str = Field(default="", max_length=120)
    endpoint: str = Field(min_length=1, max_length=200)
    quantity: Quantity | None = None
    incidence: Incidence | None = None
    severity: str = Field(default="", max_length=80)
    notes: str = Field(default="", max_length=600)


class Measurement(BaseModel):
    """
    A named study-level value the narrative is expected to state, e.g. NOAEL.

    `aliases` are supplied by the caller rather than hardcoded: the auditor uses them to find
    the claim in the narrative, and a built-in alias list would be this service asserting
    regulatory vocabulary it cannot cite. `text_value` covers values that are not numbers
    ("not established") — a narrative that puts a number on one of those is contradicting the
    source, which the auditor flags.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    aliases: list[str] = Field(default_factory=list, max_length=MAX_ALIASES)
    quantity: Quantity | None = None
    text_value: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=600)

    def render(self) -> str:
        return self.quantity.render() if self.quantity else self.text_value


class StudyTable(BaseModel):
    """The structured study record. This, and only this, is the truth the auditor checks against."""

    model_config = ConfigDict(extra="forbid")

    study_id: str = Field(min_length=1, max_length=80)
    title: str = Field(default="", max_length=300)
    test_article: str = Field(default="", max_length=200)
    species: str = Field(default="", max_length=120)
    strain: str = Field(default="", max_length=120)
    route: str = Field(default="", max_length=120)
    duration: str = Field(default="", max_length=120)
    glp_status: GlpStatus = GlpStatus.NOT_REPORTED
    groups: list[DoseGroup] = Field(default_factory=list, max_length=MAX_GROUPS)
    findings: list[Finding] = Field(default_factory=list, max_length=MAX_FINDINGS)
    measurements: list[Measurement] = Field(default_factory=list, max_length=MAX_MEASUREMENTS)


class SectionKey(str, Enum):
    """
    The parts of a preclinical study narrative the drafter writes.

    This is the conventional shape of a study report narrative (design, results,
    interpretation), *not* a regulatory heading set: ICH M4S(R2) organises study reports into
    module 4 and summarises them in 2.6, but neither prescribes the internal headings of a
    single study narrative. Section numbering for a submission is the IND compiler's job.
    """

    STUDY_DESIGN = "study_design"
    RESULTS = "results"
    INTERPRETATION = "interpretation"


SECTION_HEADINGS: dict[SectionKey, str] = {
    SectionKey.STUDY_DESIGN: "Study design and methods",
    SectionKey.RESULTS: "Results",
    SectionKey.INTERPRETATION: "Interpretation and conclusions",
}


class DraftStatus(str, Enum):
    FIRST_DRAFT = "first_draft"


class NarrativeSection(BaseModel):
    """
    One drafted section.

    The review markers live on the section itself, not only on the enclosing report, because
    a section is the unit that gets copied out of the UI into somebody's document.
    """

    key: SectionKey
    heading: str
    text: str
    draft_status: DraftStatus = DraftStatus.FIRST_DRAFT
    requires_expert_review: bool = True
    review_notice: str = REVIEW_NOTICE
    gaps: list[str] = Field(default_factory=list)


class DiscrepancyKind(str, Enum):
    CONTRADICTED_VALUE = "contradicted_value"
    UNSUPPORTED_NUMBER = "unsupported_number"
    UNIT_MISMATCH = "unit_mismatch"
    ROUNDED_VALUE = "rounded_value"


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class Discrepancy(BaseModel):
    """
    One numeric claim in the narrative that the source table does not support.

    `context` is the surrounding narrative text and `start_char`/`end_char` locate the number
    inside `section` text, so a reviewer can see the claim rather than take the flag on trust.
    """

    kind: DiscrepancyKind
    severity: Severity
    section: SectionKey
    narrative_value: str
    source_value: str = ""
    source_label: str = ""
    context: str = ""
    start_char: int = 0
    end_char: int = 0
    explanation: str = ""


class AuditSummary(BaseModel):
    """How the numbers were checked, so the check itself is inspectable."""

    auditor_version: str
    method: str = (
        "Every number in the drafted narrative is compared against the numbers in the "
        "submitted study table by exact decimal matching. No language model is involved in "
        "this check."
    )
    numbers_checked: int = 0
    numbers_matched: int = 0
    numbers_flagged: int = 0
    source_values: int = 0


class PreclinicalReport(BaseModel):
    study_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sections: list[NarrativeSection] = Field(default_factory=list)
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    audit: AuditSummary
    requires_expert_review: bool = True
    review_notice: str = REVIEW_NOTICE
