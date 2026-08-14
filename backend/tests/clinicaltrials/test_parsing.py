from __future__ import annotations

from typing import Any

from app.services.clinicaltrials.models import TrialPhase, TrialRecord, TrialStatus
from app.services.clinicaltrials.parsing import parse_study
from app.services.records import RecordSource
from tests.clinicaltrials.conftest import load_json_fixture


def first_study() -> dict[str, Any]:
    studies = load_json_fixture("search_page1.json")["studies"]
    assert isinstance(studies, list)
    study = studies[0]
    assert isinstance(study, dict)
    return study


def test_parses_every_normalized_field() -> None:
    trial = parse_study(first_study())

    assert trial.nct_id == "NCT03553836"
    assert trial.status is TrialStatus.ACTIVE_NOT_RECRUITING
    assert trial.phases == [TrialPhase.PHASE3]
    assert trial.sponsor == "Merck Sharp & Dohme LLC"
    assert trial.conditions == ["Melanoma"]
    assert [item.name for item in trial.interventions] == ["Pembrolizumab", "Placebo"]
    assert trial.interventions[0].type == "BIOLOGICAL"
    assert trial.interventions[0].display_name == "Pembrolizumab (Biological)"
    assert trial.enrollment == 976
    assert trial.enrollment_type == "ACTUAL"
    assert trial.start_date == "2018-09-12"
    assert trial.primary_completion_date
    assert trial.completion_date == "2033-10-12"
    assert trial.url == "https://clinicaltrials.gov/study/NCT03553836"


def test_missing_modules_degrade_to_empty_values() -> None:
    trial = parse_study({"protocolSection": {"identificationModule": {"nctId": "NCT00000000"}}})

    assert trial.nct_id == "NCT00000000"
    assert trial.status is None
    assert trial.phases == []
    assert trial.enrollment is None
    assert trial.start_date == ""


def test_unrecognized_vocabulary_is_dropped_rather_than_raising() -> None:
    trial = parse_study(
        {
            "protocolSection": {
                "identificationModule": {"nctId": "NCT00000001"},
                "statusModule": {"overallStatus": "SOMETHING_NEW"},
                "designModule": {"phases": ["PHASE2", "PHASE_9"]},
            }
        }
    )

    assert trial.status is None
    assert trial.phases == [TrialPhase.PHASE2]


def test_phase_and_status_labels() -> None:
    combined = TrialRecord(
        nct_id="NCT1", phases=[TrialPhase.PHASE1, TrialPhase.PHASE2], status=TrialStatus.RECRUITING
    )
    assert combined.phase_label == "Phase 1/2"
    assert combined.status_label == "Recruiting"

    assert TrialRecord(nct_id="NCT2").phase_label == "N/A"
    assert TrialRecord(nct_id="NCT3", phases=[TrialPhase.NA]).phase_label == "N/A"
    assert (
        TrialRecord(nct_id="NCT4", phases=[TrialPhase.EARLY_PHASE1]).phase_label == "Early Phase 1"
    )


def test_projects_into_the_shared_review_row() -> None:
    record = parse_study(first_study()).to_source_record()

    assert record.source is RecordSource.CLINICALTRIALS
    assert record.record_id == "NCT03553836"
    assert record.subtitle == "Phase 3 · Active Not Recruiting"
    assert record.fields["Sponsor"] == "Merck Sharp & Dohme LLC"
    assert record.fields["Intervention"] == "Pembrolizumab, Placebo"
    assert record.fields["Enrollment"] == "976"
    assert record.fields["Dates"] == "2018-09-12 – 2033-10-12"
    assert record.url == "https://clinicaltrials.gov/study/NCT03553836"
