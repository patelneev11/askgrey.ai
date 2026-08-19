"""
Tests for the trained QSAR layer: artifacts, tree evaluation, applicability domain, degradation.

The assertions on the shipped artifacts are deliberately about provenance and refusal behaviour
rather than about individual predicted numbers: the numbers a fitted model produces are the
model's, and pinning them here would only re-assert the training run. What is pinned is that the
artifacts declare their dataset, licence and scaffold-split metrics, that the evaluator is exact
and deterministic, and that anything the model cannot honestly answer becomes an unavailable
estimate instead of a number.
"""

from __future__ import annotations

import json
import math
import socket
from pathlib import Path

import pytest
from rdkit import Chem

from app.services.screening.admet import qsar_estimates
from app.services.screening.admet.features import (
    FEATURE_COUNT,
    FEATURIZER_VERSION,
    MORGAN_BITS,
    featurize,
    peptide_linkage_count,
)
from app.services.screening.admet.qsar import (
    ARTIFACT_DIRECTORY,
    QsarArtifactError,
    QsarModel,
    load_artifact,
    load_model,
    load_models,
)
from app.services.screening.admet.qsar_presentation import QSAR_KEYS

from .reference import ASPIRIN, ETHANOL, TERFENADINE

ARTIFACT_PATHS = sorted(ARTIFACT_DIRECTORY.glob("*.json"))


