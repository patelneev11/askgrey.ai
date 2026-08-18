"""
The molecular representation the trained QSAR models consume.

Shared by the training pipeline (`backend/training/admet_qsar/`) and by inference so that a model
can never be fed a vector built differently from the one it was fitted on: the training script
imports this module rather than reimplementing it, and every artifact records the featurizer
parameters it was built with, which `qsar.py` checks on load.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, rdFingerprintGenerator, rdMolDescriptors

# Morgan (ECFP4-equivalent) count fingerprint, folded. Counts are capped so that a polymer-like
# repeat cannot dominate a split learnt on drug-like counts.
MORGAN_RADIUS = 2
MORGAN_BITS = 2048
COUNT_CAP = 4

_MORGAN = rdFingerprintGenerator.GetMorganGenerator(radius=MORGAN_RADIUS, fpSize=MORGAN_BITS)

# Whole-molecule descriptors appended after the fingerprint block. Order is part of the artifact
# contract: appending is safe, reordering or removing invalidates every existing artifact.
DESCRIPTOR_FUNCTIONS: tuple[tuple[str, Callable[[Chem.Mol], float]], ...] = (
    ("molecular_weight", lambda mol: float(Descriptors.MolWt(mol))),
    ("clogp", lambda mol: float(Crippen.MolLogP(mol))),
    ("tpsa", lambda mol: float(Descriptors.TPSA(mol))),
    ("hbd", lambda mol: float(Lipinski.NumHDonors(mol))),
    ("hba", lambda mol: float(Lipinski.NumHAcceptors(mol))),
    ("rotatable_bonds", lambda mol: float(Lipinski.NumRotatableBonds(mol))),
    ("rings", lambda mol: float(rdMolDescriptors.CalcNumRings(mol))),
    ("aromatic_rings", lambda mol: float(rdMolDescriptors.CalcNumAromaticRings(mol))),
    ("heavy_atoms", lambda mol: float(mol.GetNumHeavyAtoms())),
    ("fraction_csp3", lambda mol: float(rdMolDescriptors.CalcFractionCSP3(mol))),
    ("molar_refractivity", lambda mol: float(Crippen.MolMR(mol))),
    ("formal_charge", lambda mol: float(Chem.GetFormalCharge(mol))),
)

DESCRIPTOR_NAMES: tuple[str, ...] = tuple(name for name, _ in DESCRIPTOR_FUNCTIONS)
FEATURE_COUNT = MORGAN_BITS + len(DESCRIPTOR_FUNCTIONS)
FEATURIZER_VERSION = "morgan2-2048-count4+desc12"


def featurize(mol: Chem.Mol) -> NDArray[np.float64]:
    """Build the feature vector for one sanitized molecule. Deterministic and network-free."""
    vector = np.zeros(FEATURE_COUNT, dtype=np.float64)
    for bit, count in _MORGAN.GetCountFingerprint(mol).GetNonzeroElements().items():
        vector[bit] = min(count, COUNT_CAP)
    for offset, (_, function) in enumerate(DESCRIPTOR_FUNCTIONS):
        vector[MORGAN_BITS + offset] = function(mol)
    return vector


def fingerprint_bits(mol: Chem.Mol) -> set[int]:
    """The Morgan bits switched on for one molecule, used by the applicability-domain check."""
    return set(_MORGAN.GetCountFingerprint(mol).GetNonzeroElements())
