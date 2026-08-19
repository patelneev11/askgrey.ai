"""
Reference compounds with well-documented ADMET behaviour.

The assertions built on these are deliberately *classification* assertions. The module produces no
numeric ADMET value, so no test here asserts one; what is checked is that the published rules
place well-known compounds where the literature says they belong, and that documented failure
modes of those rules are pinned rather than papered over.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceCompound:
    name: str
    smiles: str
    molecular_formula: str
    note: str


# Orally well-absorbed small molecules.
ASPIRIN = ReferenceCompound(
    "aspirin",
    "CC(=O)Oc1ccccc1C(=O)O",
    "C9H8O4",
    "Rapidly and near-completely absorbed after oral dosing.",
)
IBUPROFEN = ReferenceCompound(
    "ibuprofen",
    "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
    "C13H18O2",
    "Oral bioavailability ~80-100%.",
)
# Poorly absorbed: a large, very polar sugar.
SUCROSE = ReferenceCompound(
    "sucrose",
    "OC[C@H]1O[C@](CO)(O[C@H]2O[C@H](CO)[C@@H](O)[C@H](O)[C@H]2O)[C@@H](O)[C@@H]1O",
    "C12H22O11",
    "Not absorbed intact; used as a paracellular permeability marker.",
)
# Small and polar, and absorbed by a transporter rather than passively — outside the applicability
# domain of a passive-absorption rule, which is the point of including it.
MANNITOL = ReferenceCompound(
    "mannitol",
    "OCC(O)C(O)C(O)C(O)CO",
    "C6H14O6",
    "Poorly absorbed in humans despite low molecular weight; osmotic laxative.",
)

# Far smaller than anything in the QSAR training sets, and used here for that: a fitted model must
# refuse it rather than extrapolate.
ETHANOL = ReferenceCompound(
    "ethanol",
    "CCO",
    "C2H6O",
    "Two heavy atoms; outside the chemical space of every drug-like training set here.",
)

# CNS-active, brain-penetrant.
CAFFEINE = ReferenceCompound(
    "caffeine",
    "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
    "C8H10N4O2",
    "Freely brain penetrant CNS stimulant.",
)
DIAZEPAM = ReferenceCompound(
    "diazepam",
    "CN1c2ccc(Cl)cc2C(=Nc3ccccc3)CC1=O",
    "C16H13ClN2O",
    "Brain-penetrant benzodiazepine; not a hERG blocker at therapeutic exposure.",
)
# Peripherally restricted / non-penetrant.
ATORVASTATIN = ReferenceCompound(
    "atorvastatin",
    "CC(C)c1c(C(=O)Nc2ccccc2)c(-c2ccccc2)c(-c2ccc(F)cc2)n1CC[C@@H](O)C[C@@H](O)CC(=O)O",
    "C33H35FN2O5",
    "Hepatoselective; no meaningful CNS exposure.",
)
METFORMIN = ReferenceCompound(
    "metformin",
    "CN(C)C(=N)N=C(N)N",
    "C4H11N5",
    "Hydrophilic biguanide; negligible brain penetration.",
)
SULPIRIDE = ReferenceCompound(
    "sulpiride",
    "CCN1CCCC1CNC(=O)c1cc(S(N)(=O)=O)ccc1OC",
    "C15H23N3O4S",
    "Centrally active antipsychotic with poor passive BBB permeability — a documented "
    "counterexample to property-space filters.",
)

# Canonical hERG blockers, both withdrawn for QT prolongation.
TERFENADINE = ReferenceCompound(
    "terfenadine",
    "CC(C)(C)c1ccc(cc1)C(O)CCCN1CCC(CC1)C(O)(c1ccccc1)c1ccccc1",
    "C32H41NO2",
    "Withdrawn for hERG-mediated QT prolongation; basic amine plus high lipophilicity.",
)
ASTEMIZOLE = ReferenceCompound(
    "astemizole",
    "COc1ccc(CCN2CCC(CC2)Nc2nc3ccccc3n2Cc2ccc(F)cc2)cc1",
    "C28H31FN4O",
    "Withdrawn for hERG-mediated QT prolongation.",
)

# Structural-alert positives.
PAROXETINE = ReferenceCompound(
    "paroxetine",
    "Fc1ccc(cc1)C1CCNCC1COc1ccc2OCOc2c1",
    "C19H20FNO3",
    "Methylenedioxyphenyl group; mechanism-based CYP2D6 inactivator.",
)
ROSIGLITAZONE = ReferenceCompound(
    "rosiglitazone",
    "CN(CCOc1ccc(CC2SC(=O)NC2=O)cc1)c1ccccn1",
    "C18H19N3O3S",
    "Thiazolidinedione ring; bioactivation liability.",
)
TICLOPIDINE = ReferenceCompound(
    "ticlopidine",
    "Clc1ccccc1CN1CCc2ccsc2C1",
    "C14H14ClNS",
    "Thiophene; mechanism-based CYP2C19/2B6 inactivator.",
)

ALL_COMPOUNDS: tuple[ReferenceCompound, ...] = (
    ASPIRIN,
    IBUPROFEN,
    SUCROSE,
    MANNITOL,
    ETHANOL,
    CAFFEINE,
    DIAZEPAM,
    ATORVASTATIN,
    METFORMIN,
    SULPIRIDE,
    TERFENADINE,
    ASTEMIZOLE,
    PAROXETINE,
    ROSIGLITAZONE,
    TICLOPIDINE,
)
