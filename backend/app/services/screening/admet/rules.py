"""
Published physicochemical rules for the ADMET estimates.

Chosen deliberately over asking an LLM for pharmacokinetic numbers: every estimate here is a
classification from a peer-reviewed rule whose thresholds are published, whose inputs are
deterministic RDKit descriptors, and whose scope is stated in the payload. Properties that no such
rule can reach — plasma protein binding, isoform-level CYP inhibition, hERG blockade probability —
are served by the trained QSAR models in `qsar_presentation.py` instead, or returned as unavailable
where neither a rule nor a validated model exists.

See README.md in this package for the selection rationale and the known limitations.
"""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import Crippen, Descriptors, Lipinski, rdMolDescriptors

from .alerts import has_basic_amine
from .models import AdmetEstimate, Outcome, RuleInput

EGAN_CITATION = "Egan, Merz & Baldwin, J. Med. Chem. 43 (2000) 3867-3877"
CNS_CITATION = (
    "Pajouhesh & Lenz, NeuroRx 2 (2005) 541-553; van de Waterbeemd et al., J. Drug Target. 6 "
    "(1998) 151-165"
)
HUGHES_CITATION = "Hughes et al., Bioorg. Med. Chem. Lett. 18 (2008) 4872-4875 (3/75 rule)"
HERG_CITATION = (
    "Cavalli et al., J. Med. Chem. 45 (2002) 3844-3853; Aronov, Drug Discov. Today 10 (2005) "
    "149-155; Aronov, J. Med. Chem. 49 (2006) 6917-6921 (uncharged blockers)"
)

# Egan's 95% confidence ellipse for well-absorbed compounds, used here as its axis-aligned bounds
# (the form in which the filter is normally applied). AlogP98 in the paper is a closed-source
# implementation; RDKit's Wildman-Crippen LogP stands in for it, which is a substitution, not the
# original descriptor.
EGAN_MAX_TPSA = 131.6
EGAN_MAX_LOGP = 5.88
# Egan's 99% ellipse: between the two bounds absorption falls off sharply, hence "borderline".
EGAN_OUTER_TPSA = 148.1

CNS_MAX_MW = 450.0
CNS_MAX_TPSA = 70.0
CNS_MAX_HBD = 3
CNS_MAX_LOGP = 5.0

# The lipophilicity above which the hERG literature reports risk rising steeply for basic amines.
HERG_LOGP_THRESHOLD = 3.7


class Descriptors2D:
    """The descriptor values the rules below need, computed once per structure."""

    def __init__(self, mol: Chem.Mol) -> None:
        self.mol = mol
        self.molecular_weight = float(Descriptors.MolWt(mol))
        self.logp = float(Crippen.MolLogP(mol))
        self.tpsa = float(Descriptors.TPSA(mol))
        self.hbd = int(Lipinski.NumHDonors(mol))
        self.hba = int(Lipinski.NumHAcceptors(mol))
        self.aromatic_rings = int(rdMolDescriptors.CalcNumAromaticRings(mol))
        self.basic_amine = has_basic_amine(mol)


def _rule_input(label: str, display: str, threshold: str, within: bool) -> RuleInput:
    return RuleInput(label=label, value_display=display, threshold=threshold, within=within)


def gi_absorption(values: Descriptors2D) -> AdmetEstimate:
    """Egan's passive-absorption delineation: a region in (TPSA, logP), not a fraction absorbed."""
    within_tpsa = values.tpsa <= EGAN_MAX_TPSA
    within_logp = values.logp <= EGAN_MAX_LOGP
    outer_tpsa = values.tpsa <= EGAN_OUTER_TPSA

    if within_tpsa and within_logp:
        outcome = Outcome.FAVOURABLE
        verdict = "Inside the Egan well-absorbed region (predicted)"
    elif within_logp and outer_tpsa:
        outcome = Outcome.BORDERLINE
        verdict = (
            "Between Egan's 95% and 99% confidence bounds — absorption falls off sharply here "
            "(predicted)"
        )
    else:
        outcome = Outcome.UNFAVOURABLE
        verdict = "Outside the Egan well-absorbed region (predicted)"

    return AdmetEstimate(
        key="gi_absorption",
        label="GI absorption",
        available=True,
        outcome=outcome,
        verdict=verdict,
        scope=(
            "Classification of passive absorption only. It does not estimate a fraction absorbed, "
            "and it says nothing about active transport, efflux, solubility or first-pass "
            "metabolism — Egan excluded actively transported compounds when fitting the region."
        ),
        model_basis=(
            "Egan's physicochemical delineation of passive human intestinal absorption, applied "
            f"as its axis-aligned 95% bounds (TPSA <= {EGAN_MAX_TPSA} A^2, logP <= "
            f"{EGAN_MAX_LOGP}) to RDKit Descriptors.TPSA and Crippen.MolLogP. The paper's "
            "AlogP98 is a closed-source implementation; Wildman-Crippen logP is substituted for "
            "it, so borderline compounds can land on either side of the boundary."
        ),
        citation=EGAN_CITATION,
        inputs=[
            _rule_input("TPSA", f"{values.tpsa:.1f} A^2", f"<= {EGAN_MAX_TPSA} A^2", within_tpsa),
            _rule_input("cLogP", f"{values.logp:.2f}", f"<= {EGAN_MAX_LOGP}", within_logp),
        ],
    )


