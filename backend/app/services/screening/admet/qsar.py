"""
Inference for the trained QSAR models: artifact loading, tree evaluation, applicability domain.

Why the models are shipped as JSON gradient-boosted trees evaluated by the code below, rather than
as a pickled scikit-learn estimator: a pickle executes arbitrary code on load and binds the
service to one scikit-learn build, whereas this artifact is data that is schema-validated on load
(`QsarArtifact`), diffable in review, and evaluated by ~30 lines of numpy. scikit-learn is a
training-time dependency only; nothing here touches the network or the filesystem outside the
package directory.

Every prediction is gated on the applicability domain. A structure whose substructures the
training set never saw gets no number: `predict` returns a result with `in_domain=False` and the
caller renders the property as unavailable. That is the whole point of the gate — a boosted tree
extrapolates silently and confidently, so refusing is the only honest answer outside the domain.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, Field, ValidationError
from rdkit import Chem

from .features import (
    DESCRIPTOR_NAMES,
    FEATURE_COUNT,
    FEATURIZER_VERSION,
    MORGAN_BITS,
    featurize,
    fingerprint_bits,
    peptide_linkage_count,
)

ARTIFACT_DIRECTORY = Path(__file__).parent / "qsar_models"
ARTIFACT_SCHEMA_VERSION = 1

# Reported in `QsarPrediction.out_of_domain_descriptors` when the peptide check, rather than a
# descriptor bound, is what refuses the structure.
PEPTIDE_MARKER = "peptide_linkages"


class QsarArtifactError(RuntimeError):
    """An artifact is missing, malformed, or was built by an incompatible featurizer."""


class DatasetProvenance(BaseModel):
    """Where the labels came from, so the payload can cite them."""

    name: str
    description: str
    endpoint: str
    units: str
    license: str
    citation: str
    url: str
    compounds: int


class SplitInfo(BaseModel):
    method: str
    train_size: int
    test_size: int


class TreeData(BaseModel):
    """One decision tree, flattened. Leaves have `feature == -1`."""

    feature: list[int]
    threshold: list[float]
    left: list[int]
    right: list[int]
    value: list[float]


class PlattCalibration(BaseModel):
    """Logistic recalibration of the raw margin, fitted on a held-out calibration split."""

    method: Literal["platt"] = "platt"
    slope: float
    intercept: float


class ApplicabilityDomain(BaseModel):
    """
    The domain the model may speak about.

    A query is in domain when it has a training neighbour at Tanimoto >= `min_tanimoto`, its
    descriptors sit inside the training range (widened by `descriptor_slack`), and it carries no
    more peptide backbone linkages than the training set did. `reference_bits` holds the Morgan
    on-bits of a diverse subsample of the training set rather than all of it, so the similarity
    reported is a lower bound on the true nearest-neighbour similarity and the gate errs towards
    refusing.

    The peptide count is a separate check because fingerprint similarity cannot make it: a
    tripeptide is a chain of amide fragments the training set has seen individually, so it clears a
    similarity threshold set for small-molecule chemistry while being nothing the model was fitted
    on. Runtime testing found leu-enkephalin served four numbers on that basis.
    """

    reference_bits: list[list[int]]
    min_tanimoto: float
    descriptor_bounds: dict[str, tuple[float, float]]
    descriptor_slack: float
    max_peptide_linkages: int


class QsarArtifact(BaseModel):
    """A trained model plus everything needed to report it honestly."""

    schema_version: int = Field(ge=1)
    key: str
    label: str
    task: Literal["classification", "regression"]
    featurizer_version: str
    feature_count: int
    baseline: float
    trees: list[TreeData]
    calibration: PlattCalibration | None = None
    metrics: dict[str, float]
    metric_summary: str
    dataset: DatasetProvenance
    split: SplitInfo
    training_command: str
    applicability_domain: ApplicabilityDomain


class QsarPrediction(BaseModel):
    """One model's output for one structure, in or out of domain."""

    key: str
    in_domain: bool
    # Tanimoto similarity to the closest molecule in the artifact's training reference set.
    nearest_training_similarity: float
    out_of_domain_descriptors: list[str] = Field(default_factory=list)
    # Calibrated probability for a classifier, predicted endpoint value for a regressor. None when
    # the structure is out of domain: no number is produced at all.
    probability: float | None = None
    value: float | None = None


class _CompiledTree:
    """A tree in the array form the evaluator walks."""

    __slots__ = ("feature", "threshold", "left", "right", "value")

    def __init__(self, tree: TreeData) -> None:
        self.feature: NDArray[np.int32] = np.asarray(tree.feature, dtype=np.int32)
        self.threshold: NDArray[np.float64] = np.asarray(tree.threshold, dtype=np.float64)
        self.left: NDArray[np.int32] = np.asarray(tree.left, dtype=np.int32)
        self.right: NDArray[np.int32] = np.asarray(tree.right, dtype=np.int32)
        self.value: NDArray[np.float64] = np.asarray(tree.value, dtype=np.float64)

    def evaluate(self, vector: NDArray[np.float64]) -> float:
        node = 0
        while self.feature[node] >= 0:
            if vector[self.feature[node]] <= self.threshold[node]:
                node = int(self.left[node])
            else:
                node = int(self.right[node])
        return float(self.value[node])


