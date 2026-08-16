from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, computed_field

from app.services.grants.models import GrantProgram


class OrganizationType(str, Enum):
    """What kind of entity is applying. Only a for-profit concern can hold an SBIR/STTR award."""

    FOR_PROFIT = "for_profit"
    NONPROFIT = "nonprofit"
    ACADEMIC = "academic"
    GOVERNMENT = "government"
    INDIVIDUAL = "individual"


class AwardPhase(str, Enum):
    PHASE_I = "phase_i"
    PHASE_II = "phase_ii"
    DIRECT_PHASE_II = "direct_phase_ii"


class PrincipalInvestigatorEmployer(str, Enum):
    """Where the proposed PI spends the majority of their time during the award."""

    COMPANY = "company"
    RESEARCH_INSTITUTION = "research_institution"
    OTHER = "other"


class Ownership(BaseModel):
    """
    Who owns the concern, by percentage.

    Every field is optional because a checker that guesses at ownership is worse than one that
    says it does not know: an unset percentage produces `needs_review`, never a pass.
    """

    us_individuals_percent: float | None = Field(default=None, ge=0, le=100)
    other_small_businesses_percent: float | None = Field(default=None, ge=0, le=100)
    investment_companies_percent: float | None = Field(default=None, ge=0, le=100)
    foreign_percent: float | None = Field(default=None, ge=0, le=100)


class CompanyProfile(BaseModel):
    """
    The structured facts the rules are evaluated against.

    Unknowns are represented as `None` rather than defaulted, so the difference between "no
    employees recorded" and "zero employees" survives into the verdict.
    """

    name: str = Field(default="", max_length=200)
    organization_type: OrganizationType | None = None
    principal_place_of_business_us: bool | None = None
    employee_count: int | None = Field(default=None, ge=0)
    ownership: Ownership = Field(default_factory=Ownership)

    pi_primary_employer: PrincipalInvestigatorEmployer | None = None
    pi_company_time_percent: float | None = Field(default=None, ge=0, le=100)

    has_research_institution_partner: bool | None = None
    work_by_company_percent: float | None = Field(default=None, ge=0, le=100)
    work_by_research_institution_percent: float | None = Field(default=None, ge=0, le=100)

    phase: AwardPhase | None = None
    prior_phase_i_award_same_topic: bool | None = None
    phase_i_awards_last_five_years: int | None = Field(default=None, ge=0)
    phase_ii_awards_last_five_years: int | None = Field(default=None, ge=0)

    sam_registered: bool | None = None
    sba_company_registry_registered: bool | None = None

    research_focus: str = Field(default="", max_length=2000)


class Verdict(str, Enum):
    """
    Per-rule outcome.

    `NEEDS_REVIEW` is not a soft fail: it means the rule cannot be decided from the profile —
    a missing fact, or a threshold that is agency-specific rather than statutory.
    """

    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"


class RuleOutcome(BaseModel):
    """One rule's verdict, with the plain-language reason and the authority behind it."""

    rule_id: str
    title: str
    verdict: Verdict
    explanation: str
    citation: str = ""
    missing_fields: list[str] = Field(default_factory=list)


class EligibilityReport(BaseModel):
    """
    Every applicable rule's outcome for one profile.

    The overall verdict is the worst outcome present: any `FAIL` fails the report, otherwise any
    `NEEDS_REVIEW` holds it open. This is an aid to a human reviewer, not a legal determination.
    """

    program: GrantProgram
    phase: AwardPhase | None = None
    config_version: str = ""
    outcomes: list[RuleOutcome] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verdict(self) -> Verdict:
        verdicts = {outcome.verdict for outcome in self.outcomes}
        if Verdict.FAIL in verdicts:
            return Verdict.FAIL
        if Verdict.NEEDS_REVIEW in verdicts:
            return Verdict.NEEDS_REVIEW
        return Verdict.PASS

    def by_verdict(self, verdict: Verdict) -> list[RuleOutcome]:
        return [outcome for outcome in self.outcomes if outcome.verdict is verdict]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> str:
        failed = self.by_verdict(Verdict.FAIL)
        review = self.by_verdict(Verdict.NEEDS_REVIEW)
        if failed:
            return (
                f"Not eligible for {self.program.value} as described: "
                + "; ".join(outcome.title.lower() for outcome in failed)
                + "."
            )
        if review:
            return (
                f"No {self.program.value} rule is failed, but "
                f"{len(review)} need review before relying on this: "
                + "; ".join(outcome.title.lower() for outcome in review)
                + "."
            )
        return (
            f"Every encoded {self.program.value} rule passes on the facts given. "
            "Confirm against the solicitation before submitting."
        )
