from __future__ import annotations

import pytest

from app.services.grants.eligibility import (
    AwardPhase,
    EligibilityChecker,
    OrganizationType,
    Ownership,
    PrincipalInvestigatorEmployer,
    Verdict,
)
from app.services.grants.models import GrantProgram
from tests.grants.eligibility.conftest import outcome, profile, verdict_of

SBIR = GrantProgram.SBIR
STTR = GrantProgram.STTR


class TestOrganizationType:
    def test_for_profit_passes(self, checker: EligibilityChecker) -> None:
        assert verdict_of(checker, "organization_type", profile()) is Verdict.PASS

    @pytest.mark.parametrize(
        "kind",
        [
            OrganizationType.NONPROFIT,
            OrganizationType.ACADEMIC,
            OrganizationType.GOVERNMENT,
            OrganizationType.INDIVIDUAL,
        ],
    )
    def test_every_other_entity_type_fails(
        self, checker: EligibilityChecker, kind: OrganizationType
    ) -> None:
        assert verdict_of(checker, "organization_type", profile(organization_type=kind)) is (
            Verdict.FAIL
        )

    def test_unknown_needs_review_and_names_the_missing_field(
        self, checker: EligibilityChecker
    ) -> None:
        result = outcome(checker, "organization_type", profile(organization_type=None))
        assert result.verdict is Verdict.NEEDS_REVIEW
        assert result.missing_fields == ["organization_type"]


class TestPlaceOfBusiness:
    def test_us_passes(self, checker: EligibilityChecker) -> None:
        assert verdict_of(checker, "place_of_business", profile()) is Verdict.PASS

    def test_non_us_fails(self, checker: EligibilityChecker) -> None:
        company = profile(principal_place_of_business_us=False)
        assert verdict_of(checker, "place_of_business", company) is Verdict.FAIL

    def test_unknown_needs_review(self, checker: EligibilityChecker) -> None:
        company = profile(principal_place_of_business_us=None)
        assert verdict_of(checker, "place_of_business", company) is Verdict.NEEDS_REVIEW


class TestSizeStandard:
    @pytest.mark.parametrize("headcount,expected", [(0, Verdict.PASS), (499, Verdict.PASS)])
    def test_below_the_standard_passes(
        self, checker: EligibilityChecker, headcount: int, expected: Verdict
    ) -> None:
        assert verdict_of(checker, "size_standard", profile(employee_count=headcount)) is expected

    def test_exactly_the_standard_passes(self, checker: EligibilityChecker) -> None:
        """500 is the boundary and is inclusive: 'no more than 500 employees'."""
        assert verdict_of(checker, "size_standard", profile(employee_count=500)) is Verdict.PASS

    def test_one_over_the_standard_fails(self, checker: EligibilityChecker) -> None:
        assert verdict_of(checker, "size_standard", profile(employee_count=501)) is Verdict.FAIL

    def test_unknown_headcount_needs_review(self, checker: EligibilityChecker) -> None:
        result = outcome(checker, "size_standard", profile(employee_count=None))
        assert result.verdict is Verdict.NEEDS_REVIEW
        assert result.missing_fields == ["employee_count"]

    def test_explanation_states_the_threshold_and_the_count(
        self, checker: EligibilityChecker
    ) -> None:
        result = outcome(checker, "size_standard", profile(employee_count=501))
        assert "501" in result.explanation and "500" in result.explanation
        assert result.citation


class TestUsOwnership:
    def test_exactly_the_minimum_passes(self, checker: EligibilityChecker) -> None:
        company = profile(
            ownership=Ownership(us_individuals_percent=51, foreign_percent=49),
        )
        assert verdict_of(checker, "us_ownership", company) is Verdict.PASS

    def test_one_point_below_the_minimum_fails(self, checker: EligibilityChecker) -> None:
        company = profile(
            ownership=Ownership(us_individuals_percent=50, foreign_percent=50),
        )
        assert verdict_of(checker, "us_ownership", company) is Verdict.FAIL

    def test_small_business_ownership_counts_towards_the_minimum(
        self, checker: EligibilityChecker
    ) -> None:
        company = profile(
            ownership=Ownership(
                us_individuals_percent=30,
                other_small_businesses_percent=21,
                foreign_percent=49,
            ),
        )
        assert verdict_of(checker, "us_ownership", company) is Verdict.PASS

    def test_majority_foreign_ownership_fails_on_the_foreign_share(
        self, checker: EligibilityChecker
    ) -> None:
        company = profile(
            ownership=Ownership(us_individuals_percent=40, foreign_percent=60),
        )
        result = outcome(checker, "us_ownership", company)
        assert result.verdict is Verdict.FAIL
        assert "60" in result.explanation

    def test_unrecorded_ownership_needs_review(self, checker: EligibilityChecker) -> None:
        result = outcome(checker, "us_ownership", profile(ownership=Ownership()))
        assert result.verdict is Verdict.NEEDS_REVIEW
        assert result.missing_fields == [
            "ownership.us_individuals_percent",
            "ownership.other_small_businesses_percent",
        ]


