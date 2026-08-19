from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# The strongest caveat in the screening tab, and the reason this module exists in the shape it
# does: every estimate below is either a classification from a published physicochemical rule or
# the output of a QSAR model fitted to public assay data — never a measurement of this compound.
ADMET_CAVEAT = (
    "Predicted ADMET properties, from two bases the fields keep separate: published "
    "physicochemical rules applied to computed descriptors, and QSAR models trained on public "
    "assay data and validated on compounds sharing no scaffold with their training sets. Nothing "
    "here is measured on this compound; a model probability is an estimate carrying the held-out "
    "error its field quotes, and a property is returned as unavailable rather than guessed when "
    "the structure falls outside a model's applicability domain. Confirm experimentally "
    "(Caco-2/PAMPA, microsomal, hERG patch clamp, plasma binding) before any series or candidate "
    "decision."
)

ALERT_CAVEAT = (
    "Structural alerts are substructure matches to groups reported in the literature as liability "
    "motifs. A match is a prompt to look, not a prediction that this compound has the liability; "
    "no match is not evidence of safety."
)


class Outcome(str, Enum):
    """
    The coarse direction of a rule's verdict, for colouring the UI.

    Deliberately three-valued and coarse: the underlying rules are classifications with published
    error rates, and a finer scale would imply precision the rules do not have. `UNAVAILABLE` is a
    first-class outcome, not an error.
    """

    FAVOURABLE = "favourable"
    BORDERLINE = "borderline"
    UNFAVOURABLE = "unfavourable"
    UNAVAILABLE = "unavailable"


class RuleInput(BaseModel):
    """One descriptor a rule consumed, and how it compared to the rule's threshold."""

    label: str
    value_display: str
    threshold: str
    within: bool


class AdmetEstimate(BaseModel):
    """
    One ADMET property: its verdict, or an explicit statement that it is unavailable.

    `model_basis` is required and non-empty for every estimate, available or not — for an
    available estimate it names the published rule and the descriptors used; for an unavailable
    one it names what would be needed to produce it. It is a schema field rather than metadata
    because the UI is required to display it next to the value.
    """

    key: str
    label: str
    available: bool
    outcome: Outcome
    # Prose classification, e.g. "Within the Egan well-absorbed region". Empty when unavailable.
    verdict: str = ""
    # What the classification does *not* say, e.g. "does not estimate fraction absorbed".
    scope: str = ""
    model_basis: str = Field(min_length=1)
    citation: str = ""
    inputs: list[RuleInput] = Field(default_factory=list)
    # Populated only when `available` is False: why, and what it would take.
    reason: str = ""
    requires: str = ""
    predicted: bool = True


class StructuralAlert(BaseModel):
    """A substructure match to a documented liability motif."""

    key: str
    label: str
    concern: str
    citation: str
    matched: bool


class AdmetProfile(BaseModel):
    """Every ADMET estimate for one structure, plus the alerts and the tab-level caveat."""

    canonical_smiles: str
    molecular_formula: str
    estimates: list[AdmetEstimate] = Field(default_factory=list)
    alerts: list[StructuralAlert] = Field(default_factory=list)
    caveat: str = ADMET_CAVEAT
    alert_caveat: str = ALERT_CAVEAT

    def estimate(self, key: str) -> AdmetEstimate | None:
        for estimate in self.estimates:
            if estimate.key == key:
                return estimate
        return None

    def alert(self, key: str) -> StructuralAlert | None:
        for alert in self.alerts:
            if alert.key == key:
                return alert
        return None

    @property
    def matched_alerts(self) -> list[StructuralAlert]:
        return [alert for alert in self.alerts if alert.matched]
