from __future__ import annotations

import pytest
from rdkit import Chem

from app.services.screening.admet import ALERT_SPECS, evaluate_alerts, has_basic_amine

from .reference import (
    ASPIRIN,
    CAFFEINE,
    METFORMIN,
    PAROXETINE,
    ROSIGLITAZONE,
    TERFENADINE,
    TICLOPIDINE,
    ReferenceCompound,
)


def mol(smiles: str) -> Chem.Mol:
    parsed = Chem.MolFromSmiles(smiles)
    assert parsed is not None
    return parsed


def matched_keys(smiles: str) -> set[str]:
    return {alert.key for alert in evaluate_alerts(mol(smiles)) if alert.matched}


@pytest.mark.parametrize(
    ("compound", "key"),
    [
        (PAROXETINE, "methylenedioxyphenyl"),
        (ROSIGLITAZONE, "thiazolidinedione"),
        (TICLOPIDINE, "thiophene"),
    ],
)
def test_documented_liability_motifs_are_matched(compound: ReferenceCompound, key: str) -> None:
    assert key in matched_keys(compound.smiles)


@pytest.mark.parametrize(
    ("smiles", "key"),
    [
        ("C#Cc1ccccc1", "terminal_alkyne"),
        ("c1ccoc1", "furan"),
        ("S=C=Nc1ccccc1", "isothiocyanate"),
        ("NNc1ccccc1", "hydrazine"),
    ],
)
def test_each_remaining_motif_fires_on_a_minimal_example(smiles: str, key: str) -> None:
    assert key in matched_keys(smiles)


@pytest.mark.parametrize(
    "smiles",
    [
        # An internal alkyne is not the liability; only a terminal one forms the ketene.
        "CC#CC",
        # Benzene is not furan, and a phenol ether is not a benzodioxole.
        "COc1ccccc1",
        # An amide N-N is not a basic hydrazine.
        "O=C(N)Nc1ccccc1",
    ],
)
def test_near_misses_do_not_fire(smiles: str) -> None:
    assert matched_keys(smiles) - {"basic_amine_aromatic"} == set()


def test_every_alert_is_reported_whether_or_not_it_matched() -> None:
    alerts = evaluate_alerts(mol(ASPIRIN.smiles))

    assert [alert.key for alert in alerts] == [spec.key for spec in ALERT_SPECS]
    assert all(not alert.matched for alert in alerts)
    assert all(alert.citation for alert in alerts)
    assert all(alert.concern for alert in alerts)


def test_the_herg_motif_states_that_a_non_match_does_not_clear_a_compound() -> None:
    alert = next(spec for spec in ALERT_SPECS if spec.key == "basic_amine_aromatic")

    assert "absence of this motif does not clear a compound" in alert.concern


def test_basic_amine_detection_ignores_amides_anilines_and_guanidines() -> None:
    assert has_basic_amine(mol(TERFENADINE.smiles)) is True
    assert has_basic_amine(mol("CCN(CC)CC")) is True
    assert has_basic_amine(mol(ASPIRIN.smiles)) is False
    assert has_basic_amine(mol(CAFFEINE.smiles)) is False
    assert has_basic_amine(mol("CC(=O)NC")) is False
    assert has_basic_amine(mol(METFORMIN.smiles)) is False