class TestInvestmentCompanyOwnership:
    def test_exactly_half_passes(self, checker: EligibilityChecker) -> None:
        company = profile(
            ownership=Ownership(us_individuals_percent=50, investment_companies_percent=50),
        )
        assert verdict_of(checker, "investment_company_ownership", company) is Verdict.PASS

    def test_just_over_half_needs_review_rather_than_failing(
        self, checker: EligibilityChecker
    ) -> None:
        """Majority-VC ownership is allowed at agencies that elected the authority."""
        company = profile(
            ownership=Ownership(us_individuals_percent=49, investment_companies_percent=51),
        )
        result = outcome(checker, "investment_company_ownership", company)
        assert result.verdict is Verdict.NEEDS_REVIEW
        assert "solicitation" in result.explanation

    def test_unknown_needs_review(self, checker: EligibilityChecker) -> None:
        company = profile(ownership=Ownership(us_individuals_percent=100))
        assert verdict_of(checker, "investment_company_ownership", company) is (
            Verdict.NEEDS_REVIEW
        )

    def test_rule_is_not_applied_to_sttr(self, checker: EligibilityChecker) -> None:
        report = checker.check(profile(), STTR)
        rule = "investment_company_ownership"
        assert not [item for item in report.outcomes if item.rule_id == rule]


class TestPrincipalInvestigatorEmployment:
    def test_sbir_boundary_is_more_than_half_time(self, checker: EligibilityChecker) -> None:
        assert verdict_of(checker, "pi_employment", profile(pi_company_time_percent=50)) is (
            Verdict.FAIL
        )
        assert verdict_of(checker, "pi_employment", profile(pi_company_time_percent=50.1)) is (
            Verdict.PASS
        )

    def test_sbir_pi_at_a_research_institution_fails(self, checker: EligibilityChecker) -> None:
        company = profile(
            pi_primary_employer=PrincipalInvestigatorEmployer.RESEARCH_INSTITUTION,
            pi_company_time_percent=None,
        )
        result = outcome(checker, "pi_employment", company)
        assert result.verdict is Verdict.FAIL
        assert "STTR" in result.explanation

    def test_sbir_company_pi_without_a_time_commitment_needs_review(
        self, checker: EligibilityChecker
    ) -> None:
        company = profile(pi_company_time_percent=None)
        result = outcome(checker, "pi_employment", company)
        assert result.verdict is Verdict.NEEDS_REVIEW
        assert result.missing_fields == ["pi_company_time_percent"]

    @pytest.mark.parametrize(
        "employer",
        [
            PrincipalInvestigatorEmployer.COMPANY,
            PrincipalInvestigatorEmployer.RESEARCH_INSTITUTION,
        ],
    )
    def test_sttr_accepts_either_employer(
        self, checker: EligibilityChecker, employer: PrincipalInvestigatorEmployer
    ) -> None:
        company = profile(pi_primary_employer=employer, pi_company_time_percent=10)
        assert verdict_of(checker, "pi_employment", company, STTR) is Verdict.PASS

    def test_sttr_rejects_a_third_party_employer(self, checker: EligibilityChecker) -> None:
        company = profile(pi_primary_employer=PrincipalInvestigatorEmployer.OTHER)
        assert verdict_of(checker, "pi_employment", company, STTR) is Verdict.FAIL


class TestResearchInstitutionPartner:
    def test_required_for_sttr(self, checker: EligibilityChecker) -> None:
        company = profile(has_research_institution_partner=False)
        assert verdict_of(checker, "research_institution_partner", company, STTR) is Verdict.FAIL

    def test_partner_present_passes(self, checker: EligibilityChecker) -> None:
        assert verdict_of(checker, "research_institution_partner", profile(), STTR) is Verdict.PASS

    def test_not_applied_to_sbir(self, checker: EligibilityChecker) -> None:
        report = checker.check(profile(has_research_institution_partner=False), SBIR)
        assert not [
            item for item in report.outcomes if item.rule_id == "research_institution_partner"
        ]