def _mol(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return mol


def test_every_declared_model_ships_an_artifact() -> None:
    assert {path.stem for path in ARTIFACT_PATHS} == set(QSAR_KEYS)


@pytest.mark.parametrize("path", ARTIFACT_PATHS, ids=lambda item: item.stem)
def test_each_artifact_declares_its_provenance_and_held_out_metrics(path: Path) -> None:
    artifact = load_artifact(path)

    assert artifact.key == path.stem
    assert artifact.featurizer_version == FEATURIZER_VERSION
    assert artifact.feature_count == FEATURE_COUNT
    assert artifact.dataset.license
    assert artifact.dataset.citation
    assert artifact.dataset.url.startswith("https://")
    assert artifact.dataset.compounds > 0
    assert "scaffold" in artifact.split.method
    assert artifact.split.train_size > artifact.split.test_size > 0
    assert artifact.training_command
    assert artifact.metric_summary
    assert artifact.applicability_domain.reference_bits
    assert 0.0 < artifact.applicability_domain.min_tanimoto < 1.0
    assert artifact.applicability_domain.max_peptide_linkages >= 0

    if artifact.task == "classification":
        assert artifact.metrics["roc_auc"] >= 0.75
        assert artifact.calibration is not None
    else:
        assert artifact.metrics["r2"] >= 0.30
        assert artifact.metrics["mae"] > 0.0


@pytest.mark.parametrize("path", ARTIFACT_PATHS, ids=lambda item: item.stem)
def test_no_artifact_references_a_feature_outside_the_vector(path: Path) -> None:
    artifact = load_artifact(path)

    for tree in artifact.trees:
        assert max(tree.feature) < FEATURE_COUNT
        assert min(tree.feature) >= -1


def test_prediction_is_deterministic_and_bounded() -> None:
    models = load_models()
    mol = _mol(TERFENADINE.smiles)

    for key, model in models.items():
        first = model.predict(mol)
        second = model.predict(_mol(TERFENADINE.smiles))
        assert first == second, key
        if first.probability is not None:
            assert 0.0 <= first.probability <= 1.0


def test_a_drug_like_structure_is_inside_the_classifier_domains() -> None:
    model = load_models()["herg_blockade"]
    prediction = model.predict(_mol(TERFENADINE.smiles))

    assert prediction.in_domain
    assert prediction.probability is not None
    assert prediction.out_of_domain_descriptors == []
    assert (
        prediction.nearest_training_similarity >= model.artifact.applicability_domain.min_tanimoto
    )


def test_a_structure_unlike_the_training_set_gets_no_number() -> None:
    for key, model in load_models().items():
        prediction = model.predict(_mol(ETHANOL.smiles))

        assert not prediction.in_domain, key
        assert prediction.probability is None
        assert prediction.value is None
        assert (
            prediction.nearest_training_similarity
            < model.artifact.applicability_domain.min_tanimoto
            or prediction.out_of_domain_descriptors
        )


# Peptides clear the fingerprint-similarity gate — an amide chain is built from fragments the
# training sets contain — so they are the case the peptide-linkage bound exists for. Runtime testing
# of the endpoint found four of five models serving leu-enkephalin a number before it was added.
PEPTIDES = {
    "leu_enkephalin": "CC(C)CC(NC(=O)C(Cc1ccccc1)NC(=O)CNC(=O)CNC(=O)C(N)Cc1ccc(O)cc1)C(=O)O",
    "triglycine": "NCC(=O)NCC(=O)NCC(=O)O",
    "cyclic_tetrapeptide": "O=C1NCC(=O)NCC(=O)NCC(=O)NC1",
    # A peptidomimetic, refused with the peptides: two backbone linkages is more peptide chain than
    # the assay sets contain.
    "atazanavir": (
        "COC(=O)NC(C(C)(C)C)C(=O)NC(Cc1ccccc1)C(O)C(Cc1ccccc1)NNC(=O)C(NC(=O)OC)C(C)(C)C"
    ),
}


@pytest.mark.parametrize("name", sorted(PEPTIDES), ids=sorted(PEPTIDES))
def test_no_model_predicts_for_a_peptide(name: str) -> None:
    mol = _mol(PEPTIDES[name])

    for key, model in load_models().items():
        prediction = model.predict(mol)

        assert not prediction.in_domain, key
        assert prediction.probability is None, key
        assert prediction.value is None, key

    for estimate in qsar_estimates(mol):
        assert estimate.available is False
        assert "peptide backbone linkages" in estimate.reason


def test_the_peptide_bound_does_not_refuse_ordinary_drugs() -> None:
    """
    The gate must catch peptides without collapsing the domain for amide-containing drugs.

    Ampicillin is the reason the bound is one linkage rather than zero: a beta-lactam side chain
    matches the same motif as a single peptide bond, and beta-lactams are in these training sets.
    """
    ampicillin = "CC1(C)SC2C(NC(=O)C(N)c3ccccc3)C(=O)N2C1C(=O)O"
    assert peptide_linkage_count(_mol(ampicillin)) == 1

    for smiles in (TERFENADINE.smiles, ASPIRIN.smiles, "CC(=O)Nc1ccc(O)cc1", ampicillin):
        mol = _mol(smiles)
        served = [key for key, model in load_models().items() if model.predict(mol).in_domain]
        assert served, smiles


def test_out_of_domain_estimates_say_so_instead_of_guessing() -> None:
    estimates = {estimate.key: estimate for estimate in qsar_estimates(_mol(ETHANOL.smiles))}

    assert set(estimates) == set(QSAR_KEYS)
    for key, estimate in estimates.items():
        assert estimate.available is False, key
        assert estimate.outcome.value == "unavailable"
        assert estimate.verdict == ""
        assert "applicability domain" in estimate.reason
        assert estimate.requires


def test_in_domain_estimates_report_the_model_basis_not_a_measurement() -> None:
    estimates = {estimate.key: estimate for estimate in qsar_estimates(_mol(TERFENADINE.smiles))}
    herg = estimates["herg_blockade"]

    assert herg.available is True
    assert "calibrated probability" in herg.verdict
    assert "Gradient-boosted decision trees" in herg.model_basis
    assert "not a measurement" in herg.model_basis
    assert herg.citation
    assert [item.label for item in herg.inputs] == [
        "Calibrated probability",
        "Applicability domain",
    ]


def test_the_evaluator_reproduces_a_hand_built_ensemble() -> None:
    artifact = load_artifact(ARTIFACT_DIRECTORY / "herg_blockade.json")
    payload = artifact.model_dump()
    payload["baseline"] = 0.5
    payload["trees"] = [
        {
            "feature": [0, -1, -1],
            "threshold": [0.5, 0.0, 0.0],
            "left": [1, -1, -1],
            "right": [2, -1, -1],
            "value": [0.0, -1.0, 2.0],
        }
    ]
    payload["calibration"] = {"method": "platt", "slope": 1.0, "intercept": 0.0}
    model = QsarModel(type(artifact).model_validate(payload))

    vector = featurize(_mol(TERFENADINE.smiles))
    vector[0] = 0.0
    assert model.raw_margin(vector) == pytest.approx(-0.5)
    vector[0] = 1.0
    assert model.raw_margin(vector) == pytest.approx(2.5)
    assert model.predict(_mol(TERFENADINE.smiles)).probability == pytest.approx(
        round(1.0 / (1.0 + math.exp(-model.raw_margin(featurize(_mol(TERFENADINE.smiles))))), 4)
    )


def test_descriptor_bounds_gate_the_domain_independently_of_the_fingerprint() -> None:
    artifact = load_artifact(ARTIFACT_DIRECTORY / "herg_blockade.json")
    payload = artifact.model_dump()
    payload["applicability_domain"]["descriptor_bounds"]["molecular_weight"] = (0.0, 1.0)
    payload["applicability_domain"]["descriptor_slack"] = 0.0
    model = QsarModel(type(artifact).model_validate(payload))

    prediction = model.predict(_mol(TERFENADINE.smiles))

    assert (
        prediction.nearest_training_similarity >= model.artifact.applicability_domain.min_tanimoto
    )
    assert prediction.out_of_domain_descriptors == ["molecular_weight"]
    assert not prediction.in_domain
    assert prediction.probability is None


def test_an_artifact_from_a_different_featurizer_is_refused(tmp_path: Path) -> None:
    payload = load_artifact(ARTIFACT_DIRECTORY / "herg_blockade.json").model_dump()
    payload["featurizer_version"] = "morgan3-4096"
    path = tmp_path / "herg_blockade.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(QsarArtifactError, match="featurizer"):
        load_model(path)


def test_an_artifact_without_a_domain_reference_set_is_refused(tmp_path: Path) -> None:
    payload = load_artifact(ARTIFACT_DIRECTORY / "herg_blockade.json").model_dump()
    payload["applicability_domain"]["reference_bits"] = []
    path = tmp_path / "herg_blockade.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(QsarArtifactError, match="applicability-domain reference set"):
        load_model(path)


def test_a_classifier_without_calibration_is_refused(tmp_path: Path) -> None:
    payload = load_artifact(ARTIFACT_DIRECTORY / "herg_blockade.json").model_dump()
    payload["calibration"] = None
    path = tmp_path / "herg_blockade.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(QsarArtifactError, match="calibration"):
        load_model(path)


def test_a_corrupt_artifact_is_refused_rather_than_half_loaded(tmp_path: Path) -> None:
    truncated = tmp_path / "herg_blockade.json"
    truncated.write_text('{"key": "herg_blockade", "trees": [')
    with pytest.raises(QsarArtifactError, match="unreadable"):
        load_model(truncated)

    wrong_shape = tmp_path / "other.json"
    wrong_shape.write_text('{"key": "herg_blockade"}')
    with pytest.raises(QsarArtifactError, match="schema"):
        load_model(wrong_shape)


def test_a_build_without_artifacts_degrades_to_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.screening.admet.qsar_presentation.load_models",
        lambda: load_models(tmp_path),
    )

    estimates = qsar_estimates(_mol(TERFENADINE.smiles))

    assert {estimate.key for estimate in estimates} == set(QSAR_KEYS)
    for estimate in estimates:
        assert estimate.available is False
        assert estimate.outcome.value == "unavailable"
        assert "not present in this build" in estimate.model_basis
        assert "train.py" in estimate.requires


def test_a_load_failure_degrades_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode() -> dict[str, QsarModel]:
        raise QsarArtifactError("broken")

    monkeypatch.setattr(
        "app.services.screening.admet.qsar_presentation.load_models",
        explode,
    )

    estimates = qsar_estimates(_mol(ASPIRIN.smiles))

    assert all(estimate.outcome.value == "unavailable" for estimate in estimates)


def test_the_fingerprint_block_and_descriptor_block_keep_their_layout() -> None:
    vector = featurize(_mol(ASPIRIN.smiles))

    assert vector.shape == (FEATURE_COUNT,)
    assert vector[:MORGAN_BITS].max() > 0.0
    assert vector[MORGAN_BITS] == pytest.approx(180.16, abs=0.01)


def test_inference_opens_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Predictions come from package data; a network call here would be a supply-chain surprise."""

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("inference attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    load_models.cache_clear()
    estimates = qsar_estimates(_mol(TERFENADINE.smiles))

    assert any(estimate.available for estimate in estimates)
