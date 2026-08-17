"""
Deterministic 2D molecular descriptors and published drug-likeness rule sets.

Everything in this module is a calculation on the graph of the molecule: the same SMILES always
produces the same numbers, and no model, fit or LLM is involved. That is why the descriptor
payload carries a "computational descriptor" framing rather than the stronger unvalidated-
prediction caveat the ADMET estimates need.

Deliberately absent: binding affinity. A descriptor set cannot produce one — affinity depends on
the target's structure and a scoring function — so it is reported as unavailable, with what it
would take to produce it, instead of being regressed out of LogP and molecular weight.
"""

from __future__ import annotations

from collections.abc import Callable

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors

from ..smiles import ParsedStructure, parse_structure
from .models import (
    Descriptor,
    DescriptorProfile,
    RuleCheck,
    RuleSet,
    UnavailableProperty,
)

BASIS = (
    "RDKit 2D descriptors computed from the submitted structure "
    "(Descriptors/Crippen/Lipinski modules); no model inference involved."
)


class DescriptorSpec:
    """How one descriptor is computed, labelled and displayed."""

    def __init__(
        self,
        key: str,
        label: str,
        compute: Callable[[Chem.Mol], float],
        method: str,
        *,
        unit: str = "",
        decimals: int = 2,
    ) -> None:
        self.key = key
        self.label = label
        self.compute = compute
        self.method = method
        self.unit = unit
        self.decimals = decimals

    def evaluate(self, mol: Chem.Mol) -> Descriptor:
        value = float(self.compute(mol))
        display = f"{value:.{self.decimals}f}" if self.decimals else f"{value:.0f}"
        return Descriptor(
            key=self.key,
            label=self.label,
            value=round(value, self.decimals) if self.decimals else value,
            display=f"{display} {self.unit}".strip(),
            unit=self.unit,
            method=self.method,
        )


DESCRIPTOR_SPECS: tuple[DescriptorSpec, ...] = (
    DescriptorSpec(
        "molecular_weight",
        "Molecular weight",
        Descriptors.MolWt,
        "RDKit Descriptors.MolWt (average atomic masses)",
        unit="g/mol",
    ),
    DescriptorSpec(
        "logp",
        "cLogP",
        Crippen.MolLogP,
        "RDKit Crippen.MolLogP (Wildman-Crippen atom contributions)",
    ),
    DescriptorSpec(
        "tpsa",
        "TPSA",
        Descriptors.TPSA,
        "RDKit Descriptors.TPSA (Ertl polar surface area)",
        unit="A^2",
        decimals=1,
    ),
    DescriptorSpec(
        "hbd",
        "H-bond donors",
        Lipinski.NumHDonors,
        "RDKit Lipinski.NumHDonors",
        decimals=0,
    ),
    DescriptorSpec(
        "hba",
        "H-bond acceptors",
        Lipinski.NumHAcceptors,
        "RDKit Lipinski.NumHAcceptors",
        decimals=0,
    ),
    DescriptorSpec(
        "rotatable_bonds",
        "Rotatable bonds",
        Lipinski.NumRotatableBonds,
        "RDKit Lipinski.NumRotatableBonds",
        decimals=0,
    ),
    DescriptorSpec(
        "aromatic_rings",
        "Aromatic rings",
        lambda mol: rdMolDescriptors.CalcNumAromaticRings(mol),
        "RDKit rdMolDescriptors.CalcNumAromaticRings",
        decimals=0,
    ),
    DescriptorSpec(
        "heavy_atoms",
        "Heavy atoms",
        lambda mol: mol.GetNumHeavyAtoms(),
        "RDKit Mol.GetNumHeavyAtoms",
        decimals=0,
    ),
    DescriptorSpec(
        "molar_refractivity",
        "Molar refractivity",
        Crippen.MolMR,
        "RDKit Crippen.MolMR (Wildman-Crippen)",
        decimals=1,
    ),
    DescriptorSpec(
        "fraction_csp3",
        "Fraction Csp3",
        rdMolDescriptors.CalcFractionCSP3,
        "RDKit rdMolDescriptors.CalcFractionCSP3",
    ),
)

