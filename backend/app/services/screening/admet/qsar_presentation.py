"""
Presentation of the trained QSAR predictions as ADMET estimates.

Three rules govern everything here:

* A prediction is reported as a model output, never as a measurement. The verdict carries the
  calibrated probability (or the predicted value with its held-out error), and `model_basis`
  carries the algorithm, the training set, its licence and the scaffold-split metrics.
* Out of the applicability domain, no number is shown. The estimate degrades to `unavailable` with
  the reason spelling out how much of the structure the training set had never seen.
* A missing or incompatible artifact degrades the same way rather than failing the request: the
  rest of the profile is still useful, and a silent fallback to a rule would misattribute the
  basis.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rdkit import Chem

from .models import AdmetEstimate, Outcome, RuleInput
from .qsar import (
    ARTIFACT_DIRECTORY,
    PEPTIDE_MARKER,
    QsarArtifact,
    QsarArtifactError,
    QsarModel,
    load_models,
)

logger = logging.getLogger(__name__)

# Calibrated-probability bands. Coarse on purpose: the classifiers' Brier scores support "likely /
# uncertain / unlikely", not a two-decimal risk figure.
LIKELY_THRESHOLD = 0.70
UNLIKELY_THRESHOLD = 0.30

# Plasma protein binding bands, in % bound. Above 99% a 1% shift in bound fraction halves or
# doubles the free concentration, which is the regime the value is worth acting on.
VERY_HIGH_BINDING = 99.0
HIGH_BINDING = 95.0


@dataclass(frozen=True)
class _Presentation:
    """The wording for one model: what a positive call means, and what the model cannot say."""

    key: str
    label: str
    likely: str
    uncertain: str
    unlikely: str
    # What would settle the question experimentally, quoted when the model declines to answer.
    measurement: str
    scope: str


_CYP_SCOPE = (
    "A probability of inhibition in one high-throughput assay against one isoform, not a Ki, an "
    "IC50 or a clinical drug-drug interaction prediction. The training assay measures reversible "
    "inhibition of a recombinant enzyme; time-dependent inactivation, induction, transporter "
    "effects and the dose the compound will actually be given at are all outside it."
)

PRESENTATIONS: tuple[_Presentation, ...] = (
    _Presentation(
        key="herg_blockade",
        label="hERG blockade (QSAR)",
        measurement="a hERG patch-clamp or automated electrophysiology measurement",
        likely="Predicted hERG blocker",
        uncertain="Uncertain hERG blockade call",
        unlikely="Predicted hERG non-blocker",
        scope=(
            "A probability that the compound blocks hERG at IC50 < 10 uM in the assays behind the "
            "training set — not an IC50, not a percentage block and not a QT-prolongation "
            "prediction. It supersedes nothing: only a patch-clamp measurement clears a compound, "
            "and the pharmacophore flag in this profile is reported separately so the two bases "
            "stay distinguishable."
        ),
    ),
    _Presentation(
        key="plasma_protein_binding",
        label="Plasma protein binding (QSAR)",
        measurement="an equilibrium-dialysis or ultrafiltration plasma-binding measurement",
        likely="Predicted very high plasma protein binding",
        uncertain="Predicted high plasma protein binding",
        unlikely="Predicted moderate plasma protein binding",
        scope=(
            "A predicted percentage bound in human plasma with a held-out error of several "
            "percent, which is too coarse to derive a free concentration from when binding is "
            "above 99%. It is not species-specific beyond human plasma, does not resolve albumin "
            "from AGP binding, and says nothing about tissue binding or how the free fraction "
            "shifts with disease state or concentration."
        ),
    ),
    _Presentation(
        key="cyp3a4_inhibition",
        label="CYP3A4 inhibition (QSAR)",
        measurement="a recombinant CYP3A4 or human liver microsome inhibition assay",
        likely="Predicted CYP3A4 inhibitor",
        uncertain="Uncertain CYP3A4 inhibition call",
        unlikely="Predicted CYP3A4 non-inhibitor",
        scope=_CYP_SCOPE,
    ),
    _Presentation(
        key="cyp2d6_inhibition",
        label="CYP2D6 inhibition (QSAR)",
        measurement="a recombinant CYP2D6 or human liver microsome inhibition assay",
        likely="Predicted CYP2D6 inhibitor",
        uncertain="Uncertain CYP2D6 inhibition call",
        unlikely="Predicted CYP2D6 non-inhibitor",
        scope=_CYP_SCOPE,
    ),
    _Presentation(
        key="cyp2c9_inhibition",
        label="CYP2C9 inhibition (QSAR)",
        measurement="a recombinant CYP2C9 or human liver microsome inhibition assay",
        likely="Predicted CYP2C9 inhibitor",
        uncertain="Uncertain CYP2C9 inhibition call",
        unlikely="Predicted CYP2C9 non-inhibitor",
        scope=_CYP_SCOPE,
    ),
)

QSAR_KEYS: tuple[str, ...] = tuple(presentation.key for presentation in PRESENTATIONS)
_BY_KEY = {presentation.key: presentation for presentation in PRESENTATIONS}


def _model_basis(artifact: QsarArtifact) -> str:
    calibration = (
        "Probabilities are Platt-scaled on a held-out scaffold slice. "
        if artifact.task == "classification"
        else ""
    )
    return (
        "Gradient-boosted decision trees over Morgan count fingerprints (radius 2, 2048 bits) and "
        f"12 RDKit descriptors, fitted to {artifact.dataset.description} "
        f"({artifact.dataset.compounds} compounds, {artifact.dataset.license}). "
        f"{artifact.metric_summary} {calibration}"
        "A fitted model, not a published rule and not a measurement."
    )


def _domain_input(model: QsarModel, similarity: float) -> RuleInput:
    minimum = model.artifact.applicability_domain.min_tanimoto
    return RuleInput(
        label="Applicability domain",
        value_display=f"Tanimoto {similarity:.2f} to the nearest training compound",
        threshold=f">= {minimum:.2f}",
        within=similarity >= minimum,
    )


def _unavailable(
    key: str,
    label: str,
    model_basis: str,
    reason: str,
    requires: str,
) -> AdmetEstimate:
    return AdmetEstimate(
        key=key,
        label=label,
        available=False,
        outcome=Outcome.UNAVAILABLE,
        model_basis=model_basis,
        reason=reason,
        requires=requires,
        predicted=False,
    )


def _out_of_domain(
    model: QsarModel,
    presentation: _Presentation,
    similarity: float,
    descriptors: list[str],
) -> AdmetEstimate:
    artifact = model.artifact
    minimum = artifact.applicability_domain.min_tanimoto
    details = []
    if similarity < minimum:
        details.append(
            f"its nearest training compound is only {similarity:.2f} Tanimoto away "
            f"(the model requires {minimum:.2f})"
        )
    if PEPTIDE_MARKER in descriptors:
        allowed = artifact.applicability_domain.max_peptide_linkages
        details.append(
            "it carries more peptide backbone linkages than the training set contained "
            f"(at most {allowed}), and a chain of amino acids is not the small-molecule chemistry "
            "this model was fitted on"
        )
    out_of_range = [name for name in descriptors if name != PEPTIDE_MARKER]
    if out_of_range:
        details.append("its " + ", ".join(out_of_range) + " fall outside the training range")
    return _unavailable(
        key=artifact.key,
        label=artifact.label,
        model_basis=_model_basis(artifact),
        reason=(
            "Unavailable for this structure: it is outside the model's applicability domain — "
            + " and ".join(details)
            + ". A boosted tree still returns a confident number there, so the prediction is "
            "withheld instead."
        ),
        requires=(
            f"{presentation.measurement[0].upper()}{presentation.measurement[1:]}, or a model "
            "whose training set covers this chemistry."
        ),
    )


def _missing_artifact(key: str) -> AdmetEstimate:
    presentation = _BY_KEY[key]
    return _unavailable(
        key=key,
        label=presentation.label,
        model_basis=(
            "No estimate is produced: the trained model artifact for this property is not present "
            "in this build, so nothing was evaluated."
        ),
        reason=(
            "Unavailable in this deployment. The QSAR artifact could not be loaded, and no rule is "
            "substituted for it — a value from a different basis would be mislabelled."
        ),
        requires=(
            "The artifact rebuilt and shipped with the package "
            "(backend/training/admet_qsar/train.py), or "
            f"{presentation.measurement}."
        ),
    )


def _classification_estimate(
    model: QsarModel, presentation: _Presentation, probability: float, similarity: float
) -> AdmetEstimate:
    artifact = model.artifact
    if probability >= LIKELY_THRESHOLD:
        outcome = Outcome.UNFAVOURABLE
        verdict = f"{presentation.likely} (calibrated probability {probability:.2f})"
    elif probability <= UNLIKELY_THRESHOLD:
        outcome = Outcome.FAVOURABLE
        verdict = f"{presentation.unlikely} (calibrated probability {probability:.2f})"
    else:
        outcome = Outcome.BORDERLINE
        verdict = f"{presentation.uncertain} (calibrated probability {probability:.2f})"

    return AdmetEstimate(
        key=artifact.key,
        label=artifact.label,
        available=True,
        outcome=outcome,
        verdict=verdict,
        scope=presentation.scope,
        model_basis=_model_basis(artifact),
        citation=artifact.dataset.citation,
        inputs=[
            RuleInput(
                label="Calibrated probability",
                value_display=f"{probability:.2f}",
                threshold=(
                    f"<= {UNLIKELY_THRESHOLD:.2f} unlikely, >= {LIKELY_THRESHOLD:.2f} likely"
                ),
                within=probability <= UNLIKELY_THRESHOLD,
            ),
            _domain_input(model, similarity),
        ],
    )


def _regression_estimate(
    model: QsarModel, presentation: _Presentation, value: float, similarity: float
) -> AdmetEstimate:
    artifact = model.artifact
    error = artifact.metrics.get("mae", 0.0)
    if value >= VERY_HIGH_BINDING:
        outcome = Outcome.UNFAVOURABLE
        headline = presentation.likely
    elif value >= HIGH_BINDING:
        outcome = Outcome.BORDERLINE
        headline = presentation.uncertain
    else:
        outcome = Outcome.FAVOURABLE
        headline = presentation.unlikely

    return AdmetEstimate(
        key=artifact.key,
        label=artifact.label,
        available=True,
        outcome=outcome,
        verdict=(
            f"{headline}: {value:.1f} {artifact.dataset.units} +/- {error:.1f} "
            "(held-out mean absolute error)"
        ),
        scope=presentation.scope,
        model_basis=_model_basis(artifact),
        citation=artifact.dataset.citation,
        inputs=[
            RuleInput(
                label="Predicted fraction bound",
                value_display=f"{value:.1f} {artifact.dataset.units}",
                threshold=(
                    f"< {HIGH_BINDING:.0f}% moderate, >= {VERY_HIGH_BINDING:.0f}% very high"
                ),
                within=value < HIGH_BINDING,
            ),
            _domain_input(model, similarity),
        ],
    )


def qsar_estimates(mol: Chem.Mol) -> list[AdmetEstimate]:
    """
    Evaluate every trained model for one structure, in the order `PRESENTATIONS` declares.

    Never raises: a load failure or an out-of-domain structure becomes an unavailable estimate.
    """
    try:
        models = load_models()
    except QsarArtifactError:
        logger.exception("admet qsar artifacts unavailable dir=%s", ARTIFACT_DIRECTORY.name)
        return [_missing_artifact(key) for key in QSAR_KEYS]

    estimates: list[AdmetEstimate] = []
    for presentation in PRESENTATIONS:
        model = models.get(presentation.key)
        if model is None:
            estimates.append(_missing_artifact(presentation.key))
            continue

        prediction = model.predict(mol)
        if not prediction.in_domain:
            estimates.append(
                _out_of_domain(
                    model,
                    presentation,
                    prediction.nearest_training_similarity,
                    prediction.out_of_domain_descriptors,
                )
            )
        elif prediction.probability is not None:
            estimates.append(
                _classification_estimate(
                    model,
                    presentation,
                    prediction.probability,
                    prediction.nearest_training_similarity,
                )
            )
        elif prediction.value is not None:
            estimates.append(
                _regression_estimate(
                    model, presentation, prediction.value, prediction.nearest_training_similarity
                )
            )
        else:  # pragma: no cover - a model returns one or the other by construction
            estimates.append(_missing_artifact(presentation.key))
    return estimates
