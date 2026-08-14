from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

from app.services.records import RecordSource, SourceRecord


class GrantSource(str, Enum):
    """Which provider an opportunity was fetched from."""

    GRANTS_GOV = "grants_gov"
    SBIR = "sbir"


class GrantProgram(str, Enum):
    """SBIR/STTR set-aside program, where the provider states one."""

    SBIR = "SBIR"
    STTR = "STTR"
    BOTH = "BOTH"
    OTHER = "OTHER"

    @classmethod
    def _missing_(cls, value: object) -> GrantProgram | None:
        """Accept `sbir` as readily as `SBIR`; callers type these into a query string."""
        if isinstance(value, str):
            return cls.__members__.get(value.strip().upper())
        return None


class GrantStatus(str, Enum):
    """Whether the opportunity can be applied to today."""

    OPEN = "open"
    FORECASTED = "forecasted"
    CLOSED = "closed"


class GrantOpportunity(BaseModel):
    """
    A funding opportunity normalized across grants.gov and SBIR.gov.

    `topic_description` is the text the semantic matcher reads; on grants.gov it is the
    synopsis (only present once the opportunity has been enriched via `fetchOpportunity`),
    on SBIR.gov it is the concatenated topic descriptions of the solicitation.
    """

    source: GrantSource
    opportunity_id: str
    number: str = ""
    title: str
    agency: str = ""
    agency_code: str = ""
    branch: str = ""
    program: GrantProgram | None = None
    status: GrantStatus | None = None
    posted_date: date | None = None
    close_date: date | None = None
    funding_ceiling: int | None = None
    funding_floor: int | None = None
    topic_description: str = ""
    topics: list[str] = Field(default_factory=list)
    url: str = ""

    @property
    def deadline_label(self) -> str:
        return self.close_date.isoformat() if self.close_date else "Rolling / TBD"

    @property
    def funding_label(self) -> str:
        if self.funding_ceiling is None:
            return ""
        return f"${self.funding_ceiling:,}"

    def days_until_close(self, today: date) -> int | None:
        """Negative once the deadline has passed; `None` when no deadline is published."""
        return None if self.close_date is None else (self.close_date - today).days

    def match_text(self) -> str:
        """Everything the matcher is allowed to read, in the order it should be read."""
        parts = [self.title, self.agency, *self.topics, self.topic_description]
        return "\n".join(part for part in parts if part)

    def to_source_record(self) -> SourceRecord:
        """Project into the review row shared with the literature and chemistry services."""
        return SourceRecord(
            source=RecordSource.GRANTS,
            record_id=f"{self.source.value}:{self.opportunity_id}",
            title=self.title,
            subtitle=" · ".join(
                part for part in (self.agency, self.number, self.deadline_label) if part
            ),
            url=self.url,
            fields={
                "Agency": self.agency,
                "Program": self.program.value if self.program else "",
                "Number": self.number,
                "Status": self.status.value if self.status else "",
                "Deadline": self.deadline_label,
                "Funding ceiling": self.funding_label,
                "Posted": self.posted_date.isoformat() if self.posted_date else "",
            },
        )


class GrantSearch(BaseModel):
    """
    The filter set, one field per supported facet.

    `agency` is a human-facing name resolved per provider (see `agencies.resolve_agency`);
    `keyword` is a free-text topic search; the date bounds and `program` are applied locally
    because neither provider filters on them.
    """

    keyword: str = ""
    agency: str = ""
    program: GrantProgram | None = None
    open_only: bool = True
    closing_after: date | None = None
    closing_before: date | None = None
    sources: list[GrantSource] = Field(
        default_factory=lambda: [GrantSource.GRANTS_GOV, GrantSource.SBIR]
    )

    def is_empty(self) -> bool:
        return not any(
            (
                self.keyword.strip(),
                self.agency.strip(),
                self.program,
                self.closing_after,
                self.closing_before,
            )
        )


class SourceStatus(BaseModel):
    """
    Per-provider outcome for one search.

    A search spans two independent providers, so one being down must degrade the result set
    rather than fail the request; the caller needs to know which half it is looking at.
    """

    source: GrantSource
    ok: bool = True
    total_count: int = 0
    returned: int = 0
    error: str = ""


class GrantPage(BaseModel):
    """
    One page of opportunities merged across the enabled providers.

    `total_count` is the sum of the providers' own hit counts and is therefore an upper bound:
    it is measured before the local program/date filters run.
    """

    search: GrantSearch
    opportunities: list[GrantOpportunity] = Field(default_factory=list)
    total_count: int = 0
    page: int = 0
    page_size: int = 0
    sources: list[SourceStatus] = Field(default_factory=list)

    @property
    def has_more(self) -> bool:
        return (self.page + 1) * self.page_size < self.total_count


class OpportunityMatch(BaseModel):
    """One ranked opportunity: 0-1 relevance plus the reasoning behind it."""

    opportunity: GrantOpportunity
    score: float
    rationale: str = ""
    matched_terms: list[str] = Field(default_factory=list)


class MatchResult(BaseModel):
    """Ranked opportunities for a company research focus."""

    focus: str
    matcher: str
    candidates_considered: int
    matches: list[OpportunityMatch] = Field(default_factory=list)
    sources: list[SourceStatus] = Field(default_factory=list)
