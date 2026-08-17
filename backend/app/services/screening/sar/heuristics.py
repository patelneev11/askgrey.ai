"""
Deterministic substituent suggestions from textbook medicinal-chemistry heuristics.

This is the fallback suggester — it runs whenever no Anthropic key is configured and whenever a
Claude call fails — and it is also what keeps the feature honest: every suggestion here is a
named, published heuristic triggered by a substructure match or a descriptor threshold, so the
rationale can be checked rather than believed.

None of it is a prediction. A halogen in place of a benzylic methyl *often* blocks oxidative
metabolism; whether it does so in a given series, and what it costs in potency, is a question
for a chemist and an assay. That is why every set carries `SUGGESTION_CAVEAT` and
`validated=False`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rdkit import Chem

from .models import (
    DescriptorProfile,
    SubstituentSuggestion,
    SuggestionSet,
    SuggestionSource,
)

GENERATOR = "rule-based medicinal-chemistry heuristics (deterministic)"
MAX_SUGGESTIONS = 6


@dataclass(frozen=True)
class Heuristic:
    """One suggestion, the SMARTS or descriptor condition that fires it, and its priority."""

    key: str
    smarts: str
    """Empty for a descriptor-only heuristic."""
    condition: Callable[[DescriptorProfile], bool] | None
    priority: int
    suggestion: SubstituentSuggestion

    def matches(self, mol: Chem.Mol, profile: DescriptorProfile) -> bool:
        if self.smarts:
            pattern = Chem.MolFromSmarts(self.smarts)
            if pattern is None or not mol.HasSubstructMatch(pattern):
                return False
        if self.condition is not None and not self.condition(profile):
            return False
        return True


def _above(key: str, limit: float) -> Callable[[DescriptorProfile], bool]:
    def test(profile: DescriptorProfile) -> bool:
        value = profile.value_of(key)
        return value is not None and value > limit

    return test


HEURISTICS: tuple[Heuristic, ...] = (
    Heuristic(
        key="benzylic_methyl_to_halogen",
        smarts="[CH3]-c",
        condition=None,
        priority=10,
        suggestion=SubstituentSuggestion(
            title="Swap the aryl methyl for fluorine or chlorine",
            site="Methyl group attached to an aromatic ring",
            transformation="Ar-CH3 -> Ar-F or Ar-Cl",
            rationale=(
                "A methyl on an aromatic ring is a common site of CYP-mediated benzylic "
                "oxidation. Halogen substitution removes the abstractable hydrogens while "
                "keeping a similar steric footprint."
            ),
            expected_effect=(
                "Often slows oxidative metabolism at that position; chlorine adds "
                "lipophilicity (pi ~ 0.71), fluorine adds almost none (pi ~ 0.14)."
            ),
            risk=(
                "Metabolism may shift to another site rather than stop, and the electronic "
                "change can cost potency if the methyl makes a hydrophobic contact."
            ),
        ),
    ),
    Heuristic(
        key="ester_to_amide",
        smarts="[CX3](=O)O[CX4]",
        condition=None,
        priority=20,
        suggestion=SubstituentSuggestion(
            title="Replace the ester with an amide or other stable bioisostere",
            site="Alkyl ester",
            transformation="-C(=O)O-R -> -C(=O)NH-R, oxadiazole or ketone bioisostere",
            rationale=(
                "Alkyl esters are hydrolysed by plasma and hepatic esterases, which usually "
                "reads as a short half-life unless the ester is an intended prodrug handle."
            ),
            expected_effect="Typically improves plasma stability; lowers LogP modestly.",
            risk=(
                "Amides are more polar and can lose a key H-bond geometry; if the ester is "
                "the prodrug trigger, replacing it removes the exposure it was there to buy."
            ),
        ),
    ),
    Heuristic(
        key="aniline_capping",
        smarts="[NX3;H2]-c",
        condition=None,
        priority=15,
        suggestion=SubstituentSuggestion(
            title="Cap the primary aromatic amine",
            site="Aniline nitrogen",
            transformation="Ar-NH2 -> Ar-NHC(=O)R, Ar-NHSO2R or a ring-fused nitrogen",
            rationale=(
                "Unsubstituted anilines are a recognised structural alert: N-oxidation can give "
                "hydroxylamine and nitroso species associated with idiosyncratic toxicity."
            ),
            expected_effect="Removes the alert; acylation also lowers basicity and LogD.",
            risk=(
                "The free NH2 is often a hydrogen-bond donor to the target, so capping it can "
                "cost potency outright."
            ),
        ),
    ),
    Heuristic(
        key="nitro_replacement",
        smarts="[N+](=O)[O-]",
        condition=None,
        priority=5,
        suggestion=SubstituentSuggestion(
            title="Replace the nitro group",
            site="Aromatic or aliphatic nitro group",
            transformation="-NO2 -> -CN, -SO2Me, -CF3 or halogen",
            rationale=(
                "Nitroaromatics are reduced to reactive nitroso and hydroxylamine "
                "intermediates and are a long-standing genotoxicity alert."
            ),
            expected_effect=(
                "Removes the alert while keeping an electron-withdrawing group of similar "
                "Hammett character."
            ),
            risk="No isostere matches nitro's electronics exactly; expect a potency shift.",
        ),
    ),
    Heuristic(
        key="phenol_masking",
        smarts="[OX2H]-c",
        condition=None,
        priority=30,
        suggestion=SubstituentSuggestion(
            title="Mask or bioisosterically replace the phenol",
            site="Phenolic hydroxyl",
            transformation="Ar-OH -> Ar-OMe, Ar-F, or an acyl/phosphate prodrug",
            rationale=(
                "Phenols are rapidly glucuronidated and sulfated, which frequently limits oral "
                "exposure through first-pass conjugation."
            ),
            expected_effect="Usually raises exposure; methylation removes a donor and adds LogP.",
            risk=(
                "If the phenol donates a hydrogen bond in the binding site, masking it is "
                "likely to be potency-destroying rather than neutral."
            ),
        ),
    ),
    Heuristic(
        key="reduce_lipophilicity",
        smarts="c1ccccc1",
        condition=_above("logp", 4.0),
        priority=25,
        suggestion=SubstituentSuggestion(
            title="Lower lipophilicity by swapping a phenyl for an azine",
            site="Unsubstituted benzene ring",
            transformation="phenyl -> pyridyl / pyrimidinyl, or add a small polar substituent",
            rationale=(
                "cLogP above ~4 correlates with higher promiscuity, hERG binding and poorer "
                "solubility in retrospective analyses of clinical candidates."
            ),
            expected_effect=(
                "Each ring nitrogen typically removes ~1 LogP unit and adds an acceptor."
            ),
            risk=(
                "A ring nitrogen changes the pi-system and can break a hydrophobic or "
                "pi-stacking contact; solubility gains are not guaranteed."
            ),
        ),
    ),
    Heuristic(
        key="restrict_flexibility",
        smarts="",
        condition=_above("rotatable_bonds", 10.0),
        priority=35,
        suggestion=SubstituentSuggestion(
            title="Restrict the flexible linker",
            site="Acyclic linker carrying the rotatable bonds",
            transformation=(
                "Close a ring across the linker, or replace a -CH2CH2- span with a "
                "cyclopropyl or alkene"
            ),
            rationale=(
                "More than 10 rotatable bonds exceeds the Veber flexibility criterion, which "
                "tracked with reduced oral bioavailability in rat data."
            ),
            expected_effect=(
                "Reduces the entropic cost of binding and often improves permeability."
            ),
            risk=(
                "Conformational restriction is only favourable if it locks the bound "
                "conformation; the wrong ring closure loses activity entirely."
            ),
        ),
    ),
    Heuristic(
        key="trim_molecular_weight",
        smarts="",
        condition=_above("molecular_weight", 500.0),
        priority=40,
        suggestion=SubstituentSuggestion(
            title="Trim molecular weight before elaborating further",
            site="Peripheral substituents not making target contacts",
            transformation="Remove or shorten peripheral groups; keep the pharmacophore",
            rationale=(
                "Molecular weight above 500 breaches the Rule of Five and leaves no room for "
                "the growth that potency optimisation usually requires."
            ),
            expected_effect="Improves ligand efficiency if potency is retained.",
            risk=(
                "Requires knowing which groups touch the target; without a structure or SAR "
                "matrix this is guesswork."
            ),
        ),
    ),
)

FALLBACK = SubstituentSuggestion(
    title="No heuristic fired for this structure",
    site="-",
    transformation="-",
    rationale=(
        "None of this module's substructure or descriptor triggers matched, so it has nothing "
        "specific to propose. That is not a statement that the structure is optimal."
    ),
    expected_effect="Unknown.",
    risk="Absence of a suggestion carries no information about the compound's quality.",
)


def suggest_from_rules(structure_mol: Chem.Mol, profile: DescriptorProfile) -> SuggestionSet:
    """Every heuristic whose condition this structure meets, highest priority first."""
    fired = [
        heuristic
        for heuristic in sorted(HEURISTICS, key=lambda item: item.priority)
        if heuristic.matches(structure_mol, profile)
    ]
    suggestions = [heuristic.suggestion for heuristic in fired[:MAX_SUGGESTIONS]]
    return SuggestionSet(
        canonical_smiles=profile.canonical_smiles,
        source=SuggestionSource.RULES,
        generator=GENERATOR,
        suggestions=suggestions or [FALLBACK],
    )
