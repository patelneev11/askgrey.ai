# ADMET estimation

What this module does, and — more importantly — what it refuses to do.

## The choice

Three options were on the table for ADMET on the Screening tab:

1. **Ask an LLM for pharmacokinetic numbers.** Rejected. An LLM will happily return "GI absorption
   87%, fu 4.2%, hERG IC50 3 µM" for any structure, with no basis whatsoever. Every one of those
   numbers would be fabricated, and fabricated numbers with two significant figures are more
   dangerous than no numbers at all.
2. **Ship a QSAR/ML model.** Rejected for now. The credible open models (SwissADME's SVMs, ADMETlab,
   pkCSM) either cannot be redistributed, need their training sets to define an applicability
   domain, or would mean vendoring weights we cannot validate here. Calling an external predictor
   per request would also put a third-party dependency in the middle of an authenticated flow.
3. **Apply published physicochemical rules, and say "unavailable" for everything they cannot
   cover.** Chosen.

Every estimate this module returns is therefore a **classification from a peer-reviewed rule with
published thresholds, computed from deterministic RDKit descriptors** — never a fitted value, never
a probability, never a number that looks like a measurement.

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

## What is returned as unavailable

| Field | Why |
| --- | --- |
| `plasma_protein_binding` | Fraction bound needs a regression trained on measured f<sub>u</sub>. The descriptor-level correlation with lipophilicity is far too weak to quote a percentage from, so nothing is quoted. Requires a validated QSAR with a published training set, or equilibrium dialysis / ultrafiltration data. |
| `cyp_inhibition` | Per-isoform inhibition and substrate calls (1A2/2C9/2C19/2D6/3A4) come from ML classifiers trained on screening data. Without the training set and an applicability-domain check, a per-isoform verdict would be a guess wearing a model's clothes. The structural-alert list is provided instead, clearly labelled as a substructure match. |

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

## Security and cost

No network calls, no LLM, no secrets. Input is validated and bounded by
`app.services.screening.smiles` before RDKit sees it (length, character set, heavy-atom count), and
the endpoint (`POST /api/screening/admet`) stays behind bearer authentication and the standard API
rate limiter. Malformed structures return `422`, never a traceback.

## Tests

`backend/tests/screening/admet/` checks the rules against reference compounds whose ADMET behaviour
is well documented (caffeine, diazepam and morphine as CNS-active; atorvastatin, metformin and
mannitol as non-penetrant or poorly absorbed; terfenadine and astemizole as canonical hERG
blockers; paroxetine for the methylenedioxyphenyl alert; rosiglitazone for thiazolidinedione;
ticlopidine for thiophene). Those are **classification** assertions — the tests deliberately never
assert a predicted numeric ADMET value, because the module never produces one.
