"""The ADMET service: validate a structure, then apply the published rules and trained models."""

from __future__ import annotations

from ..smiles import parse_structure
from .alerts import evaluate_alerts
from .models import AdmetProfile
from .qsar_presentation import qsar_estimates
from .rules import (
    Descriptors2D,
    bbb_penetration,
    cyp_isoforms_not_modelled,
    cyp_structural_alerts,
    general_toxicity_risk,
    gi_absorption,
    herg_liability,
)

# Alerts tied to P450 bioactivation; the hERG pharmacophore alert is surfaced through the hERG
# estimate instead, so it is excluded from the CYP flag summary.
_HERG_ALERT_KEY = "basic_amine_aromatic"


class AdmetService:
    """
    Deterministic ADMET estimation from published physicochemical rules and trained QSAR models.

    No LLM and no network: the rules are published thresholds over RDKit descriptors and the QSAR
    models are gradient-boosted trees loaded from package data, so the same structure always yields
    the same profile. Properties with neither a defensible rule nor a model inside its applicability
    domain come back as unavailable estimates rather than numbers.
    """

    def evaluate(self, smiles: object) -> AdmetProfile:
        """
        Profile `smiles`.

        Raises `InvalidStructureError` for anything RDKit cannot sanitize; see `..smiles`.
        """
        structure = parse_structure(smiles)
        values = Descriptors2D(structure.mol)
        alerts = evaluate_alerts(structure.mol)
        cyp_matches = [
            alert.label for alert in alerts if alert.matched and alert.key != _HERG_ALERT_KEY
        ]

        return AdmetProfile(
            canonical_smiles=structure.canonical_smiles,
            molecular_formula=structure.molecular_formula,
            estimates=[
                gi_absorption(values),
                bbb_penetration(values),
                herg_liability(values),
                cyp_structural_alerts(values, cyp_matches),
                general_toxicity_risk(values),
                *qsar_estimates(structure.mol),
                cyp_isoforms_not_modelled(),
            ],
            alerts=alerts,
        )
