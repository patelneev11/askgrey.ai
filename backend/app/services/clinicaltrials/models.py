from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.services.records import RecordSource, SourceRecord

STUDY_URL = "https://clinicaltrials.gov/study"


class TrialPhase(str, Enum):
    """The phase vocabulary the v2 API accepts; a trial may report more than one (e.g. 1/2)."""

    NA = "NA"
    EARLY_PHASE1 = "EARLY_PHASE1"
    PHASE1 = "PHASE1"
    PHASE2 = "PHASE2"
    PHASE3 = "PHASE3"
    PHASE4 = "PHASE4"


class TrialStatus(str, Enum):
    """Recruitment status, as `filter.overallStatus` spells it."""

    NOT_YET_RECRUITING = "NOT_YET_RECRUITING"
    RECRUITING = "RECRUITING"
    ENROLLING_BY_INVITATION = "ENROLLING_BY_INVITATION"
    ACTIVE_NOT_RECRUITING = "ACTIVE_NOT_RECRUITING"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    WITHHELD = "WITHHELD"
    UNKNOWN = "UNKNOWN"


class Intervention(BaseModel):
    """One arm's intervention: `DRUG`, `BIOLOGICAL`, `DEVICE`, `BEHAVIORAL`, ..."""

    name: str
    type: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.name} ({self.type.title()})" if self.type else self.name


class TrialSearch(BaseModel):
    """
    The filter set, one field per supported facet.

    Text facets are the API's own search areas (a phrase, not an exact match); `phases` and
    `statuses` are enum filters and are AND-ed with the text facets.
    """

    sponsor: str = ""
    condition: str = ""
    intervention: str = ""
    term: str = ""
    phases: list[TrialPhase] = Field(default_factory=list)
    statuses: list[TrialStatus] = Field(default_factory=list)

    def is_empty(self) -> bool:
        return not any(
            (self.sponsor, self.condition, self.intervention, self.term, self.phases, self.statuses)
        )


class TrialRecord(BaseModel):
    """A ClinicalTrials.gov study normalized to the fields the rest of the product consumes."""

    nct_id: str
    title: str = ""
    official_title: str = ""
    status: TrialStatus | None = None
    phases: list[TrialPhase] = Field(default_factory=list)
    study_type: str = ""
    sponsor: str = ""
    collaborators: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    interventions: list[Intervention] = Field(default_factory=list)
    enrollment: int | None = None
    enrollment_type: str = ""
    start_date: str = ""
    primary_completion_date: str = ""
    completion_date: str = ""
    url: str = ""

    @property
    def phase_label(self) -> str:
        """`PHASE2`,`PHASE3` reads as `Phase 2/3`; a trial with no phase is `N/A`."""
        numbers = [
            phase.value.removeprefix("EARLY_").removeprefix("PHASE")
            for phase in self.phases
            if phase is not TrialPhase.NA
        ]
        if not numbers:
            return "N/A"
        prefix = "Early Phase " if TrialPhase.EARLY_PHASE1 in self.phases else "Phase "
        return prefix + "/".join(numbers)

    @property
    def status_label(self) -> str:
        return self.status.value.replace("_", " ").title() if self.status else ""

    def to_source_record(self) -> SourceRecord:
        """Project into the review row shared with the literature and chemistry services."""
        dates = " – ".join(part for part in (self.start_date, self.completion_date) if part)
        return SourceRecord(
            source=RecordSource.CLINICALTRIALS,
            record_id=self.nct_id,
            title=self.title,
            subtitle=" · ".join(part for part in (self.phase_label, self.status_label) if part),
            url=self.url or f"{STUDY_URL}/{self.nct_id}",
            fields={
                "Status": self.status_label,
                "Phase": self.phase_label,
                "Sponsor": self.sponsor,
                "Condition": ", ".join(self.conditions),
                "Intervention": ", ".join(item.name for item in self.interventions),
                "Enrollment": "" if self.enrollment is None else str(self.enrollment),
                "Dates": dates,
            },
        )


class TrialPage(BaseModel):
    """
    One page of results plus the cursor for the next one.

    ClinicalTrials.gov paginates with an opaque `nextPageToken` rather than offsets, so the
    caller carries `next_page_token` back into the following request. `total_count` is the size
    of the whole result set, not of this page — but v2 reports it only on the first page of a
    walk, so on a later page it falls back to the records in hand and `total_count_known` is
    false. A caller that states a total has to check that flag first.
    """

    search: TrialSearch
    trials: list[TrialRecord] = Field(default_factory=list)
    total_count: int = 0
    total_count_known: bool = True
    page_size: int = 0
    next_page_token: str | None = None

    @property
    def has_more(self) -> bool:
        return bool(self.next_page_token)