def bbb_penetration(values: Descriptors2D) -> AdmetEstimate:
    """CNS property-space classification. Not a logBB value and not a P-gp assessment."""
    checks = [
        _rule_input(
            "Molecular weight",
            f"{values.molecular_weight:.2f} g/mol",
            f"< {CNS_MAX_MW:.0f} g/mol",
            values.molecular_weight < CNS_MAX_MW,
        ),
        _rule_input(
            "TPSA",
            f"{values.tpsa:.1f} A^2",
            f"< {CNS_MAX_TPSA:.0f} A^2",
            values.tpsa < CNS_MAX_TPSA,
        ),
        _rule_input(
            "H-bond donors", f"{values.hbd:d}", f"< {CNS_MAX_HBD:d}", values.hbd < CNS_MAX_HBD
        ),
        _rule_input(
            "cLogP", f"{values.logp:.2f}", f"< {CNS_MAX_LOGP:.0f}", values.logp < CNS_MAX_LOGP
        ),
    ]
    failures = sum(1 for check in checks if not check.within)

    if failures == 0:
        outcome = Outcome.FAVOURABLE
        verdict = "Inside the property space of marketed CNS drugs (predicted)"
    elif failures == 1:
        outcome = Outcome.BORDERLINE
        verdict = "One property outside the CNS drug property space (predicted)"
    else:
        outcome = Outcome.UNFAVOURABLE
        verdict = f"{failures} properties outside the CNS drug property space (predicted)"

    return AdmetEstimate(
        key="bbb_penetration",
        label="BBB penetration",
        available=True,
        outcome=outcome,
        verdict=verdict,
        scope=(
            "A property-space comparison against marketed CNS drugs, not a logBB, a Kp,uu or a "
            "brain concentration. It cannot see P-glycoprotein efflux, which is the usual reason "
            "a compound with ideal properties still fails to reach the brain, and a compound "
            "outside the space may still be centrally active."
        ),
        model_basis=(
            "Retrospective physicochemical envelope of marketed CNS drugs (MW < "
            f"{CNS_MAX_MW:.0f}, TPSA < {CNS_MAX_TPSA:.0f} A^2, HBD < {CNS_MAX_HBD}, cLogP < "
            f"{CNS_MAX_LOGP:.0f}) evaluated on RDKit descriptors. Counts of properties outside "
            "the envelope, not a fitted model or a probability. The CNS MPO score is not "
            "computed: it needs logD(7.4) and the pKa of the most basic centre, neither of which "
            "RDKit provides."
        ),
        citation=CNS_CITATION,
        inputs=checks,
    )


def cyp_isoforms_not_modelled() -> AdmetEstimate:
    """CYP1A2 and CYP2C19, and substrate prediction for any isoform: no model is served."""
    return AdmetEstimate(
        key="cyp_inhibition_other_isoforms",
        label="CYP1A2 / CYP2C19 inhibition and CYP substrate prediction",
        available=False,
        outcome=Outcome.UNAVAILABLE,
        model_basis=(
            "No call is produced for these endpoints. Trained classifiers are served for CYP3A4, "
            "CYP2D6 and CYP2C9 inhibition (see those estimates); CYP1A2 and CYP2C19 inhibition and "
            "substrate identification for any isoform are not modelled here, and a verdict "
            "extrapolated from the three that are would be a guess wearing a model's clothes."
        ),
        reason=(
            "Unavailable for these isoforms and for substrate prediction. What is provided instead "
            "is the CYP structural-alert list, which reports documented mechanism-based "
            "inactivation motifs and is a substructure match, not a prediction of inhibition."
        ),
        requires=(
            "A classifier trained and scaffold-validated on the corresponding assay data, or in "
            "vitro microsomal / recombinant-isoform inhibition and substrate-depletion data."
        ),
        predicted=False,
    )


