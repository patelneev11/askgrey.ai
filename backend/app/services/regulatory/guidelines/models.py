from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
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


# How the snapshot is expected to be maintained, in days since the `retrieved` date.
#
# The interval is a maintenance policy, not a regulatory one: no authority publishes on a schedule.
# 90 days is a quarterly review, short enough that a revision is unlikely to sit unnoticed for long
# (PMDA's points-to-consider document is revised roughly annually); past 180 days the snapshot is
# declared stale, because at that age nobody should be told it reflects current guidance.
SNAPSHOT_REVIEW_INTERVAL_DAYS = 90
SNAPSHOT_STALE_AFTER_DAYS = 180

# Where the manual refresh is written down. Pointed at from the payload so the person who sees the
# warning is told where to act, rather than only that something is old.
SNAPSHOT_UPDATE_PROCEDURE = (
    "Refresh manually: app/services/regulatory/guidelines/README.md, 'Refreshing the data' - read "
    "each document in docs/regulatory-sources.md against reference/<jurisdiction>.json, then bump "
    "that file's 'version' and 'retrieved'. Nothing is fetched at runtime by design."
)


class SnapshotStatus(str, Enum):
    """
    How much trust the snapshot's age earns.

    `REVIEW_DUE` does not mean the data is wrong and `CURRENT` does not mean it is complete or
    legally current: the status is a statement about when a human last read the source documents,
    which is the only thing the age of a file can support.
    """

    CURRENT = "current"
    REVIEW_DUE = "review_due"
    STALE = "stale"


class SnapshotFreshness(BaseModel):
    """The age of a shipped snapshot against the maintenance policy, computed, never asserted."""

    version: str
    retrieved: date
    age_days: int
    review_interval_days: int = SNAPSHOT_REVIEW_INTERVAL_DAYS
    stale_after_days: int = SNAPSHOT_STALE_AFTER_DAYS
    review_due_on: date
    stale_on: date
    status: SnapshotStatus
    message: str
    update_procedure: str = SNAPSHOT_UPDATE_PROCEDURE


def assess_freshness(version: str, retrieved: date, today: date) -> SnapshotFreshness:
    """
    Age one snapshot. Deterministic in `today`, so a caller can ask about any date.

    A negative age (a `retrieved` date in the future) is reported as 0 days and `REVIEW_DUE`: the
    file is inconsistent rather than fresh, and treating it as current would hide that.
    """
    age = (today - retrieved).days
    review_due_on = retrieved + timedelta(days=SNAPSHOT_REVIEW_INTERVAL_DAYS)
    stale_on = retrieved + timedelta(days=SNAPSHOT_STALE_AFTER_DAYS)
    if age < 0:
        return SnapshotFreshness(
            version=version,
            retrieved=retrieved,
            age_days=0,
            review_due_on=review_due_on,
            stale_on=stale_on,
            status=SnapshotStatus.REVIEW_DUE,
            message=(
                f"Snapshot {version} is dated {retrieved.isoformat()}, in the future. Treat the "
                "vintage as unknown and re-read the source documents."
            ),
        )
    if age >= SNAPSHOT_STALE_AFTER_DAYS:
        status = SnapshotStatus.STALE
        message = (
            f"Snapshot {version} was read from the source documents {age} days ago "
            f"({retrieved.isoformat()}), past the {SNAPSHOT_STALE_AFTER_DAYS}-day limit. Findings "
            "may reflect superseded guidance; check every requirement against the cited document "
            "before relying on this report."
        )
    elif age >= SNAPSHOT_REVIEW_INTERVAL_DAYS:
        status = SnapshotStatus.REVIEW_DUE
        message = (
            f"Snapshot {version} was read from the source documents {age} days ago "
            f"({retrieved.isoformat()}); a review was due on {review_due_on.isoformat()}. It has "
            "not been checked against the sources since."
        )
    else:
        status = SnapshotStatus.CURRENT
        message = (
            f"Snapshot {version} was read from the source documents {age} days ago "
            f"({retrieved.isoformat()}); the next review is due {review_due_on.isoformat()}. That "
            "is when a human last read the sources, not a statement that the data is complete or "
            "legally current."
        )
    return SnapshotFreshness(
        version=version,
        retrieved=retrieved,
        age_days=age,
        review_due_on=review_due_on,
        stale_on=stale_on,
        status=status,
        message=message,
    )


def oldest(snapshots: Sequence[SnapshotFreshness]) -> SnapshotFreshness | None:
    """The snapshot a UI should lead with: the one whose age is worst."""
    if not snapshots:
        return None
    return max(snapshots, key=lambda snapshot: snapshot.age_days)


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
    freshness: SnapshotFreshness
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
    # The worst-aged snapshot the report drew on, so one line can state how old the comparison is.
    snapshot: SnapshotFreshness | None = None
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
    freshness: SnapshotFreshness
    notes: str = ""
    requirements: list[ReferenceRequirement] = Field(default_factory=list)


class ReferenceLibrary(BaseModel):
    """Vintage plus contents of the shipped datasets, so a UI can show what it is comparing to."""

    jurisdictions: list[ReferenceJurisdiction] = Field(default_factory=list)
    snapshot: SnapshotFreshness | None = None
    requires_expert_review: bool = True
    review_notice: str = REVIEW_NOTICE
    limitations: str = LIMITATIONS