class QsarModel:
    """A loaded artifact: raw margin, calibration, applicability domain."""

    def __init__(self, artifact: QsarArtifact) -> None:
        if artifact.schema_version != ARTIFACT_SCHEMA_VERSION:
            raise QsarArtifactError(
                f"{artifact.key}: artifact schema version {artifact.schema_version} != "
                f"{ARTIFACT_SCHEMA_VERSION}"
            )
        if artifact.featurizer_version != FEATURIZER_VERSION:
            raise QsarArtifactError(
                f"{artifact.key}: artifact was built with featurizer "
                f"{artifact.featurizer_version!r}, this build computes {FEATURIZER_VERSION!r}"
            )
        if artifact.feature_count != FEATURE_COUNT:
            raise QsarArtifactError(
                f"{artifact.key}: artifact expects {artifact.feature_count} features, this build "
                f"computes {FEATURE_COUNT}"
            )
        if not artifact.trees:
            raise QsarArtifactError(f"{artifact.key}: artifact contains no trees")
        if artifact.task == "classification" and artifact.calibration is None:
            raise QsarArtifactError(f"{artifact.key}: a classifier must ship its calibration")
        if not artifact.applicability_domain.reference_bits:
            raise QsarArtifactError(
                f"{artifact.key}: artifact ships no applicability-domain reference set"
            )

        self.artifact = artifact
        self._trees = [_CompiledTree(tree) for tree in artifact.trees]
        self._references = [
            frozenset(bits) for bits in artifact.applicability_domain.reference_bits if bits
        ]

    @property
    def key(self) -> str:
        return self.artifact.key

    def raw_margin(self, vector: NDArray[np.float64]) -> float:
        """The ensemble's uncalibrated output; public so the training script can verify it."""
        # Leaf values already carry the learning rate, so the ensemble is a plain sum.
        return self.artifact.baseline + sum(tree.evaluate(vector) for tree in self._trees)

    def _domain(self, mol: Chem.Mol, vector: NDArray[np.float64]) -> tuple[bool, float, list[str]]:
        domain = self.artifact.applicability_domain
        bits = fingerprint_bits(mol)
        similarity = 0.0
        for reference in self._references:
            shared = len(bits & reference)
            if not shared:
                continue
            tanimoto = shared / (len(bits) + len(reference) - shared)
            if tanimoto > similarity:
                similarity = tanimoto

        outside: list[str] = []
        for offset, name in enumerate(DESCRIPTOR_NAMES):
            bounds = domain.descriptor_bounds.get(name)
            if bounds is None:
                continue
            low, high = bounds
            span = high - low
            slack = abs(span) * domain.descriptor_slack
            observed = float(vector[MORGAN_BITS + offset])
            if observed < low - slack or observed > high + slack:
                outside.append(name)

        peptide_linkages = peptide_linkage_count(mol)
        if peptide_linkages > domain.max_peptide_linkages:
            outside.append(PEPTIDE_MARKER)

        in_domain = similarity >= domain.min_tanimoto and not outside
        return in_domain, similarity, outside

    def predict(self, mol: Chem.Mol) -> QsarPrediction:
        vector = featurize(mol)
        in_domain, similarity, outside = self._domain(mol, vector)
        prediction = QsarPrediction(
            key=self.key,
            in_domain=in_domain,
            nearest_training_similarity=round(similarity, 4),
            out_of_domain_descriptors=outside,
        )
        if not in_domain:
            return prediction

        margin = self.raw_margin(vector)
        if self.artifact.task == "classification":
            calibration = self.artifact.calibration
            assert calibration is not None  # enforced in __init__
            scaled = calibration.slope * margin + calibration.intercept
            prediction.probability = round(float(1.0 / (1.0 + np.exp(-scaled))), 4)
        else:
            prediction.value = round(margin, 2)
        return prediction


def load_artifact(path: Path) -> QsarArtifact:
    """Read and validate one artifact file."""
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise QsarArtifactError(f"{path.name}: unreadable artifact ({error})") from error
    try:
        return QsarArtifact.model_validate(payload)
    except ValidationError as error:
        raise QsarArtifactError(f"{path.name}: artifact does not match the schema") from error


def load_model(path: Path) -> QsarModel:
    return QsarModel(load_artifact(path))


@lru_cache(maxsize=1)
def load_models(directory: Path = ARTIFACT_DIRECTORY) -> dict[str, QsarModel]:
    """
    Load every artifact in the package's model directory, keyed by model key.

    Cached: the artifacts are read-only package data, and parsing them on every request would
    dominate the response time. A malformed or incompatible artifact fails loudly here rather than
    silently degrading a prediction.
    """
    models: dict[str, QsarModel] = {}
    for path in sorted(directory.glob("*.json")):
        model = load_model(path)
        if model.key in models:
            raise QsarArtifactError(f"duplicate model key {model.key!r} in {directory}")
        models[model.key] = model
    return models
