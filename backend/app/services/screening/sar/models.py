from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# One sentence, carried in the payload rather than left to the frontend, so the caveat cannot be
# lost by a client that forgets to add it. The descriptor caveat is deliberately weaker than the
# ADMET one: these values are deterministic calculations, not predictions of behaviour.
DESCRIPTOR_CAVEAT = (
    "Computed descriptors from the 2D structure (RDKit). Deterministic calculations, not "
    "measured physicochemical values — confirm experimentally where a decision depends on them."
)
SUGGESTION_CAVEAT = (
    "Unvalidated heuristic suggestions, not predictions of activity or a synthesis route. "
    "Requires medicinal-chemist review before any compound is made or a series is progressed."
)


class Descriptor(BaseModel):
    """One computed molecular descriptor, carrying the function that produced it."""

    key: str
    label: str
    value: float
    # Pre-rounded for display, so the API and the UI cannot disagree about precision.
    display: str
    unit: str = ""
    # e.g. "RDKit Descriptors.MolWt" — what a reviewer needs to reproduce the number.
    method: str


class RuleCheck(BaseModel):
    """One threshold inside a rule set, and whether this structure meets it."""

    key: str
    label: str
    value_display: str
    limit: str
    passed: bool


class RuleSet(BaseModel):
    """
    A published set of physicochemical thresholds evaluated against the structure.

    Rule sets are guidelines for oral drug-likeness, not pass/fail gates: `compliant` means the
    structure meets every threshold in this set, nothing more.
    """

    key: str
    name: str
    citation: str
    description: str
    compliant: bool
    violations: int
    checks: list[RuleCheck] = Field(default_factory=list)


class UnavailableProperty(BaseModel):
    """
    A property this service refuses to estimate, and what it would take to produce it.

    Modelled explicitly rather than omitted: a missing key reads as an oversight, while an
    entry saying binding affinity needs a target structure and a docking pipeline is the
    honest answer, and the frontend can render it.
    """

    key: str
    label: str
    available: bool = False
    reason: str
    requires: str


class SuggestionSource(str, Enum):
    """Which suggester produced a substituent suggestion set."""

    LLM = "llm"
    RULES = "rules"


class SubstituentSuggestion(BaseModel):
    """
    One proposed structural modification, with the reasoning offered for it.

    Nothing here is validated: `expected_effect` is a medicinal-chemistry expectation, not a
    prediction from a model fitted to data, and `risk` is what the reviewer should look for.
    """

    title: str
    site: str
    transformation: str
    rationale: str
    expected_effect: str
    risk: str = ""


class SuggestionSet(BaseModel):
    """Substituent suggestions for one structure, labelled with what generated them."""

    canonical_smiles: str
    source: SuggestionSource
    # Model id for `source="llm"`, empty for the deterministic rule-based suggester.
    model: str = ""
    generator: str
    suggestions: list[SubstituentSuggestion] = Field(default_factory=list)
    caveat: str = SUGGESTION_CAVEAT
    validated: bool = False


class DescriptorProfile(BaseModel):
    """The deterministic half of the SAR view: identity, descriptors and rule-set outcomes."""

    input_smiles: str
    canonical_smiles: str
    molecular_formula: str
    inchikey: str = ""
    heavy_atom_count: int
    descriptors: list[Descriptor] = Field(default_factory=list)
    rule_sets: list[RuleSet] = Field(default_factory=list)
    unavailable: list[UnavailableProperty] = Field(default_factory=list)
    basis: str
    caveat: str = DESCRIPTOR_CAVEAT

    def descriptor(self, key: str) -> Descriptor | None:
        for descriptor in self.descriptors:
            if descriptor.key == key:
                return descriptor
        return None

    def value_of(self, key: str) -> float | None:
        descriptor = self.descriptor(key)
        return None if descriptor is None else descriptor.value
