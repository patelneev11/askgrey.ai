from __future__ import annotations

from collections.abc import Callable

from app.services.grants.models import GrantProgram

from .config import RuleSpec
from .models import (
    AwardPhase,
    CompanyProfile,
    OrganizationType,
    PrincipalInvestigatorEmployer,
    RuleOutcome,
    Verdict,
)

Evaluation = tuple[Verdict, str, list[str]]
Evaluator = Callable[[CompanyProfile, RuleSpec, GrantProgram], Evaluation]


def _unknown(explanation: str, *fields: str) -> Evaluation:
    return Verdict.NEEDS_REVIEW, explanation, list(fields)


def organization_type(profile: CompanyProfile, rule: RuleSpec, program: GrantProgram) -> Evaluation:
    if profile.organization_type is None:
        return _unknown(
            "The entity type is not recorded. Only a for-profit business concern can hold an "
            "award, so this has to be confirmed.",
            "organization_type",
        )
    if profile.organization_type is OrganizationType.FOR_PROFIT:
        return Verdict.PASS, "The applicant is a for-profit business concern.", []
    return (
        Verdict.FAIL,
        f"The applicant is recorded as {profile.organization_type.value.replace('_', ' ')}. "
        "Only a for-profit business concern can receive the award; a nonprofit or university "
        "can participate as a subcontractor or research-institution partner instead.",
        [],
    )


def place_of_business(profile: CompanyProfile, rule: RuleSpec, program: GrantProgram) -> Evaluation:
    if profile.principal_place_of_business_us is None:
        return _unknown(
            "It is not recorded whether the principal place of business is in the United States.",
            "principal_place_of_business_us",
        )
    if profile.principal_place_of_business_us:
        return Verdict.PASS, "The principal place of business is in the United States.", []
    return (
        Verdict.FAIL,
        "The principal place of business is outside the United States. The award requires a "
        "concern located in, and performing the work in, the US.",
        [],
    )


def size_standard(profile: CompanyProfile, rule: RuleSpec, program: GrantProgram) -> Evaluation:
    limit = rule.number("max_employees")
    if profile.employee_count is None:
        return _unknown(
            f"Headcount is not recorded. The concern must have no more than {limit:g} employees, "
            "counting affiliates and all locations.",
            "employee_count",
        )
    if profile.employee_count <= limit:
        return (
            Verdict.PASS,
            f"{profile.employee_count} employees is within the {limit:g}-employee size standard, "
            "provided that count already includes every affiliate.",
            [],
        )
    return (
        Verdict.FAIL,
        f"{profile.employee_count} employees exceeds the {limit:g}-employee size standard, which "
        "counts affiliates and all locations.",
        [],
    )


def us_ownership(profile: CompanyProfile, rule: RuleSpec, program: GrantProgram) -> Evaluation:
    minimum = rule.number("min_ownership_percent")
    ownership = profile.ownership
    individuals = ownership.us_individuals_percent
    businesses = ownership.other_small_businesses_percent

    if individuals is None and businesses is None:
        return _unknown(
            f"Ownership percentages are not recorded. At least {minimum:g}% must be held by US "
            "citizens or permanent residents, or by other US small businesses.",
            "ownership.us_individuals_percent",
            "ownership.other_small_businesses_percent",
        )

    us_held = (individuals or 0) + (businesses or 0)
    if us_held >= minimum:
        return (
            Verdict.PASS,
            f"{us_held:g}% is held by US citizens, permanent residents or other US small "
            f"businesses, meeting the {minimum:g}% requirement.",
            [],
        )

    foreign = ownership.foreign_percent
    if foreign is not None and foreign > 100 - minimum:
        return (
            Verdict.FAIL,
            f"{foreign:g}% foreign ownership leaves less than the required {minimum:g}% in US "
            "hands.",
            [],
        )
    return (
        Verdict.FAIL,
        f"Only {us_held:g}% is recorded as US-held, below the {minimum:g}% required for US "
        "ownership and control.",
        [],
    )


def investment_company_ownership(
    profile: CompanyProfile, rule: RuleSpec, program: GrantProgram
) -> Evaluation:
    majority = rule.number("majority_percent")
    held = profile.ownership.investment_companies_percent
    if held is None:
        return _unknown(
            "Ownership by venture capital, hedge or private equity firms is not recorded. "
            "Majority ownership by such firms is allowed only at agencies that have elected to "
            "use that authority, and never for STTR.",
            "ownership.investment_companies_percent",
        )
    if held <= majority:
        return (
            Verdict.PASS,
            f"{held:g}% held by investment companies stays at or below the {majority:g}% "
            "threshold, so the majority-ownership provision does not apply.",
            [],
        )
    return (
        Verdict.NEEDS_REVIEW,
        f"{held:g}% is held by venture capital, hedge or private equity firms. That is permitted "
        "only for SBIR, and only at agencies that have elected to accept majority-VC-owned "
        "applicants — check the specific solicitation.",
        [],
    )


