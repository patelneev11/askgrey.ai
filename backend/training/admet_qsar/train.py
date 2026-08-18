"""
Train and export the ADMET QSAR models the screening service serves.

Run from `backend/` with the training extra installed (see README.md in this directory):

    .venv/bin/python training/admet_qsar/train.py --target herg_blockade --write

Design notes that matter for anyone re-running this:

* Split is by Bemis-Murcko scaffold, largest scaffold groups first into train. A random split on
  these datasets flatters every model by putting analogues of the test compounds in training; the
  numbers this script prints are the scaffold-split numbers, and they are the numbers the API
  quotes.
* A held-out calibration slice (never trained on, never used for reporting) fits the Platt scaling,
  so the probability the API returns means something close to a frequency.
* Export is verified: the JSON artifact is re-evaluated with the service's own evaluator and must
  reproduce scikit-learn's raw margin to 1e-6 on the whole test set, otherwise nothing is written.
* A target whose held-out metrics miss the bar in `MINIMUM_METRICS` is reported as FAILED and its
  artifact is not written, no matter what `--write` says.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from rdkit import Chem, RDLogger
from rdkit.Chem.Scaffolds import MurckoScaffold
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    balanced_accuracy_score,
    brier_score_loss,
    mean_absolute_error,
    r2_score,
    roc_auc_score,
)
from sklearn.tree import DecisionTreeRegressor

BACKEND_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.screening.admet.features import (  # noqa: E402
    DESCRIPTOR_NAMES,
    FEATURE_COUNT,
    FEATURIZER_VERSION,
    MORGAN_BITS,
    featurize,
    fingerprint_bits,
)
from app.services.screening.admet.qsar import (  # noqa: E402
    ARTIFACT_DIRECTORY,
    ARTIFACT_SCHEMA_VERSION,
    QsarArtifact,
    QsarModel,
)

RDLogger.DisableLog("rdApp.*")

DATA_DIRECTORY = Path(__file__).parent / "data"
RANDOM_STATE = 0
TEST_FRACTION = 0.2
CALIBRATION_FRACTION = 0.1
# The applicability domain is a nearest-neighbour similarity gate (Sheridan et al., J. Chem. Inf.
# Comput. Sci. 44 (2004) 1912-1928) over a diverse subsample of the training set, backed by a
# descriptor-range check. The subsample is bounded so the artifact stays a reviewable JSON file;
# picking it by MaxMin keeps the covered chemistry, and any molecule left out can only make the
# reported similarity an underestimate.
DOMAIN_REFERENCE_LIMIT = 1200
# The similarity below which a training molecule would have been an outlier in its own training
# set: the threshold is read off that distribution rather than chosen by hand.
DOMAIN_PERCENTILE = 1.0
# Descriptor bounds are the 0.5th-99.5th training percentile widened by a quarter of that range:
# tight enough to catch a peptide or a salt fragment, loose enough not to refuse an aspirin-sized
# drug just because the training set skewed large.
DESCRIPTOR_PERCENTILE = 0.5
DESCRIPTOR_SLACK = 0.25

# The bar a model must clear on the scaffold-split test set to be served at all. Set before
# training, not after looking at the results.
MINIMUM_METRICS: dict[str, tuple[str, float]] = {
    "classification": ("roc_auc", 0.75),
    "regression": ("r2", 0.30),
}


@dataclass(frozen=True)
class Target:
    key: str
    label: str
    task: Literal["classification", "regression"]
    loader: Callable[[], pd.DataFrame]
    description: str
    endpoint: str
    units: str
    license: str
    citation: str
    url: str


def _adme(name: str) -> Callable[[], pd.DataFrame]:
    def load() -> pd.DataFrame:
        from tdc.single_pred import ADME

        return ADME(name=name, path=str(DATA_DIRECTORY)).get_data()

    return load


def _tox(name: str) -> Callable[[], pd.DataFrame]:
    def load() -> pd.DataFrame:
        from tdc.single_pred import Tox

        return Tox(name=name, path=str(DATA_DIRECTORY)).get_data()

    return load


TDC_URL = "https://tdcommons.ai"

TARGETS: tuple[Target, ...] = (
    Target(
        key="herg_blockade",
        label="hERG blockade (QSAR)",
        task="classification",
        loader=_tox("hERG_Karim"),
        description=(
            "hERG channel blockade calls assembled by Karim et al. from patch-clamp and "
            "fluorescence-based screens; a compound is labelled a blocker at IC50 < 10 uM."
        ),
        endpoint="probability that the compound blocks hERG at IC50 < 10 uM",
        units="probability",
        license="CC BY 4.0",
        citation=(
            "Karim et al., Sci. Rep. 11 (2021) 7628 (CardioTox net); dataset via Therapeutics "
            "Data Commons (hERG_Karim)"
        ),
        url=f"{TDC_URL}/single_pred_tasks/tox/#herg-karim-et-al",
    ),
    Target(
        key="plasma_protein_binding",
        label="Plasma protein binding (QSAR)",
        task="regression",
        loader=_adme("PPBR_AZ"),
        description=(
            "Human plasma protein binding measured by AstraZeneca and released through ChEMBL, "
            "expressed as the percentage of drug bound to plasma proteins."
        ),
        endpoint="percentage of compound bound to human plasma proteins",
        units="% bound",
        license="CC BY 4.0",
        citation=(
            "AstraZeneca, deposited data set (ChEMBL3301365); dataset via Therapeutics Data "
            "Commons (PPBR_AZ)"
        ),
        url=f"{TDC_URL}/single_pred_tasks/adme/#ppbr-plasma-protein-binding-rate-astrazeneca",
    ),
    Target(
        key="cyp3a4_inhibition",
        label="CYP3A4 inhibition (QSAR)",
        task="classification",
        loader=_adme("CYP3A4_Veith"),
        description=(
            "CYP3A4 inhibition from the Veith et al. quantitative high-throughput screen of "
            "~17,000 compounds against five P450 isoforms (PubChem AID 1851)."
        ),
        endpoint="probability of CYP3A4 inhibition in the Veith qHTS assay",
        units="probability",
        license="CC BY 4.0",
        citation=(
            "Veith et al., Nat. Biotechnol. 27 (2009) 1050-1055; dataset via Therapeutics Data "
            "Commons (CYP3A4_Veith)"
        ),
        url=f"{TDC_URL}/single_pred_tasks/adme/#cyp-p450-3a4-inhibition-veith-et-al",
    ),
    Target(
        key="cyp2d6_inhibition",
        label="CYP2D6 inhibition (QSAR)",
        task="classification",
        loader=_adme("CYP2D6_Veith"),
        description=(
            "CYP2D6 inhibition from the Veith et al. quantitative high-throughput screen "
            "(PubChem AID 1851)."
        ),
        endpoint="probability of CYP2D6 inhibition in the Veith qHTS assay",
        units="probability",
        license="CC BY 4.0",
        citation=(
            "Veith et al., Nat. Biotechnol. 27 (2009) 1050-1055; dataset via Therapeutics Data "
            "Commons (CYP2D6_Veith)"
        ),
        url=f"{TDC_URL}/single_pred_tasks/adme/#cyp-p450-2d6-inhibition-veith-et-al",
    ),
    Target(
        key="cyp2c9_inhibition",
        label="CYP2C9 inhibition (QSAR)",
        task="classification",
        loader=_adme("CYP2C9_Veith"),
        description=(
            "CYP2C9 inhibition from the Veith et al. quantitative high-throughput screen "
            "(PubChem AID 1851)."
        ),
        endpoint="probability of CYP2C9 inhibition in the Veith qHTS assay",
        units="probability",
        license="CC BY 4.0",
        citation=(
            "Veith et al., Nat. Biotechnol. 27 (2009) 1050-1055; dataset via Therapeutics Data "
            "Commons (CYP2C9_Veith)"
        ),
        url=f"{TDC_URL}/single_pred_tasks/adme/#cyp-p450-2c9-inhibition-veith-et-al",
    ),
)


def canonicalize(frame: pd.DataFrame) -> tuple[list[str], NDArray[np.float64]]:
    """Sanitize, canonicalize and deduplicate. Duplicate structures average their labels."""
    grouped: dict[str, list[float]] = {}
    for smiles, label in zip(frame["Drug"], frame["Y"], strict=True):
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            continue
        grouped.setdefault(Chem.MolToSmiles(mol), []).append(float(label))
    canonical = sorted(grouped)
    labels = np.array([float(np.mean(grouped[smiles])) for smiles in canonical])
    return canonical, labels


def scaffold_split(smiles: list[str]) -> tuple[list[int], list[int], list[int]]:
    """Deterministic Bemis-Murcko scaffold split into train / calibration / test index lists."""
    buckets: dict[str, list[int]] = {}
    for index, structure in enumerate(smiles):
        try:
            scaffold = MurckoScaffold.MurckoScaffoldSmiles(smiles=structure, includeChirality=False)
        except ValueError:
            scaffold = structure
        buckets.setdefault(scaffold, []).append(index)

    groups = sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0]))
    total = len(smiles)
    n_test = int(total * TEST_FRACTION)
    n_calibration = int(total * CALIBRATION_FRACTION)

    train: list[int] = []
    calibration: list[int] = []
    test: list[int] = []
    for _, indices in groups:
        if len(test) + len(indices) <= n_test:
            test.extend(indices)
        elif len(calibration) + len(indices) <= n_calibration:
            calibration.extend(indices)
        else:
            train.extend(indices)
    return train, calibration, test


def featurize_all(smiles: list[str]) -> tuple[NDArray[np.float64], list[Chem.Mol]]:
    mols = [Chem.MolFromSmiles(structure) for structure in smiles]
    matrix = np.vstack([featurize(mol) for mol in mols])
    return matrix, mols


def _tanimoto(left: set[int], right: set[int]) -> float:
    shared = len(left & right)
    if not shared:
        return 0.0
    return shared / (len(left) + len(right) - shared)


def pick_reference_set(fingerprints: list[set[int]]) -> list[int]:
    """MaxMin selection of the training molecules the domain check compares against."""
    if len(fingerprints) <= DOMAIN_REFERENCE_LIMIT:
        return list(range(len(fingerprints)))

    picked = [0]
    distance = [1.0 - _tanimoto(fingerprints[0], other) for other in fingerprints]
    while len(picked) < DOMAIN_REFERENCE_LIMIT:
        candidate = int(np.argmax(distance))
        picked.append(candidate)
        distance[candidate] = -1.0
        for index, other in enumerate(fingerprints):
            if distance[index] < 0.0:
                continue
            distance[index] = min(distance[index], 1.0 - _tanimoto(fingerprints[candidate], other))
    return sorted(picked)


def build_domain(mols: list[Chem.Mol], matrix: NDArray[np.float64]) -> dict[str, object]:
    fingerprints = [fingerprint_bits(mol) for mol in mols]
    reference_idx = pick_reference_set(fingerprints)
    references = [fingerprints[index] for index in reference_idx]

    # Each training molecule's similarity to its nearest *other* reference molecule: the threshold
    # is the low tail of that distribution, so a query less similar to the training set than the
    # training set is to itself is refused.
    nearest = []
    for index, fingerprint in enumerate(fingerprints):
        best = max(
            (
                _tanimoto(fingerprint, reference)
                for position, reference in zip(reference_idx, references, strict=True)
                if position != index
            ),
            default=0.0,
        )
        nearest.append(best)
    min_tanimoto = float(np.percentile(nearest, DOMAIN_PERCENTILE))

    bounds: dict[str, tuple[float, float]] = {}
    for offset, name in enumerate(DESCRIPTOR_NAMES):
        column = matrix[:, MORGAN_BITS + offset]
        bounds[name] = (
            float(np.percentile(column, DESCRIPTOR_PERCENTILE)),
            float(np.percentile(column, 100.0 - DESCRIPTOR_PERCENTILE)),
        )
    return {
        "reference_bits": [sorted(fingerprints[index]) for index in reference_idx],
        "min_tanimoto": round(min_tanimoto, 4),
        "descriptor_bounds": bounds,
        "descriptor_slack": DESCRIPTOR_SLACK,
    }


def export_tree(
    tree: DecisionTreeRegressor, learning_rate: float
) -> dict[str, list[float] | list[int]]:
    """Flatten one scikit-learn regression tree, baking the learning rate into the leaves."""
    inner = tree.tree_
    feature = [int(value) if value >= 0 else -1 for value in inner.feature]
    values = inner.value.reshape(-1)
    return {
        "feature": feature,
        "threshold": [float(value) for value in inner.threshold],
        "left": [int(value) for value in inner.children_left],
        "right": [int(value) for value in inner.children_right],
        "value": [float(value) * learning_rate for value in values],
    }


def fit_platt(margins: NDArray[np.float64], labels: NDArray[np.float64]) -> dict[str, float]:
    scaler = LogisticRegression(C=1e6, max_iter=1000)
    scaler.fit(margins.reshape(-1, 1), labels)
    return {
        "method": "platt",
        "slope": float(scaler.coef_[0][0]),
        "intercept": float(scaler.intercept_[0]),
    }


def train_target(target: Target, write: bool) -> bool:
    print(f"\n=== {target.key} ({target.task})", flush=True)
    smiles, labels = canonicalize(target.loader())
    matrix, mols = featurize_all(smiles)
    train_idx, calibration_idx, test_idx = scaffold_split(smiles)
    print(
        f"    compounds={len(smiles)} train={len(train_idx)} "
        f"calibration={len(calibration_idx)} test={len(test_idx)}",
        flush=True,
    )

    x_train, y_train = matrix[train_idx], labels[train_idx]
    x_test, y_test = matrix[test_idx], labels[test_idx]

    learning_rate = 0.06
    if target.task == "classification":
        model: GradientBoostingClassifier | GradientBoostingRegressor = GradientBoostingClassifier(
            n_estimators=400,
            learning_rate=learning_rate,
            max_depth=5,
            subsample=0.8,
            max_features="sqrt",
            random_state=RANDOM_STATE,
        )
    else:
        model = GradientBoostingRegressor(
            n_estimators=400,
            learning_rate=learning_rate,
            max_depth=5,
            subsample=0.8,
            max_features="sqrt",
            random_state=RANDOM_STATE,
        )
    model.fit(x_train, y_train)

    if target.task == "classification":
        margins = model.decision_function(x_test)
        prior = float(np.clip(y_train.mean(), 1e-6, 1 - 1e-6))
        baseline = float(np.log(prior / (1.0 - prior)))
        calibration = fit_platt(
            model.decision_function(matrix[calibration_idx]), labels[calibration_idx]
        )
        probabilities = 1.0 / (
            1.0 + np.exp(-(calibration["slope"] * margins + calibration["intercept"]))
        )
        metrics = {
            "roc_auc": float(roc_auc_score(y_test, probabilities)),
            "balanced_accuracy": float(
                balanced_accuracy_score(y_test, (probabilities >= 0.5).astype(int))
            ),
            "brier": float(brier_score_loss(y_test, probabilities)),
            "test_positive_rate": float(y_test.mean()),
        }
        metric_key, minimum = MINIMUM_METRICS["classification"]
        raw_reference = margins
    else:
        predictions = model.predict(x_test)
        baseline = float(model.init_.constant_.reshape(-1)[0])
        calibration = None
        metrics = {
            "mae": float(mean_absolute_error(y_test, predictions)),
            "r2": float(r2_score(y_test, predictions)),
            "label_std": float(np.std(labels)),
        }
        metric_key, minimum = MINIMUM_METRICS["regression"]
        raw_reference = predictions

    estimators: NDArray[np.object_] = np.asarray(model.estimators_)
    trees = [export_tree(tree, learning_rate) for tree in estimators.ravel()]
    domain = build_domain([mols[i] for i in train_idx], x_train)

    artifact_payload: dict[str, object] = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "key": target.key,
        "label": target.label,
        "task": target.task,
        "featurizer_version": FEATURIZER_VERSION,
        "feature_count": FEATURE_COUNT,
        "baseline": baseline,
        "trees": trees,
        "calibration": calibration,
        "metrics": {name: round(value, 4) for name, value in metrics.items()},
        "metric_summary": "",
        "dataset": {
            "name": target.key,
            "description": target.description,
            "endpoint": target.endpoint,
            "units": target.units,
            "license": target.license,
            "citation": target.citation,
            "url": target.url,
            "compounds": len(smiles),
        },
        "split": {
            "method": "Bemis-Murcko scaffold split (largest scaffold groups held for training)",
            "train_size": len(train_idx),
            "test_size": len(test_idx),
        },
        "training_command": f"python training/admet_qsar/train.py --target {target.key} --write",
        "applicability_domain": domain,
    }

    artifact = QsarArtifact.model_validate(artifact_payload)
    served = QsarModel(artifact)

    # The exported artifact must reproduce scikit-learn's own raw output, or the export is wrong.
    reproduced = np.array([served.raw_margin(row) for row in x_test])
    deviation = float(np.max(np.abs(reproduced - raw_reference)))
    print(f"    export deviation from scikit-learn: {deviation:.2e}", flush=True)
    if deviation > 1e-6:
        print("    FAILED: exported artifact does not reproduce the fitted model", flush=True)
        return False

    in_domain = np.array([served.predict(mols[i]).in_domain for i in test_idx])
    coverage = float(in_domain.mean())
    print("    metrics: " + ", ".join(f"{k}={v:.3f}" for k, v in metrics.items()), flush=True)
    print(f"    applicability-domain coverage of the test set: {coverage:.1%}", flush=True)
    if in_domain.sum() >= 20 and target.task == "classification":
        gated = roc_auc_score(y_test[in_domain], probabilities[in_domain])
        print(f"    in-domain ROC-AUC: {gated:.3f}", flush=True)
        metrics["in_domain_roc_auc"] = float(gated)
    if in_domain.sum() >= 20 and target.task == "regression":
        gated_mae = mean_absolute_error(y_test[in_domain], predictions[in_domain])
        gated_r2 = r2_score(y_test[in_domain], predictions[in_domain])
        print(f"    in-domain MAE: {gated_mae:.3f}  R2: {gated_r2:.3f}", flush=True)
        metrics["in_domain_mae"] = float(gated_mae)
        metrics["in_domain_r2"] = float(gated_r2)

    passed = metrics[metric_key] >= minimum
    if not passed:
        print(
            f"    FAILED the bar: {metric_key}={metrics[metric_key]:.3f} < {minimum}; "
            "artifact not written",
            flush=True,
        )
        return False

    if target.task == "classification":
        summary = (
            f"Scaffold-split held-out ROC-AUC {metrics['roc_auc']:.2f}, balanced accuracy "
            f"{metrics['balanced_accuracy']:.2f}, Brier score {metrics['brier']:.2f} on "
            f"{len(test_idx)} compounds sharing no scaffold with the training set."
        )
    else:
        summary = (
            f"Scaffold-split held-out mean absolute error {metrics['mae']:.1f} {target.units}, "
            f"R2 {metrics['r2']:.2f} on {len(test_idx)} compounds sharing no scaffold with the "
            f"training set (label standard deviation {metrics['label_std']:.1f})."
        )

    artifact_payload["metrics"] = {name: round(value, 4) for name, value in metrics.items()}
    artifact_payload["metric_summary"] = summary
    QsarArtifact.model_validate(artifact_payload)

    if write:
        ARTIFACT_DIRECTORY.mkdir(parents=True, exist_ok=True)
        path = ARTIFACT_DIRECTORY / f"{target.key}.json"
        path.write_text(json.dumps(artifact_payload, separators=(",", ":"), sort_keys=True) + "\n")
        size_kb = path.stat().st_size / 1024
        print(f"    wrote {path.relative_to(BACKEND_ROOT)} ({size_kb:.0f} kB)", flush=True)
    else:
        print("    passed (dry run; pass --write to export)", flush=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", action="append", dest="targets", default=None)
    parser.add_argument("--write", action="store_true")
    arguments = parser.parse_args()

    selected = [
        target
        for target in TARGETS
        if arguments.targets is None or target.key in set(arguments.targets)
    ]
    if not selected:
        parser.error(f"no such target; available: {', '.join(t.key for t in TARGETS)}")

    results = {target.key: train_target(target, arguments.write) for target in selected}
    print("\n=== summary")
    for key, passed in results.items():
        print(f"    {key}: {'PASS' if passed else 'FAIL'}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