class TestWorkSplit:
    def test_sbir_phase_i_boundary(self, checker: EligibilityChecker) -> None:
        at = profile(phase=AwardPhase.PHASE_I, work_by_company_percent=66.7)
        under = profile(phase=AwardPhase.PHASE_I, work_by_company_percent=66.6)
        assert verdict_of(checker, "work_split", at) is Verdict.PASS
        assert verdict_of(checker, "work_split", under) is Verdict.FAIL

    def test_sbir_phase_ii_boundary_is_lower(self, checker: EligibilityChecker) -> None:
        company = profile(
            phase=AwardPhase.PHASE_II,
            prior_phase_i_award_same_topic=True,
            work_by_company_percent=50,
        )
        assert verdict_of(checker, "work_split", company) is Verdict.PASS
        assert (
            verdict_of(
                checker, "work_split", company.model_copy(update={"work_by_company_percent": 49.9})
            )
            is Verdict.FAIL
        )

    def test_sttr_requires_both_shares(self, checker: EligibilityChecker) -> None:
        at_boundary = profile(work_by_company_percent=40, work_by_research_institution_percent=30)
        assert verdict_of(checker, "work_split", at_boundary, STTR) is Verdict.PASS

        company_short = at_boundary.model_copy(update={"work_by_company_percent": 39})
        institution_short = at_boundary.model_copy(
            update={"work_by_research_institution_percent": 29}
        )
        assert verdict_of(checker, "work_split", company_short, STTR) is Verdict.FAIL
        assert verdict_of(checker, "work_split", institution_short, STTR) is Verdict.FAIL

    def test_sttr_failure_names_every_shortfall(self, checker: EligibilityChecker) -> None:
        company = profile(work_by_company_percent=10, work_by_research_institution_percent=10)
        result = outcome(checker, "work_split", company, STTR)
        assert "small business performs 10%" in result.explanation
        assert "research institution performs 10%" in result.explanation

    def test_sbir_without_a_phase_cannot_pick_a_threshold(
        self, checker: EligibilityChecker
    ) -> None:
        result = outcome(checker, "work_split", profile(phase=None))
        assert result.verdict is Verdict.NEEDS_REVIEW
        assert result.missing_fields == ["phase"]


class TestPhaseProgression:
    def test_phase_i_has_no_prerequisite(self, checker: EligibilityChecker) -> None:
        assert verdict_of(checker, "phase_progression", profile()) is Verdict.PASS

    def test_phase_ii_without_a_prior_phase_i_fails(self, checker: EligibilityChecker) -> None:
        company = profile(phase=AwardPhase.PHASE_II, prior_phase_i_award_same_topic=False)
        assert verdict_of(checker, "phase_progression", company) is Verdict.FAIL

    def test_phase_ii_with_a_prior_phase_i_passes(self, checker: EligibilityChecker) -> None:
        company = profile(phase=AwardPhase.PHASE_II, prior_phase_i_award_same_topic=True)
        assert verdict_of(checker, "phase_progression", company) is Verdict.PASS

    def test_phase_ii_with_unknown_history_needs_review(self, checker: EligibilityChecker) -> None:
        company = profile(phase=AwardPhase.PHASE_II, prior_phase_i_award_same_topic=None)
        assert verdict_of(checker, "phase_progression", company) is Verdict.NEEDS_REVIEW

    def test_direct_phase_ii_is_agency_specific(self, checker: EligibilityChecker) -> None:
        company = profile(phase=AwardPhase.DIRECT_PHASE_II, prior_phase_i_award_same_topic=False)
        assert verdict_of(checker, "phase_progression", company) is Verdict.NEEDS_REVIEW


class TestPerformanceBenchmarks:
    def test_at_the_threshold_passes(self, checker: EligibilityChecker) -> None:
        company = profile(phase_i_awards_last_five_years=20)
        assert verdict_of(checker, "performance_benchmarks", company) is Verdict.PASS

    def test_one_over_the_threshold_needs_review(self, checker: EligibilityChecker) -> None:
        company = profile(phase_i_awards_last_five_years=21)
        result = outcome(checker, "performance_benchmarks", company)
        assert result.verdict is Verdict.NEEDS_REVIEW
        assert "transition" in result.explanation

    def test_unknown_history_needs_review(self, checker: EligibilityChecker) -> None:
        company = profile(phase_i_awards_last_five_years=None)
        assert verdict_of(checker, "performance_benchmarks", company) is Verdict.NEEDS_REVIEW


class TestRegistrations:
    def test_both_active_passes(self, checker: EligibilityChecker) -> None:
        assert verdict_of(checker, "registrations", profile()) is Verdict.PASS

    @pytest.mark.parametrize("field", ["sam_registered", "sba_company_registry_registered"])
    def test_a_missing_registration_blocks_submission_without_failing_eligibility(
        self, checker: EligibilityChecker, field: str
    ) -> None:
        result = outcome(checker, "registrations", profile(**{field: False}))
        assert result.verdict is Verdict.NEEDS_REVIEW
        assert "cannot be submitted" in result.explanation

    def test_unknown_registration_status_needs_review(self, checker: EligibilityChecker) -> None:
        result = outcome(checker, "registrations", profile(sam_registered=None))
        assert result.verdict is Verdict.NEEDS_REVIEW
        assert result.missing_fields == ["sam_registered"]


class TestTopicFit:
    def test_never_decided_automatically(self, checker: EligibilityChecker) -> None:
        assert verdict_of(checker, "topic_fit", profile()) is Verdict.NEEDS_REVIEW

    def test_missing_focus_names_the_field(self, checker: EligibilityChecker) -> None:
        result = outcome(checker, "topic_fit", profile(research_focus="  "))
        assert result.missing_fields == ["research_focus"]
