"""The ADMET service: validate a structure, then apply every published rule to it."""

from __future__ import annotations

from ..smiles import parse_structure
from .alerts import evaluate_alerts
from .models import AdmetProfile
from .rules import (
    Descriptors2D,
    bbb_penetration,
    cyp_inhibition_unavailable,
    cyp_structural_alerts,
    general_toxicity_risk,
    gi_absorption,
    herg_liability,
    plasma_protein_binding,
)

# Alerts tied to P450 bioactivation; the hERG pharmacophore alert is surfaced through the hERG
# estimate instead, so it is excluded from the CYP flag summary.
_HERG_ALERT_KEY = "basic_amine_aromatic"


class AdmetService:
    """
    Deterministic ADMET estimation from published physicochemical rules.

    No LLM and no network: the same structure always yields the same profile. Properties without a
    defensible open approach come back as unavailable estimates rather than numbers.
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
                cyp_inhibition_unavailable(),
                plasma_protein_binding(),
                general_toxicity_risk(values),
            ],
            alerts=alerts,
        )
