from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.grants.eligibility import (
    DEFAULT_RULES_PATH,
    EVALUATORS,
    AwardPhase,
    EligibilityChecker,
    EligibilityConfigError,
    OrganizationType,
    Ownership,
    PrincipalInvestigatorEmployer,
    RuleConfig,
    Verdict,
    load_rule_config,
)
from app.services.grants.errors import InvalidQueryError
from app.services.grants.models import GrantProgram
from tests.grants.eligibility.conftest import profile

SBIR = GrantProgram.SBIR
STTR = GrantProgram.STTR


def test_every_configured_rule_has_an_evaluator() -> None:
    config = load_rule_config()
    assert {rule.id for rule in config.rules} <= set(EVALUATORS)


def test_every_rule_produces_a_titled_explanation(checker: EligibilityChecker) -> None:
    for outcome in checker.check(profile(), SBIR).outcomes:
        assert outcome.title and outcome.explanation.endswith(".")
        assert outcome.citation


def test_report_stamps_the_config_version(checker: EligibilityChecker) -> None:
    report = checker.check(profile(), SBIR)
    assert report.config_version == load_rule_config().version
    assert report.phase is AwardPhase.PHASE_I


def test_one_failure_fails_the_whole_report(checker: EligibilityChecker) -> None:
    report = checker.check(profile(employee_count=900), SBIR)
    assert report.verdict is Verdict.FAIL
    assert [outcome.rule_id for outcome in report.by_verdict(Verdict.FAIL)] == ["size_standard"]
    assert "not eligible" in report.summary.lower()


def test_no_failure_but_open_questions_holds_the_report_open(
    checker: EligibilityChecker,
) -> None:
    report = checker.check(profile(), SBIR)
    assert report.verdict is Verdict.NEEDS_REVIEW
    assert {outcome.rule_id for outcome in report.by_verdict(Verdict.NEEDS_REVIEW)} == {"topic_fit"}


def test_a_report_can_pass_outright_when_no_rule_is_undecidable(
    checker: EligibilityChecker,
) -> None:
    config = load_rule_config()
    without_topic_fit = RuleConfig(
        version=config.version,
        rules=[rule for rule in config.rules if rule.id != "topic_fit"],
    )
    report = EligibilityChecker(without_topic_fit).check(profile(), SBIR)
    assert report.verdict is Verdict.PASS
    assert "passes" in report.summary


def test_an_ineligible_sbir_applicant_can_still_qualify_for_sttr(
    checker: EligibilityChecker,
) -> None:
    """An institution-based PI is the classic SBIR failure that STTR exists to allow."""
    company = profile(
        pi_primary_employer=PrincipalInvestigatorEmployer.RESEARCH_INSTITUTION,
        pi_company_time_percent=None,
        work_by_company_percent=45,
        work_by_research_institution_percent=55,
    )
    reports = checker.check_all(company)
    assert reports[SBIR].verdict is Verdict.FAIL
    assert reports[STTR].verdict is Verdict.NEEDS_REVIEW


def test_a_nonprofit_fails_both_programmes(checker: EligibilityChecker) -> None:
    reports = checker.check_all(profile(organization_type=OrganizationType.NONPROFIT))
    assert all(report.verdict is Verdict.FAIL for report in reports.values())


def test_an_empty_profile_asks_rather_than_guesses(checker: EligibilityChecker) -> None:
    blank = profile(ownership=Ownership(), **{field: None for field in _NULLABLE})
    report = checker.check(blank, SBIR)
    assert report.verdict is Verdict.NEEDS_REVIEW
    assert not report.by_verdict(Verdict.PASS)
    undecided = [item for item in report.outcomes if item.rule_id != "topic_fit"]
    assert all(item.missing_fields for item in undecided)


_NULLABLE = (
    "organization_type",
    "principal_place_of_business_us",
    "employee_count",
    "pi_primary_employer",
    "pi_company_time_percent",
    "has_research_institution_partner",
    "work_by_company_percent",
    "work_by_research_institution_percent",
    "phase",
    "prior_phase_i_award_same_topic",
    "phase_i_awards_last_five_years",
    "sam_registered",
    "sba_company_registry_registered",
)


def test_unsupported_programme_is_rejected(checker: EligibilityChecker) -> None:
    with pytest.raises(InvalidQueryError):
        checker.check(profile(), GrantProgram.BOTH)


def test_ownership_percentages_are_bounded() -> None:
    with pytest.raises(ValueError):
        Ownership(us_individuals_percent=140)


class TestConfig:
    def test_default_config_loads(self) -> None:
        config = load_rule_config()
        assert config.version
        assert len(config.for_program(SBIR)) > len(config.for_program(STTR)) - 1

    def test_disabling_a_rule_removes_it_from_reports(self, tmp_path: Path) -> None:
        payload = json.loads(DEFAULT_RULES_PATH.read_text())
        for rule in payload["rules"]:
            if rule["id"] == "size_standard":
                rule["enabled"] = False
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(payload))

        report = EligibilityChecker.from_config_file(path).check(profile(employee_count=5000), SBIR)
        assert not [item for item in report.outcomes if item.rule_id == "size_standard"]
        assert report.verdict is not Verdict.FAIL

    def test_editing_a_threshold_changes_the_verdict(self, tmp_path: Path) -> None:
        payload = json.loads(DEFAULT_RULES_PATH.read_text())
        for rule in payload["rules"]:
            if rule["id"] == "size_standard":
                rule["parameters"]["max_employees"] = 1000
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(payload))

        company = profile(employee_count=750)
        assert EligibilityChecker.from_config_file().check(company, SBIR).verdict is Verdict.FAIL
        relaxed = EligibilityChecker.from_config_file(path).check(company, SBIR)
        assert relaxed.verdict is Verdict.NEEDS_REVIEW

    def test_a_missing_threshold_raises_rather_than_passing_the_rule(self, tmp_path: Path) -> None:
        payload = json.loads(DEFAULT_RULES_PATH.read_text())
        for rule in payload["rules"]:
            if rule["id"] == "size_standard":
                rule["parameters"] = {}
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(payload))

        with pytest.raises(EligibilityConfigError, match="max_employees"):
            EligibilityChecker.from_config_file(path).check(profile(), SBIR)

    def test_an_unimplemented_rule_id_is_rejected_at_construction(self, tmp_path: Path) -> None:
        payload = json.loads(DEFAULT_RULES_PATH.read_text())
        payload["rules"].append(
            {"id": "must_be_headquartered_in_boston", "title": "Invented", "applies_to": ["SBIR"]}
        )
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(payload))

        with pytest.raises(EligibilityConfigError, match="must_be_headquartered_in_boston"):
            EligibilityChecker.from_config_file(path)

    def test_duplicate_rule_ids_are_rejected(self, tmp_path: Path) -> None:
        payload = json.loads(DEFAULT_RULES_PATH.read_text())
        payload["rules"].append(payload["rules"][0])
        path = tmp_path / "rules.json"
        path.write_text(json.dumps(payload))

        with pytest.raises(EligibilityConfigError, match="duplicate"):
            load_rule_config(path)

    def test_malformed_json_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "rules.json"
        path.write_text("{not json")
        with pytest.raises(EligibilityConfigError, match="not valid JSON"):
            load_rule_config(path)

    def test_missing_file_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(EligibilityConfigError, match="no eligibility rules"):
            load_rule_config(tmp_path / "absent.json")