LIPINSKI_CITATION = "Lipinski et al., Adv. Drug Deliv. Rev. 46 (2001) 3-26 (Rule of Five)"
VEBER_CITATION = "Veber et al., J. Med. Chem. 45 (2002) 2615-2623"

BINDING_AFFINITY_UNAVAILABLE = UnavailableProperty(
    key="binding_affinity",
    label="Binding affinity (pKi / Kd)",
    reason=(
        "Not available without a target structure and a docking or free-energy pipeline. "
        "Affinity cannot be derived from 2D descriptors, and this service will not publish a "
        "number it cannot ground."
    ),
    requires=(
        "A validated target structure (or homology model) plus a docking/scoring pipeline, "
        "or measured assay data for the series."
    ),
)


def _lipinski_rule_set(values: dict[str, Descriptor]) -> RuleSet:
    checks = [
        _check("molecular_weight", values, "MW <= 500 g/mol", lambda value: value <= 500),
        _check("logp", values, "cLogP <= 5", lambda value: value <= 5),
        _check("hbd", values, "donors <= 5", lambda value: value <= 5),
        _check("hba", values, "acceptors <= 10", lambda value: value <= 10),
    ]
    violations = sum(1 for check in checks if not check.passed)
    return RuleSet(
        key="lipinski",
        name="Lipinski's Rule of Five",
        citation=LIPINSKI_CITATION,
        description=(
            "Oral drug-likeness guideline. Lipinski treats two or more violations as the "
            "signal, so one violation is common among marketed oral drugs."
        ),
        compliant=violations == 0,
        violations=violations,
        checks=checks,
    )


def _veber_rule_set(values: dict[str, Descriptor]) -> RuleSet:
    checks = [
        _check("rotatable_bonds", values, "rotatable bonds <= 10", lambda value: value <= 10),
        _check("tpsa", values, "TPSA <= 140 A^2", lambda value: value <= 140),
    ]
    violations = sum(1 for check in checks if not check.passed)
    return RuleSet(
        key="veber",
        name="Veber criteria",
        citation=VEBER_CITATION,
        description=(
            "Oral bioavailability guideline from rat data: flexibility and polar surface area "
            "predicted permeability better than molecular weight alone."
        ),
        compliant=violations == 0,
        violations=violations,
        checks=checks,
    )


def _check(
    key: str,
    values: dict[str, Descriptor],
    limit: str,
    passes: Callable[[float], bool],
) -> RuleCheck:
    descriptor = values[key]
    return RuleCheck(
        key=key,
        label=descriptor.label,
        value_display=descriptor.display,
        limit=limit,
        passed=passes(descriptor.value),
    )


def compute_descriptors(mol: Chem.Mol) -> list[Descriptor]:
    """Every descriptor in `DESCRIPTOR_SPECS`, in declaration order."""
    return [spec.evaluate(mol) for spec in DESCRIPTOR_SPECS]


def profile_structure(smiles: object) -> DescriptorProfile:
    """
    Validate `smiles` and return its descriptor profile.

    Raises `InvalidStructureError` for anything RDKit cannot sanitize; see `..smiles`.
    """
    structure: ParsedStructure = parse_structure(smiles)
    descriptors = compute_descriptors(structure.mol)
    by_key = {descriptor.key: descriptor for descriptor in descriptors}

    return DescriptorProfile(
        input_smiles=structure.input_smiles,
        canonical_smiles=structure.canonical_smiles,
        molecular_formula=structure.molecular_formula,
        inchikey=structure.inchikey,
        heavy_atom_count=structure.heavy_atom_count,
        descriptors=descriptors,
        rule_sets=[_lipinski_rule_set(by_key), _veber_rule_set(by_key)],
        unavailable=[BINDING_AFFINITY_UNAVAILABLE],
        basis=BASIS,
    )
