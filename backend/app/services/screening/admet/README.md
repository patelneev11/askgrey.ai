# ADMET estimation

What this module does, and — more importantly — what it refuses to do.

## The choice

Three options were on the table for ADMET on the Screening tab:

1. **Ask an LLM for pharmacokinetic numbers.** Rejected. An LLM will happily return "GI absorption
   87%, fu 4.2%, hERG IC50 3 µM" for any structure, with no basis whatsoever. Every one of those
   numbers would be fabricated, and fabricated numbers with two significant figures are more
   dangerous than no numbers at all.
2. **Vendor a third-party QSAR predictor.** Rejected. SwissADME, ADMETlab and pkCSM either cannot be
   redistributed or ship weights whose training sets are not available, so their applicability
   domain cannot be checked here; calling one per request would also put a third-party dependency
   inside an authenticated flow.
3. **Apply published physicochemical rules, and train our own QSAR models on public benchmark data
   for the properties no rule can reach.** Chosen — both halves, kept visibly separate in the
   payload.

So every estimate is one of two things, and the response says which: a **classification from a
peer-reviewed rule with published thresholds**, or a **prediction from a model fitted here on public
assay data, scaffold-validated, and refused outside its applicability domain**. Neither is a
measurement, and the module never returns a number it cannot attach an error and a provenance to.

## What is returned

| Field | Basis | Reference |
| --- | --- | --- |
| `gi_absorption` | Egan's 95%/99% confidence bounds on (TPSA, logP) for passive human intestinal absorption | Egan, Merz & Baldwin, *J. Med. Chem.* 43 (2000) 3867–3877 |
| `bbb_penetration` | Physicochemical envelope of marketed CNS drugs: MW < 450, TPSA < 70 Å², HBD < 3, cLogP < 5 | Pajouhesh & Lenz, *NeuroRx* 2 (2005) 541–553; van de Waterbeemd et al., *J. Drug Target.* 6 (1998) 151–165 |
| `herg` | Basic-nitrogen + lipophilic-aromatic hERG pharmacophore, as a feature count | Cavalli et al., *J. Med. Chem.* 45 (2002) 3844–3853; Aronov, *Drug Discov. Today* 10 (2005) 149–155 |
| `cyp_alerts` | SMARTS matching against motifs documented as mechanism-based P450 inactivators | Hollenberg et al., *Chem. Res. Toxicol.* 21 (2008) 189–205; Orr et al., *J. Med. Chem.* 55 (2012) 4896–4933 |
| `general_toxicity` | The 3/75 rule: cLogP ≤ 3 and TPSA ≥ 75 Å² associated with fewer adverse in vivo findings | Hughes et al., *Bioorg. Med. Chem. Lett.* 18 (2008) 4872–4875 |

Each estimate carries a **required, non-empty `model_basis`** field naming the rule and the
descriptors it consumed, plus a `scope` field stating what the classification explicitly does *not*
say. `model_basis` is part of the response schema, not metadata: the Screening UI renders it next to
the value.

## The trained QSAR models

Five gradient-boosted-tree models, trained by `backend/training/admet_qsar/train.py` on Therapeutics
Data Commons benchmark sets (all CC BY 4.0) and shipped as JSON in `qsar_models/`:

| Field | Dataset | Task | Compounds | Held-out performance |
| --- | --- | --- | --- | --- |
| `herg_blockade` | hERG_Karim | classification | 13,445 | ROC-AUC 0.862, balanced accuracy 0.772, Brier 0.153 |
| `plasma_protein_binding` | PPBR_AZ (AstraZeneca) | regression, % bound | 1,614 | MAE 8.2 % bound, R² 0.30 (in-domain MAE 7.8, R² 0.39) |
| `cyp3a4_inhibition` | CYP3A4_Veith | classification | 12,328 | ROC-AUC 0.933, balanced accuracy 0.849 |
| `cyp2d6_inhibition` | CYP2D6_Veith | classification | 13,130 | ROC-AUC 0.871, balanced accuracy 0.764 |
| `cyp2c9_inhibition` | CYP2C9_Veith | classification | 12,092 | ROC-AUC 0.872, balanced accuracy 0.679 |

Dataset citations and URLs travel inside each artifact and are echoed in the response's `citation`
field. A model that missed the pre-declared bar (ROC-AUC ≥ 0.75, R² ≥ 0.30 on the held-out split)
would not have been written; the training script fails loudly instead of shipping it.

