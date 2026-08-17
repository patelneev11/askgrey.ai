from __future__ import annotations

import pytest
from rdkit import Chem

from app.services.screening.admet import AdmetService, Outcome
from app.services.screening.admet.rules import (
    Descriptors2D,
    bbb_penetration,
    cyp_inhibition_unavailable,
    general_toxicity_risk,
    gi_absorption,
    herg_liability,
    plasma_protein_binding,
)

from .reference import (
    ASPIRIN,
    ASTEMIZOLE,
    ATORVASTATIN,
    CAFFEINE,
    DIAZEPAM,
    IBUPROFEN,
    MANNITOL,
    METFORMIN,
    ROSIGLITAZONE,
    SUCROSE,
    SULPIRIDE,
    TERFENADINE,
    ReferenceCompound,
)


def values(compound: ReferenceCompound) -> Descriptors2D:
    mol = Chem.MolFromSmiles(compound.smiles)
    assert mol is not None
    return Descriptors2D(mol)


@pytest.mark.parametrize("compound", [ASPIRIN, IBUPROFEN, CAFFEINE, DIAZEPAM])
def test_well_absorbed_drugs_fall_inside_the_egan_region(compound: ReferenceCompound) -> None:
    estimate = gi_absorption(values(compound))

    assert estimate.outcome is Outcome.FAVOURABLE
    assert "Egan" in estimate.verdict


def test_a_large_polar_sugar_falls_outside_the_egan_region() -> None:
    estimate = gi_absorption(values(SUCROSE))

    assert estimate.outcome is Outcome.UNFAVOURABLE
    assert all(not item.within for item in estimate.inputs if item.label == "TPSA")


def test_gi_absorption_labels_the_headline_verdict_as_predicted() -> None:
    assert "(predicted)" in gi_absorption(values(ASPIRIN)).verdict


def test_gi_absorption_states_that_it_is_a_passive_classification_only() -> None:
    estimate = gi_absorption(values(ASPIRIN))

    assert "does not estimate a fraction absorbed" in estimate.scope
    assert "active transport" in estimate.scope
    assert "Wildman-Crippen logP is substituted" in estimate.model_basis
    assert "Egan" in estimate.citation


def test_a_transporter_dependent_sugar_alcohol_is_a_documented_misclassification() -> None:
    """
    Mannitol is poorly absorbed in humans, but its descriptors sit inside the region.

    Pinned rather than hidden: the rule delineates *passive* absorption over drug-like chemical
    space, and a small very hydrophilic polyol is outside its applicability domain. The payload's
    `scope` is what tells the researcher this, so it is asserted alongside.
    """
    estimate = gi_absorption(values(MANNITOL))

    assert estimate.outcome is Outcome.FAVOURABLE
    assert "active transport" in estimate.scope


@pytest.mark.parametrize("compound", [CAFFEINE, DIAZEPAM])
def test_brain_penetrant_drugs_sit_inside_the_cns_property_space(
    compound: ReferenceCompound,
) -> None:
    estimate = bbb_penetration(values(compound))

    assert estimate.outcome is Outcome.FAVOURABLE
    assert "(predicted)" in estimate.verdict


@pytest.mark.parametrize("compound", [ATORVASTATIN, METFORMIN, SUCROSE])
def test_non_penetrant_drugs_sit_outside_the_cns_property_space(
    compound: ReferenceCompound,
) -> None:
    estimate = bbb_penetration(values(compound))

    assert estimate.outcome is Outcome.UNFAVOURABLE
    assert "outside" in estimate.verdict


def test_a_centrally_active_drug_with_poor_permeability_is_only_borderline() -> None:
    """Sulpiride is centrally active but a poor passive permeant: the rule cannot see the
    difference, which is exactly why the payload disclaims transporter effects."""
    estimate = bbb_penetration(values(SULPIRIDE))

    assert estimate.outcome is Outcome.BORDERLINE
    assert "P-glycoprotein" in estimate.scope


def test_bbb_estimate_declares_what_it_is_not() -> None:
    estimate = bbb_penetration(values(CAFFEINE))

    assert "not a logBB" in estimate.scope
    assert "CNS MPO score is not computed" in estimate.model_basis
    assert {item.label for item in estimate.inputs} == {
        "Molecular weight",
        "TPSA",
        "H-bond donors",
        "cLogP",
    }


@pytest.mark.parametrize("compound", [TERFENADINE, ASTEMIZOLE])
def test_canonical_herg_blockers_match_the_pharmacophore(compound: ReferenceCompound) -> None:
    estimate = herg_liability(values(compound))

    assert estimate.outcome is Outcome.UNFAVOURABLE
    assert "hERG pharmacophore" in estimate.verdict
    assert "predicted" in estimate.verdict


@pytest.mark.parametrize("compound", [ASPIRIN, CAFFEINE, METFORMIN])
def test_compounds_without_a_basic_lipophilic_centre_do_not_match(
    compound: ReferenceCompound,
) -> None:
    assert herg_liability(values(compound)).outcome is Outcome.FAVOURABLE


def test_herg_estimate_refuses_to_imply_safety_or_potency() -> None:
    estimate = herg_liability(values(ASPIRIN))

    assert "not an IC50" in estimate.scope
    assert "not evidence of cardiac safety" in estimate.scope
    assert "does not compute pKa" in estimate.model_basis


def test_the_3_75_rule_bands_lipophilic_low_polarity_compounds_as_higher_risk() -> None:
    assert general_toxicity_risk(values(TERFENADINE)).outcome is Outcome.UNFAVOURABLE
    assert general_toxicity_risk(values(METFORMIN)).outcome is Outcome.FAVOURABLE
    assert general_toxicity_risk(values(ROSIGLITAZONE)).outcome is Outcome.BORDERLINE


def test_the_3_75_rule_states_that_it_is_a_population_level_association() -> None:
    estimate = general_toxicity_risk(values(TERFENADINE))

    assert "not a prediction of toxicity for this one" in estimate.scope
    assert "Hughes" in estimate.citation


def test_plasma_protein_binding_is_unavailable_with_a_reason_and_no_number() -> None:
    estimate = plasma_protein_binding()

    assert estimate.available is False
    assert estimate.outcome is Outcome.UNAVAILABLE
    assert estimate.verdict == ""
    assert "Unavailable" in estimate.reason
    assert "equilibrium-dialysis" in estimate.requires
    assert estimate.model_basis
    assert "%" not in estimate.reason


def test_per_isoform_cyp_prediction_is_unavailable_and_points_at_the_alert_list() -> None:
    estimate = cyp_inhibition_unavailable()

    assert estimate.available is False
    assert estimate.outcome is Outcome.UNAVAILABLE
    assert "structural-alert list" in estimate.reason
    assert "trained" in estimate.requires


def test_every_estimate_carries_a_non_empty_model_basis() -> None:
    profile = AdmetService().evaluate(ASPIRIN.smiles)

    assert profile.estimates
    for estimate in profile.estimates:
        assert estimate.model_basis.strip(), estimate.key


@pytest.mark.parametrize("compound", [ASPIRIN, TERFENADINE, ROSIGLITAZONE])
def test_no_estimate_quotes_a_pharmacokinetic_measurement(compound: ReferenceCompound) -> None:
    """Verdicts are classifications; a unit or a potency term would mean a fabricated value."""
    profile = AdmetService().evaluate(compound.smiles)
    forbidden = ("%", "IC50", "uM", "nM", "mg", "ng/mL", "CL/F", "logBB", "fu ")

    for estimate in profile.estimates:
        for token in forbidden:
            assert token not in estimate.verdict, (estimate.key, token)