def pi_employment(profile: CompanyProfile, rule: RuleSpec, program: GrantProgram) -> Evaluation:
    minimum = rule.number("min_company_time_percent")
    employer = profile.pi_primary_employer
    share = profile.pi_company_time_percent

    if program is GrantProgram.STTR:
        if employer is None:
            return _unknown(
                "The PI's primary employer is not recorded. For STTR the PI may be primarily "
                "employed by either the small business or the research institution.",
                "pi_primary_employer",
            )
        if employer in (
            PrincipalInvestigatorEmployer.COMPANY,
            PrincipalInvestigatorEmployer.RESEARCH_INSTITUTION,
        ):
            return (
                Verdict.PASS,
                "The PI is primarily employed by the small business or the research institution, "
                "either of which STTR allows.",
                [],
            )
        return (
            Verdict.FAIL,
            "The PI is primarily employed by a third party. STTR requires the PI to be primarily "
            "employed by the small business or by the partnering research institution.",
            [],
        )

    if employer is None and share is None:
        return _unknown(
            f"The PI's employment is not recorded. For SBIR the PI must spend more than "
            f"{minimum:g}% of their time employed by the small business during the award.",
            "pi_primary_employer",
            "pi_company_time_percent",
        )
    if share is not None:
        if share > minimum:
            return (
                Verdict.PASS,
                f"The PI spends {share:g}% of their time employed by the company, above the "
                f"{minimum:g}% SBIR requires.",
                [],
            )
        return (
            Verdict.FAIL,
            f"The PI spends {share:g}% of their time with the company. SBIR requires more than "
            f"{minimum:g}%, so the PI would not be primarily employed by the applicant.",
            [],
        )
    if employer is not None and employer is not PrincipalInvestigatorEmployer.COMPANY:
        return (
            Verdict.FAIL,
            f"The PI is primarily employed by the {employer.value.replace('_', ' ')}. SBIR "
            "requires the PI to be primarily employed by the applicant small business for the "
            "duration of the award; STTR is the program that allows an institution-based PI.",
            [],
        )
    return (
        Verdict.NEEDS_REVIEW,
        "The PI is recorded as primarily employed by the company, but their time commitment is "
        f"not, and SBIR needs more than {minimum:g}% of their time to be with the applicant.",
        ["pi_company_time_percent"],
    )


def research_institution_partner(
    profile: CompanyProfile, rule: RuleSpec, program: GrantProgram
) -> Evaluation:
    if profile.has_research_institution_partner is None:
        return _unknown(
            "No research-institution partner is recorded. STTR requires a formal cooperative "
            "agreement with one.",
            "has_research_institution_partner",
        )
    if profile.has_research_institution_partner:
        return (
            Verdict.PASS,
            "A partnering research institution is in place, as STTR requires.",
            [],
        )
    return (
        Verdict.FAIL,
        "STTR requires a formal partnership with a research institution. Without one the work "
        "would have to be proposed under SBIR instead.",
        [],
    )


def work_split(profile: CompanyProfile, rule: RuleSpec, program: GrantProgram) -> Evaluation:
    company = profile.work_by_company_percent

    if program is GrantProgram.STTR:
        min_company = rule.number("sttr_min_company_percent")
        min_institution = rule.number("sttr_min_research_institution_percent")
        institution = profile.work_by_research_institution_percent
        if company is None or institution is None:
            return _unknown(
                f"The split of work is not recorded. STTR requires at least {min_company:g}% by "
                f"the small business and at least {min_institution:g}% by the research "
                "institution.",
                "work_by_company_percent",
                "work_by_research_institution_percent",
            )
        if company >= min_company and institution >= min_institution:
            return (
                Verdict.PASS,
                f"{company:g}% by the small business and {institution:g}% by the research "
                f"institution meet the {min_company:g}/{min_institution:g} STTR split.",
                [],
            )
        shortfalls = []
        if company < min_company:
            shortfalls.append(
                f"the small business performs {company:g}%, below the required {min_company:g}%"
            )
        if institution < min_institution:
            shortfalls.append(
                f"the research institution performs {institution:g}%, below the required "
                f"{min_institution:g}%"
            )
        return Verdict.FAIL, "STTR work split is not met: " + "; ".join(shortfalls) + ".", []

    if profile.phase is None:
        return _unknown(
            "The phase is not recorded, and the minimum share of work the applicant must perform "
            "differs between Phase I and Phase II.",
            "phase",
        )
    key = (
        "sbir_phase_i_min_company_percent"
        if profile.phase is AwardPhase.PHASE_I
        else "sbir_phase_ii_min_company_percent"
    )
    minimum = rule.number(key)
    label = "Phase I" if profile.phase is AwardPhase.PHASE_I else "Phase II"
    if company is None:
        return _unknown(
            f"The share of work performed by the applicant is not recorded. SBIR {label} requires "
            f"at least {minimum:g}%.",
            "work_by_company_percent",
        )
    if company >= minimum:
        return (
            Verdict.PASS,
            f"The applicant performs {company:g}% of the work, meeting the {minimum:g}% SBIR "
            f"{label} minimum.",
            [],
        )
    return (
        Verdict.FAIL,
        f"The applicant performs {company:g}% of the work, below the {minimum:g}% SBIR {label} "
        "requires it to perform itself.",
        [],
    )


