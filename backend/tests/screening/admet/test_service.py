from __future__ import annotations

import pytest

from app.services.screening import InvalidStructureError
from app.services.screening.admet import ADMET_CAVEAT, AdmetService, Outcome

from .reference import ALL_COMPOUNDS, ASPIRIN, TERFENADINE, TICLOPIDINE, ReferenceCompound


@pytest.fixture
def service() -> AdmetService:
    return AdmetService()


@pytest.mark.parametrize("compound", ALL_COMPOUNDS, ids=lambda item: item.name)
def test_every_reference_compound_profiles_completely(
    service: AdmetService, compound: ReferenceCompound
) -> None:
    profile = service.evaluate(compound.smiles)

    assert profile.molecular_formula == compound.molecular_formula
    assert {estimate.key for estimate in profile.estimates} == {
        "gi_absorption",
        "bbb_penetration",
        "herg",
        "cyp_alerts",
        "cyp_inhibition",
        "plasma_protein_binding",
        "general_toxicity",
    }
    assert all(estimate.model_basis for estimate in profile.estimates)


def test_the_profile_carries_the_tab_level_caveat(service: AdmetService) -> None:
    profile = service.evaluate(ASPIRIN.smiles)

    assert profile.caveat == ADMET_CAVEAT
    assert "not measured" in profile.caveat
    assert "Confirm experimentally" in profile.caveat
    assert "not evidence of safety" in profile.alert_caveat


def test_evaluation_is_deterministic(service: AdmetService) -> None:
    first = service.evaluate(ASPIRIN.smiles)
    second = service.evaluate("CC(=O)OC1=CC=CC=C1C(=O)O")

    assert first == second


def test_cyp_alert_summary_lists_matched_motifs_and_excludes_the_herg_motif(
    service: AdmetService,
) -> None:
    profile = service.evaluate(TICLOPIDINE.smiles)
    alerts = profile.estimate("cyp_alerts")
    assert alerts is not None

    assert alerts.outcome is Outcome.UNFAVOURABLE
    assert "Thiophene" in alerts.verdict
    assert "hERG" not in alerts.verdict
    assert profile.alert("basic_amine_aromatic") is not None


def test_a_clean_structure_reports_no_matched_motifs_without_implying_safety(
    service: AdmetService,
) -> None:
    profile = service.evaluate(ASPIRIN.smiles)
    alerts = profile.estimate("cyp_alerts")
    assert alerts is not None

    assert alerts.outcome is Outcome.FAVOURABLE
    assert "No motif from the screened alert list is present" == alerts.verdict
    assert "an empty result only means none of the screened motifs is present" in alerts.scope
    assert profile.matched_alerts == []


def test_matched_alerts_exposes_only_the_hits(service: AdmetService) -> None:
    profile = service.evaluate(TERFENADINE.smiles)

    assert [alert.key for alert in profile.matched_alerts] == ["basic_amine_aromatic"]


@pytest.mark.parametrize(
    ("smiles", "expected"),
    [
        ("", "must not be empty"),
        ("not a molecule", "not valid in SMILES"),
        ("c1ccccc", "not a valid SMILES string"),
        (None, "must be a string"),
        ("C" * 201, "limited to 200-atom"),
    ],
)
def test_invalid_structures_are_rejected_before_any_rule_runs(
    service: AdmetService, smiles: object, expected: str
) -> None:
    with pytest.raises(InvalidStructureError) as error:
        service.evaluate(smiles)

    assert expected in str(error.value)
