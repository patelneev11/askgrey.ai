from __future__ import annotations

from typing import Any

import pytest

from app.services.grants.eligibility import (
    AwardPhase,
    CompanyProfile,
    EligibilityChecker,
    OrganizationType,
    Ownership,
    PrincipalInvestigatorEmployer,
    RuleOutcome,
    Verdict,
)
from app.services.grants.models import GrantProgram


def profile(**overrides: Any) -> CompanyProfile:
    """
    A profile that passes every rule it can, so each test changes exactly one fact.

    `topic_fit` always needs review, so no profile is ever wholly clean; the tests assert on
    individual outcomes rather than on the report verdict except where they say otherwise.
    """
    base: dict[str, Any] = {
        "name": "Grey Therapeutics",
        "organization_type": OrganizationType.FOR_PROFIT,
        "principal_place_of_business_us": True,
        "employee_count": 12,
        "ownership": Ownership(
            us_individuals_percent=100,
            other_small_businesses_percent=0,
            investment_companies_percent=0,
            foreign_percent=0,
        ),
        "pi_primary_employer": PrincipalInvestigatorEmployer.COMPANY,
        "pi_company_time_percent": 100,
        "has_research_institution_partner": True,
        "work_by_company_percent": 100,
        "work_by_research_institution_percent": 0,
        "phase": AwardPhase.PHASE_I,
        "prior_phase_i_award_same_topic": False,
        "phase_i_awards_last_five_years": 0,
        "phase_ii_awards_last_five_years": 0,
        "sam_registered": True,
        "sba_company_registry_registered": True,
        "research_focus": "Patient-derived organoid screening for pancreatic cancer",
    }
    base.update(overrides)
    return CompanyProfile(**base)


@pytest.fixture
def checker() -> EligibilityChecker:
    return EligibilityChecker.from_config_file()


def outcome(
    checker: EligibilityChecker,
    rule_id: str,
    company: CompanyProfile,
    program: GrantProgram = GrantProgram.SBIR,
) -> RuleOutcome:
    report = checker.check(company, program)
    matches = [item for item in report.outcomes if item.rule_id == rule_id]
    assert matches, f"rule '{rule_id}' produced no outcome for {program.value}"
    return matches[0]


def verdict_of(
    checker: EligibilityChecker,
    rule_id: str,
    company: CompanyProfile,
    program: GrantProgram = GrantProgram.SBIR,
) -> Verdict:
    return outcome(checker, rule_id, company, program).verdict