**How they are built and served**

- **Features.** Morgan count fingerprints (radius 2, 2048 bits, counts capped at 4) plus 12 RDKit
  descriptors (MW, cLogP, TPSA, HBD, HBA, rotatable bonds, rings, aromatic rings, heavy atoms,
  Fsp3, molar refractivity, formal charge). The featurizer is versioned
  (`morgan2-2048-count4+desc12`) and an artifact built against a different version is refused at
  load, not silently mis-fed.
- **Split.** Bemis–Murcko **scaffold** split, 70/10/20 — no scaffold is shared between train,
  calibration and test — so the quoted metrics are not the random-split numbers that flatter every
  fingerprint model. Metrics come from the test slice only; the calibration slice is used solely for
  Platt scaling, so reported probabilities are calibrated, not raw margins.
- **Serialization.** Trees are exported as plain JSON arrays and evaluated by a small interpreter in
  `qsar.py`. No pickle, no joblib, no `__reduce__` executing on load. The training script verifies
  the exported evaluator reproduces scikit-learn's own output (max deviation ≤ 1e-6; observed
  ≤ 1.6e-13).
- **Applicability domain.** A prediction is returned only if the structure is within `min_tanimoto`
  (a percentile of the training set's own nearest-neighbour similarities, ≈0.20) of a MaxMin-chosen
  reference subset of ≤1,200 training molecules, *and* its 12 descriptors sit inside the training
  percentile bounds widened by 25%, *and* it carries no more α-amino-acid backbone linkages
  (`N–Cα–C(=O)–N`) than the training set did at the same percentile. Otherwise the field is
  `unavailable` with the similarity, the threshold and the offending check stated. Ethanol and salts
  are refused; ordinary drug-like chemistry is served (95–99% of each held-out test set is in
  domain, and in-domain metrics are reported alongside the overall ones).
- **Why peptides need their own check.** Similarity cannot make this call: a peptide is a chain of
  amide fragments the training sets contain individually, so it clears a Tanimoto threshold set for
  small-molecule chemistry. End-to-end testing of the live endpoint found leu-enkephalin served
  numbers by four of the five models on exactly that basis, so the linkage count is checked
  separately. It is a training-set bound, not a hand-picked one: a peptide-rich training set would
  widen it, and the bound is capped at one linkage because a peptide chain starts at two.
  Peptidomimetics with two or more backbone linkages (atazanavir, for instance) are refused with the
  peptides — deliberately, since the training sets contain almost none of them. **Known gap:** a
  single linkage stays in domain, because a β-lactam side chain (ampicillin, cefalexin) matches the
  same motif, so dipeptides and isopeptide-linked tripeptides such as glutathione — one α-linkage
  each — are still served if they clear the similarity and descriptor checks.
- **Failure mode.** A missing, unreadable, schema-mismatched or uncalibrated artifact makes its
  field `unavailable`; it never falls back to a rule under the same name and never returns a value
  from an artifact it could not validate.

Raw training data is **not** committed — only fitted artifacts, with dataset name, license, citation,
URL and compound count recorded inside each one. Retrain with:

```
pip install -e ".[training]" && python training/admet_qsar/train.py --write
```

## What is still returned as unavailable

| Field | Why |
| --- | --- |
| `cyp_inhibition_other_isoforms` | CYP1A2 and CYP2C19 inhibition, and substrate prediction for any isoform, are not modelled. Extrapolating from the three isoforms that are would be a guess wearing a model's clothes. The structural-alert list is provided instead, clearly labelled as a substructure match. |
| any QSAR field, for this structure | Out of the model's applicability domain, or its artifact could not be loaded — see above. |

Unavailable fields still carry `model_basis` (what *would* be needed), `reason`, and `requires`.
They are a first-class outcome (`outcome: "unavailable"`), not an error.

## Substitutions and their consequences

- Egan's model uses **AlogP98**, a closed-source implementation. RDKit's Wildman–Crippen
  `Crippen.MolLogP` stands in. The two are related but not identical, so compounds near the
  boundary can land on either side. This is stated in the returned `model_basis`.
- Egan's region is an **ellipse**; the module applies its axis-aligned bounds (TPSA ≤ 131.6 Å²,
  logP ≤ 5.88), which is how the filter is normally used. The corners of the box are therefore
  slightly more permissive than the ellipse.
