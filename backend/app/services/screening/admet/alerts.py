"""
Substructure alerts for metabolic and cardiac liabilities.

Each entry is a SMARTS pattern for a group that the cited literature associates with a specific
liability — mechanism-based inactivation of a P450, or hERG block. A match is a reason to run the
assay, not a prediction: the alert says "this motif has caused this problem in other compounds",
which is a statement about the literature rather than about this molecule. Absence of a match is
worth even less, because the same reviews document liabilities in series lacking every motif here.
"""

from __future__ import annotations

from dataclasses import dataclass

from rdkit import Chem

from .models import StructuralAlert

MBI_CITATION = (
    "Hollenberg et al., Chem. Res. Toxicol. 21 (2008) 189-205; Orr et al., J. Med. Chem. 55 "
    "(2012) 4896-4933 (mechanism-based P450 inactivation, structural classes)"
)
HERG_CITATION = (
    "Cavalli et al., J. Med. Chem. 45 (2002) 3844-3853; Aronov & Goldman, Bioorg. Med. Chem. 12 "
    "(2004) 2307-2315 (basic-nitrogen/aromatic hERG pharmacophore)"
)


@dataclass(frozen=True)
class AlertSpec:
    key: str
    label: str
    smarts: str
    concern: str
    citation: str

    def evaluate(self, mol: Chem.Mol) -> StructuralAlert:
        pattern = Chem.MolFromSmarts(self.smarts)
        matched = pattern is not None and mol.HasSubstructMatch(pattern)
        return StructuralAlert(
            key=self.key,
            label=self.label,
            concern=self.concern,
            citation=self.citation,
            matched=matched,
        )


# The P450 classes named in the cited reviews that can be expressed as an unambiguous 2D
# substructure. Classes that cannot (quinone-forming anilines, arylamine bioactivation) are left
# out rather than approximated by a pattern that would fire on half of all drug-like molecules.
ALERT_SPECS: tuple[AlertSpec, ...] = (
    AlertSpec(
        key="methylenedioxyphenyl",
        label="Methylenedioxyphenyl (benzodioxole)",
        smarts="c1ccc2c(c1)OCO2",
        concern=(
            "Forms a carbene that coordinates the P450 heme; a classic mechanism-based "
            "inactivator motif (CYP3A4, CYP2D6) and a recognised DDI risk."
        ),
        citation=MBI_CITATION,
    ),
    AlertSpec(
        key="terminal_alkyne",
        label="Terminal alkyne",
        smarts="[CX2;H1]#[CX2]",
        concern=(
            "Oxidised to a ketene or oxirene that acylates the apoprotein or heme, inactivating "
            "the enzyme irreversibly."
        ),
        citation=MBI_CITATION,
    ),
    AlertSpec(
        key="furan",
        label="Furan ring",
        smarts="c1ccoc1",
        concern=(
            "Epoxidised to a reactive ene-dione; associated with P450 inactivation and covalent "
            "protein binding."
        ),
        citation=MBI_CITATION,
    ),
    AlertSpec(
        key="thiophene",
        label="Thiophene ring",
        smarts="c1ccsc1",
        concern=(
            "S-oxidation gives an electrophilic S-oxide or epoxide; a documented "
            "mechanism-based inactivation and reactive-metabolite motif."
        ),
        citation=MBI_CITATION,
    ),
    AlertSpec(
        key="thiazolidinedione",
        label="Thiazolidinedione",
        smarts="O=C1NC(=O)SC1",
        concern=(
            "Ring-opening bioactivation produces reactive species implicated in P450 "
            "inactivation and idiosyncratic hepatotoxicity."
        ),
        citation=MBI_CITATION,
    ),
    AlertSpec(
        key="isothiocyanate",
        label="Isothiocyanate",
        smarts="[NX2]=[CX2]=[SX1]",
        concern="Directly electrophilic at sulfur; inactivates P450s and haptenises protein.",
        citation=MBI_CITATION,
    ),
    AlertSpec(
        key="hydrazine",
        label="Hydrazine / hydrazide",
        smarts="[NX3;!$(N=*)]-[NX3;!$(N=*)]",
        concern=(
            "Oxidised to diazene and radical species; associated with P450 inactivation and "
            "hepatotoxicity."
        ),
        citation=MBI_CITATION,
    ),
    AlertSpec(
        key="basic_amine_aromatic",
        label="Basic nitrogen flanked by aromatic rings (hERG pharmacophore)",
        # An sp3 nitrogen that is not an amide/aniline/nitrile, in a molecule that also carries
        # aromatic rings; the ring requirement is enforced by the rule in `rules.py`, which has
        # the descriptor counts.
        smarts="[NX3;H0,H1,H2;!$(N[#6]=[O,N,S]);!$(Na);!$(N#*);!$(N=*)]",
        concern=(
            "Protonatable amine flanked by hydrophobic aromatic groups is the recurring feature "
            "of hERG blockers in published pharmacophores; uncharged blockers also exist, so "
            "absence of this motif does not clear a compound."
        ),
        citation=HERG_CITATION,
    ),
)


def evaluate_alerts(mol: Chem.Mol) -> list[StructuralAlert]:
    """Every alert in `ALERT_SPECS`, matched or not, so the UI can show what was checked."""
    return [spec.evaluate(mol) for spec in ALERT_SPECS]


def has_basic_amine(mol: Chem.Mol) -> bool:
    """Whether the structure carries a plausibly protonatable sp3 nitrogen.

    A proxy for basicity: RDKit does not compute pKa, so an amine that is neither an amide, an
    aniline, nor otherwise deactivated is treated as basic. That over-counts weak bases.
    """
    spec = next(item for item in ALERT_SPECS if item.key == "basic_amine_aromatic")
    pattern = Chem.MolFromSmarts(spec.smarts)
    return pattern is not None and mol.HasSubstructMatch(pattern)
