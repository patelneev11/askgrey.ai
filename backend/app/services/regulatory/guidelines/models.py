from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

from .text import PhraseMatch

# Repeated verbatim in every report and in the reference listing. The frontend may render it, but
# it travels with the data so a report that is exported, pasted or logged still carries it.
REVIEW_NOTICE = (
    "Unvalidated drafting aid. This report is produced by literal keyword-signal matching, not by "
    "a regulatory assessment, and must be reviewed by a qualified regulatory affairs professional "
    "before it is relied on for any submission decision."
)

LIMITATIONS = (
    "The reference data is a dated snapshot of the documents listed in docs/regulatory-sources.md; "
    "nothing in this product watches those documents for change, so the expectations checked here "
    "can be older than the current guidance (see the version and retrieved date per jurisdiction). "
    "Coverage is limited to the requirements encoded in that snapshot and is neither complete nor "
    "authoritative: 'addressed' means a phrase the engine looks for is present, not that the "
    "section satisfies the requirement, and 'missing' can mean the section says the right thing in "
    "words the engine does not know."
)


class Jurisdiction(str, Enum):
    FDA = "fda"
    EMA = "ema"
    PMDA = "pmda"


class RequirementStatus(str, Enum):
    """
    Per-requirement outcome.

    `INDETERMINATE` is not a soft `MISSING`: it means the engine declines to judge — the section is
    too short to carry the content, or a negative signal (placeholder text such as "to be
    determined") makes any positive match untrustworthy. A false `ADDRESSED` is the dangerous
    direction, so anything doubtful lands here.
    """

    ADDRESSED = "addressed"
    MISSING = "missing"
    INDETERMINATE = "indeterminate"


class Citation(BaseModel):
    """The document a requirement was transcribed from. Every field is mandatory by design."""

    document: str = Field(min_length=1, max_length=300)
    url: str = Field(min_length=1, max_length=500)
    # As printed on the document ("Step 4, 20 December 2002"), which is often not an ISO date.
    document_date: str = Field(min_length=1, max_length=100)


class SignalEvidence(BaseModel):
    """Which signal group fired and where each of its phrases was found."""

    group_index: int
    phrases: list[PhraseMatch] = Field(default_factory=list)


class RequirementFinding(BaseModel):
    """One requirement evaluated against one section, with the evidence behind the status."""

    requirement_id: str
    title: str
    ctd_sections: list[str] = Field(default_factory=list)
    matched_scope: str = ""
    citation: Citation
    expectation: str
    status: RequirementStatus
    explanation: str
    matched_signal: SignalEvidence | None = None
    suppressed_by: PhraseMatch | None = None


class JurisdictionFindings(BaseModel):
    """Findings for one jurisdiction, stamped with the vintage of the data that produced them."""

    jurisdiction: Jurisdiction
    version: str
    retrieved: date
    findings: list[RequirementFinding] = Field(default_factory=list)
    out_of_scope_requirement_ids: list[str] = Field(default_factory=list)

    def with_status(self, status: RequirementStatus) -> list[RequirementFinding]:
        return [finding for finding in self.findings if finding.status is status]


class GuidelineCheckReport(BaseModel):
    """
    The whole comparison for one draft section.

    `requires_expert_review` is always true and `limitations` is always populated: this object is
    the only place a consumer is guaranteed to look, so the caveat lives in the data rather than
    only in the UI.
    """

    section_id: str
    word_count: int
    min_words_to_judge: int
    jurisdictions: list[JurisdictionFindings] = Field(default_factory=list)
    requires_expert_review: bool = True
    review_notice: str = REVIEW_NOTICE
    limitations: str = LIMITATIONS

    def counts(self) -> dict[RequirementStatus, int]:
        tally = dict.fromkeys(RequirementStatus, 0)
        for jurisdiction in self.jurisdictions:
            for finding in jurisdiction.findings:
                tally[finding.status] += 1
        return tally


class ReferenceRequirement(BaseModel):
    """A requirement as advertised to a client: what is checked, and on whose authority."""

    id: str
    title: str
    ctd_sections: list[str] = Field(default_factory=list)
    citation: Citation
    expectation: str


class ReferenceJurisdiction(BaseModel):
    jurisdiction: Jurisdiction
    version: str
    retrieved: date
    notes: str = ""
    requirements: list[ReferenceRequirement] = Field(default_factory=list)


class ReferenceLibrary(BaseModel):
    """Vintage plus contents of the shipped datasets, so a UI can show what it is comparing to."""

    jurisdictions: list[ReferenceJurisdiction] = Field(default_factory=list)
    requires_expert_review: bool = True
    review_notice: str = REVIEW_NOTICE
    limitations: str = LIMITATIONS