- The **BOILED-Egg** (Daina & Zoete, *ChemMedChem* 11 (2016) 1117–1121) is a better-validated
  version of the same idea and would be preferable, but the numeric ellipse parameters live in the
  paper's supporting information rather than the article body, and guessing them would mean
  claiming a model we had not actually implemented. Egan is used instead, with attribution.
- **pKa is not computed.** RDKit has no pKa model, so "basic centre" in the hERG rule is a SMARTS
  proxy: an sp3 nitrogen that is neither amide, aniline, nitrile nor imine. That over-counts weak
  bases, which makes the hERG flag conservative (more likely to warn).
- The **CNS MPO** score (Wager et al., *ACS Chem. Neurosci.* 1 (2010) 435–449) is not computed for
  the same reason: it needs logD(7.4) and the pKa of the most basic centre.

## Limitations that apply to everything here

- All inputs are **2D descriptors**. No conformer, no tautomer/ionisation handling, no
  stereochemistry-dependent behaviour.
- Rules were derived from **populations of drug-like small molecules**. Peptides, macrocycles,
  covalent warheads, PROTACs and salts/mixtures are outside their applicability domain, and the
  module cannot detect that a compound is outside it.
- Classifications say nothing about **transporters** (P-gp efflux is the usual reason a
  CNS-property-space compound still fails), solubility, first-pass metabolism, or dose.
- Structural alerts are **substructure matches**. A match is a prompt to run the assay; no match is
  not evidence of safety — the hERG literature documents blockers lacking every screened feature.
- Alert lists are non-exhaustive by construction. Classes that cannot be expressed as an
  unambiguous 2D substructure (arylamine and quinone bioactivation, for instance) are omitted
  rather than approximated by a pattern that would fire on half of all drug-like molecules.

## Limitations specific to the fitted models

- The benchmark sets are assembled from public screening data (PubChem bioassays for the Veith CYP
  panels, a curated literature compilation for hERG, an AstraZeneca release for PPBR). Assay
  protocol, cell system and activity threshold vary within each set, so a probability is a
  prediction of *that benchmark's* label, not of a particular in-house assay's readout.
- Marketed drugs are frequently *in* these training sets (caffeine and terfenadine both appear in
  PPBR_AZ at Tanimoto 1.0), so a good-looking prediction for a familiar drug is not evidence of
  generalization. The scaffold-split metrics above are.
- PPBR is predicted as **percent bound**, and an MAE of 8 points is large exactly where it matters
  most: 99% versus 99.9% bound is a tenfold difference in free fraction that this model cannot
  resolve. The verdict quotes the error for that reason.
- CYP inhibition classifiers say nothing about **substrate** status, time-dependent inactivation,
  induction, or the clinical significance of any interaction.
- Same 2D-only caveat as the rules: no conformers, tautomers, stereochemistry or ionisation.

## Security and cost

No network calls (model artifacts are package data, loaded from disk), no LLM, no secrets. Input is validated and bounded by
`app.services.screening.smiles` before RDKit sees it (length, character set, heavy-atom count), and
the endpoint (`POST /api/screening/admet`) stays behind bearer authentication and the standard API
rate limiter. Malformed structures return `422`, never a traceback.

## Tests

`backend/tests/screening/admet/` checks the rules against reference compounds whose ADMET behaviour
is well documented (caffeine, diazepam and morphine as CNS-active; atorvastatin, metformin and
mannitol as non-penetrant or poorly absorbed; terfenadine and astemizole as canonical hERG
blockers; paroxetine for the methylenedioxyphenyl alert; rosiglitazone for thiazolidinedione;
ticlopidine for thiophene). Those are **classification** assertions — no rule-based test asserts a
numeric ADMET value, because no rule produces one.

`test_qsar.py` covers the model half: every declared artifact is present, matches the featurizer and
schema, carries its license/citation/split metadata, and clears the metric bar; predictions are
deterministic; an in-domain structure gets a calibrated probability with model provenance; ethanol is
refused by every model; descriptor bounds gate independently of the fingerprint; and a wrong
featurizer, an uncalibrated classifier, a corrupt file, a missing file and an empty reference set
each degrade to `unavailable` rather than to a number.