def phase_progression(profile: CompanyProfile, rule: RuleSpec, program: GrantProgram) -> Evaluation:
    if profile.phase is None:
        return _unknown("The phase being applied for is not recorded.", "phase")
    if profile.phase is AwardPhase.PHASE_I:
        return Verdict.PASS, "Phase I has no prior-award prerequisite.", []
    if profile.phase is AwardPhase.DIRECT_PHASE_II:
        return (
            Verdict.NEEDS_REVIEW,
            "Direct-to-Phase-II skips the Phase I prerequisite, but only some agencies offer it "
            "and each sets its own evidence requirements. Confirm against the solicitation.",
            [],
        )
    if profile.prior_phase_i_award_same_topic is None:
        return _unknown(
            "Phase II normally requires a prior Phase I award on the same topic, and no prior "
            "award is recorded.",
            "prior_phase_i_award_same_topic",
        )
    if profile.prior_phase_i_award_same_topic:
        return (
            Verdict.PASS,
            "A prior Phase I award on the same topic supports the Phase II application.",
            [],
        )
    return (
        Verdict.FAIL,
        "Phase II requires a prior Phase I award on the same topic, and none is recorded. A "
        "Direct-to-Phase-II solicitation would be the alternative route.",
        [],
    )


def performance_benchmarks(
    profile: CompanyProfile, rule: RuleSpec, program: GrantProgram
) -> Evaluation:
    threshold = rule.number("phase_i_awards_triggering_review")
    awards = profile.phase_i_awards_last_five_years
    if awards is None:
        return _unknown(
            f"Prior award history is not recorded. Concerns with more than {threshold:g} Phase I "
            "awards in the last five years must meet SBA's transition-rate benchmarks.",
            "phase_i_awards_last_five_years",
        )
    if awards <= threshold:
        return (
            Verdict.PASS,
            f"{awards} Phase I awards in the last five years is at or below the {threshold:g} "
            "that triggers SBA's performance benchmarks.",
            [],
        )
    return (
        Verdict.NEEDS_REVIEW,
        f"{awards} Phase I awards in the last five years exceeds {threshold:g}, so SBA's "
        "Phase I-to-Phase II transition-rate benchmark applies. Eligibility depends on the "
        "company's measured transition rate, which this checker does not hold.",
        [],
    )


def registrations(profile: CompanyProfile, rule: RuleSpec, program: GrantProgram) -> Evaluation:
    missing = [
        name
        for name, value in (
            ("sam_registered", profile.sam_registered),
            ("sba_company_registry_registered", profile.sba_company_registry_registered),
        )
        if value is None
    ]
    if missing:
        return _unknown(
            "Registration status is not recorded. An application cannot be submitted without an "
            "active SAM registration and an SBA Company Registry ID.",
            *missing,
        )
    if profile.sam_registered and profile.sba_company_registry_registered:
        return Verdict.PASS, "SAM and SBA Company Registry registrations are both active.", []
    outstanding = []
    if not profile.sam_registered:
        outstanding.append("SAM")
    if not profile.sba_company_registry_registered:
        outstanding.append("the SBA Company Registry")
    return (
        Verdict.NEEDS_REVIEW,
        f"Not registered with {' and '.join(outstanding)}. This does not make the company "
        "ineligible, but the application cannot be submitted until it is done, and SAM in "
        "particular can take weeks.",
        [],
    )


def topic_fit(profile: CompanyProfile, rule: RuleSpec, program: GrantProgram) -> Evaluation:
    if not profile.research_focus.strip():
        return _unknown(
            "No research focus is recorded, so the fit to the solicitation's topic cannot be "
            "reviewed.",
            "research_focus",
        )
    return (
        Verdict.NEEDS_REVIEW,
        "Whether the proposed work falls inside the topic is a programme officer's judgement, "
        "not a threshold. This checker deliberately does not score it.",
        [],
    )


EVALUATORS: dict[str, Evaluator] = {
    "organization_type": organization_type,
    "place_of_business": place_of_business,
    "size_standard": size_standard,
    "us_ownership": us_ownership,
    "investment_company_ownership": investment_company_ownership,
    "pi_employment": pi_employment,
    "research_institution_partner": research_institution_partner,
    "work_split": work_split,
    "phase_progression": phase_progression,
    "performance_benchmarks": performance_benchmarks,
    "registrations": registrations,
    "topic_fit": topic_fit,
}


def evaluate_rule(
    rule: RuleSpec, profile: CompanyProfile, program: GrantProgram, evaluator: Evaluator
) -> RuleOutcome:
    verdict, explanation, missing = evaluator(profile, rule, program)
    return RuleOutcome(
        rule_id=rule.id,
        title=rule.title,
        verdict=verdict,
        explanation=explanation,
        citation=rule.citation,
        missing_fields=missing,
    )