def cyp_structural_alerts(values: Descriptors2D, matched_labels: list[str]) -> AdmetEstimate:
    """The CYP output that *is* defensible: which documented liability motifs are present."""
    if matched_labels:
        outcome = Outcome.UNFAVOURABLE
        verdict = (
            f"{len(matched_labels)} mechanism-based inactivation motif(s) present: "
            + ", ".join(matched_labels)
        )
    else:
        outcome = Outcome.FAVOURABLE
        verdict = "No motif from the screened alert list is present"

    return AdmetEstimate(
        key="cyp_alerts",
        label="CYP450 interaction flags (structural alerts)",
        available=True,
        outcome=outcome,
        verdict=verdict,
        scope=(
            "A substructure search against a fixed list of motifs the literature associates with "
            "mechanism-based P450 inactivation. It is not an inhibition prediction, carries no "
            "isoform assignment and no potency, and an empty result only means none of the "
            "screened motifs is present — reversible inhibition and other bioactivation routes "
            "are not covered."
        ),
        model_basis=(
            "Exact SMARTS substructure matching against motifs named in published "
            "mechanism-based P450 inactivation reviews. Deterministic matching; the liability "
            "attribution comes from the cited literature, not from this compound."
        ),
        citation=(
            "Hollenberg et al., Chem. Res. Toxicol. 21 (2008) 189-205; Orr et al., J. Med. Chem. "
            "55 (2012) 4896-4933"
        ),
        inputs=[],
    )


def herg_liability(values: Descriptors2D) -> AdmetEstimate:
    """hERG pharmacophore alert: basic nitrogen plus lipophilic aromatic character."""
    lipophilic = values.logp >= HERG_LOGP_THRESHOLD
    aromatic = values.aromatic_rings >= 2
    features = sum([values.basic_amine, lipophilic, aromatic])

    if values.basic_amine and lipophilic and aromatic:
        outcome = Outcome.UNFAVOURABLE
        verdict = "Matches the basic-amine/lipophilic-aromatic hERG pharmacophore (predicted risk)"
    elif features >= 2:
        outcome = Outcome.BORDERLINE
        verdict = "Partially matches the hERG pharmacophore (predicted risk)"
    else:
        outcome = Outcome.FAVOURABLE
        verdict = "Does not match the screened hERG pharmacophore features"

    return AdmetEstimate(
        key="herg",
        label="hERG liability",
        available=True,
        outcome=outcome,
        verdict=verdict,
        scope=(
            "A feature-count flag, not an IC50, a percentage block or a probability. Uncharged "
            "hERG blockers are documented in the same literature, so a non-match is not evidence "
            "of cardiac safety; a patch-clamp measurement is the only thing that clears a "
            "compound."
        ),
        model_basis=(
            "Published hERG pharmacophore features counted on the structure: a protonatable sp3 "
            "nitrogen (SMARTS proxy for a basic centre, since RDKit does not compute pKa), "
            f"cLogP >= {HERG_LOGP_THRESHOLD} and at least two aromatic rings. A three-feature "
            "count from a qualitative pharmacophore, not a QSAR fit."
        ),
        citation=HERG_CITATION,
        inputs=[
            _rule_input(
                "Basic (protonatable) nitrogen",
                "present" if values.basic_amine else "absent",
                "absent",
                not values.basic_amine,
            ),
            _rule_input(
                "cLogP",
                f"{values.logp:.2f}",
                f"< {HERG_LOGP_THRESHOLD}",
                not lipophilic,
            ),
            _rule_input(
                "Aromatic rings",
                f"{values.aromatic_rings:d}",
                "< 2",
                not aromatic,
            ),
        ],
    )


def general_toxicity_risk(values: Descriptors2D) -> AdmetEstimate:
    """The 3/75 rule: a promiscuity/toxicity risk band from lipophilicity and polarity."""
    low_risk = values.logp <= 3.0 and values.tpsa >= 75.0
    high_risk = values.logp > 3.0 and values.tpsa < 75.0

    if high_risk:
        outcome = Outcome.UNFAVOURABLE
        verdict = "In the higher-risk 3/75 band: cLogP > 3 and TPSA < 75 A^2 (predicted)"
    elif low_risk:
        outcome = Outcome.FAVOURABLE
        verdict = "In the lower-risk 3/75 band: cLogP <= 3 and TPSA >= 75 A^2 (predicted)"
    else:
        outcome = Outcome.BORDERLINE
        verdict = "Between the 3/75 bands (predicted)"

    return AdmetEstimate(
        key="general_toxicity",
        label="In vivo tolerability risk (3/75)",
        available=True,
        outcome=outcome,
        verdict=verdict,
        scope=(
            "A population-level association between physicochemistry and the odds of adverse "
            "in vivo findings, derived from a retrospective analysis of preclinical toxicology "
            "studies. It is a prior over a set of compounds, not a prediction of toxicity for "
            "this one, and no specific organ or mechanism is implied."
        ),
        model_basis=(
            "The 3/75 rule (cLogP <= 3 and TPSA >= 75 A^2 associated with a lower incidence of "
            "adverse in vivo outcomes) evaluated on RDKit Crippen.MolLogP and Descriptors.TPSA. "
            "A retrospective association from a published dataset, not a model fitted to this "
            "compound."
        ),
        citation=HUGHES_CITATION,
        inputs=[
            _rule_input("cLogP", f"{values.logp:.2f}", "<= 3", values.logp <= 3.0),
            _rule_input("TPSA", f"{values.tpsa:.1f} A^2", ">= 75 A^2", values.tpsa >= 75.0),
        ],
    )
