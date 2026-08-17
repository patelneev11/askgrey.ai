"""
Reference compounds for the descriptor tests.

`pubchem_*` values are PubChem's own computed properties, read from PUG-REST
(`/compound/name/<name>/property/...`) on 2026-08-16. They are the external reference: if a
change to this repo's descriptor code moves molecular weight, TPSA, donor count or aromatic ring
count away from them, the change is wrong.

`rdkit_*` values are what this repo's descriptor stack produces where its definition genuinely
differs from PubChem's. Those are regression locks, not independent references, and each one
records why the two disagree — asserting agreement where none exists would be the dishonest
option, and silently dropping the property would hide a real definitional difference from anyone
reading a Lipinski verdict.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceCompound:
    name: str
    smiles: str
    formula: str
    pubchem_mw: float
    pubchem_tpsa: float
    pubchem_hbd: int
    pubchem_hba: int
    pubchem_rotatable_bonds: int
    pubchem_xlogp3: float
    aromatic_rings: int
    # Present only where RDKit's definition differs from PubChem's, with the reason.
    rdkit_tpsa: float | None = None
    rdkit_hba: int | None = None
    rdkit_rotatable_bonds: int | None = None
    divergence: str = ""


# Ten well-characterized compounds spanning the descriptor space: a fragment (benzene), a
# polar base (metformin), classic small orals (aspirin, paracetamol, ibuprofen, caffeine,
# diazepam), a rigid polycycle (morphine), a Rule-of-Five breaker (atorvastatin) and a
# kinase inhibitor (imatinib).
REFERENCE_COMPOUNDS: tuple[ReferenceCompound, ...] = (
    ReferenceCompound(
        name="aspirin",
        smiles="CC(=O)OC1=CC=CC=C1C(=O)O",
        formula="C9H8O4",
        pubchem_mw=180.16,
        pubchem_tpsa=63.6,
        pubchem_hbd=1,
        pubchem_hba=4,
        pubchem_rotatable_bonds=3,
        pubchem_xlogp3=1.2,
        aromatic_rings=1,
        rdkit_hba=3,
        rdkit_rotatable_bonds=2,
        divergence=(
            "RDKit's Lipinski acceptor definition excludes the carboxylic acid hydroxyl and "
            "counts the ester oxygens once; its strict rotatable-bond definition excludes the "
            "bond to the ester carbonyl."
        ),
    ),
    ReferenceCompound(
        name="caffeine",
        smiles="CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
        formula="C8H10N4O2",
        pubchem_mw=194.19,
        pubchem_tpsa=58.4,
        pubchem_hbd=0,
        pubchem_hba=3,
        pubchem_rotatable_bonds=0,
        pubchem_xlogp3=-0.1,
        aromatic_rings=2,
        rdkit_tpsa=61.82,
        rdkit_hba=6,
        divergence=(
            "RDKit perceives both rings as aromatic and counts every ring nitrogen as an "
            "acceptor with the aromatic-N polar surface contribution; PubChem's XLogP3-based "
            "pipeline treats the amide nitrogens differently."
        ),
    ),
    ReferenceCompound(
        name="ibuprofen",
        smiles="CC(C)CC1=CC=C(C=C1)C(C)C(=O)O",
        formula="C13H18O2",
        pubchem_mw=206.28,
        pubchem_tpsa=37.3,
        pubchem_hbd=1,
        pubchem_hba=2,
        pubchem_rotatable_bonds=4,
        pubchem_xlogp3=3.5,
        aromatic_rings=1,
        rdkit_hba=1,
        divergence="Carboxylic acid hydroxyl not counted as an acceptor by Lipinski.",
    ),
    ReferenceCompound(
        name="acetaminophen",
        smiles="CC(=O)NC1=CC=C(C=C1)O",
        formula="C8H9NO2",
        pubchem_mw=151.16,
        pubchem_tpsa=49.3,
        pubchem_hbd=2,
        pubchem_hba=2,
        pubchem_rotatable_bonds=1,
        pubchem_xlogp3=0.5,
        aromatic_rings=1,
    ),
    ReferenceCompound(
        name="benzene",
        smiles="C1=CC=CC=C1",
        formula="C6H6",
        pubchem_mw=78.11,
        pubchem_tpsa=0.0,
        pubchem_hbd=0,
        pubchem_hba=0,
        pubchem_rotatable_bonds=0,
        pubchem_xlogp3=2.1,
        aromatic_rings=1,
    ),
    ReferenceCompound(
        name="metformin",
        smiles="CN(C)C(=N)N=C(N)N",
        formula="C4H11N5",
        pubchem_mw=129.16,
        pubchem_tpsa=91.5,
        pubchem_hbd=3,
        pubchem_hba=1,
        pubchem_rotatable_bonds=2,
        pubchem_xlogp3=-1.3,
        aromatic_rings=0,
        rdkit_rotatable_bonds=0,
        divergence=(
            "The biguanide's C=N bonds are conjugated, which RDKit's strict definition treats "
            "as non-rotatable."
        ),
    ),
    ReferenceCompound(
        name="diazepam",
        smiles="CN1C(=O)CN=C(C2=C1C=CC(=C2)Cl)C3=CC=CC=C3",
        formula="C16H13ClN2O",
        pubchem_mw=284.74,
        pubchem_tpsa=32.7,
        pubchem_hbd=0,
        pubchem_hba=2,
        pubchem_rotatable_bonds=1,
        pubchem_xlogp3=3.0,
        aromatic_rings=2,
    ),
    ReferenceCompound(
        name="atorvastatin",
        smiles=(
            "CC(C)C1=C(C(=C(N1CC[C@H](C[C@H](CC(=O)O)O)O)C2=CC=C(C=C2)F)"
            "C3=CC=CC=C3)C(=O)NC4=CC=CC=C4"
        ),
        formula="C33H35FN2O5",
        pubchem_mw=558.6,
        pubchem_tpsa=112.0,
        pubchem_hbd=4,
        pubchem_hba=6,
        pubchem_rotatable_bonds=12,
        pubchem_xlogp3=5.0,
        aromatic_rings=4,
        rdkit_tpsa=111.79,
        rdkit_hba=5,
        divergence=(
            "PubChem rounds TPSA to three significant figures; the acid hydroxyl is again not "
            "a Lipinski acceptor."
        ),
    ),
    ReferenceCompound(
        name="morphine",
        smiles="CN1CC[C@]23[C@@H]4[C@H]1CC5=C2C(=C(C=C5)O)O[C@H]3[C@H](C=C4)O",
        formula="C17H19NO3",
        pubchem_mw=285.34,
        pubchem_tpsa=52.9,
        pubchem_hbd=2,
        pubchem_hba=4,
        pubchem_rotatable_bonds=0,
        pubchem_xlogp3=0.8,
        aromatic_rings=1,
    ),
    ReferenceCompound(
        name="imatinib",
        smiles=("CC1=C(C=C(C=C1)NC(=O)C2=CC=C(C=C2)CN3CCN(CC3)C)NC4=NC=CC(=N4)C5=CN=CC=C5"),
        formula="C29H31N7O",
        pubchem_mw=493.6,
        pubchem_tpsa=86.3,
        pubchem_hbd=2,
        pubchem_hba=7,
        pubchem_rotatable_bonds=7,
        pubchem_xlogp3=3.5,
        aromatic_rings=4,
    ),
)
