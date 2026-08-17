# SAR predictor

A SMILES string in; computed descriptors, published rule-set outcomes, and heuristic
substituent suggestions out.

```python
from app.services.screening.sar import SarService

service = SarService.from_settings()
profile = service.profile("CC(=O)Oc1ccccc1C(=O)O")
profile.descriptors     # MW, cLogP, TPSA, HBD, HBA, rotatable bonds, ...
profile.rule_sets       # Lipinski Ro5 and Veber, per-threshold pass/fail
profile.unavailable     # binding affinity, and why it is not here

suggestions = await service.suggestions("CC(=O)Oc1ccccc1C(=O)O")
suggestions.source      # "llm" or "rules" — which suggester actually ran
```

## Two different kinds of output, labelled differently

`profile()` is arithmetic on the molecular graph: the same SMILES always gives the same numbers,
and no model is involved. It carries `DESCRIPTOR_CAVEAT` ("computed descriptors, not measured
values").

`suggestions()` is heuristic. It carries `SUGGESTION_CAVEAT`, `validated=False`, and the name of
the generator, because there is no data behind it — only medicinal-chemistry rules of thumb.
The frontend renders both strings; they are in the payload precisely so a client cannot lose
them.

## Why there is no binding affinity

Affinity is a property of a ligand *and* a target. Regressing it out of MW and LogP would produce
a plausible-looking number with no relationship to the compound, which is worse than no number:
somebody would rank a series with it. So `profile().unavailable` contains an explicit
`binding_affinity` entry naming what would be required — a target structure plus a docking or
free-energy pipeline, or measured assay data — and the API and UI both show that instead.

## What the LLM is and is not asked for

Claude is asked only for prose: which group on this scaffold to modify, into what, why, and what
could go wrong. The system prompt forbids numeric predictions (affinity, IC50, clearance,
probabilities), and the descriptors in the prompt are computed locally by RDKit rather than
supplied by the model, so it cannot invent them.

If no Anthropic key is configured, or a call fails, `suggestions()` falls back to
`heuristics.py`: a fixed table of SMARTS- and descriptor-triggered heuristics (aryl methyl to
halogen, ester to amide, aniline capping, nitro replacement, phenol masking, lipophilicity
reduction, conformational restriction, weight trimming). The returned set says which suggester
ran, so the fallback is visible rather than silent.

## Input validation

`..smiles.parse_structure` is the only door into RDKit: it bounds length
(`MAX_SMILES_LENGTH`), rejects any character SMILES notation cannot contain (which also stops a
pasted list or a query fragment reaching an external API), then requires RDKit to sanitize the
molecule, and caps heavy atoms at `MAX_HEAVY_ATOMS`. Malformed input raises
`InvalidStructureError`, which the API renders as 422.

## Descriptor references

Descriptor values are asserted in `tests/screening/sar/test_descriptors.py` against the ten
well-characterized compounds in `tests/screening/sar/reference.py`, whose reference values are
PubChem's own computed properties (read from PUG-REST, date recorded in that file).

Molecular weight (±0.05 g/mol), TPSA (±1 Å²), donor count and aromatic ring count must match
PubChem. Two properties genuinely disagree with it and are handled explicitly rather than
loosened away:

- **Acceptor count and rotatable bonds.** RDKit's `Lipinski` definitions are narrower than
  PubChem's (the carboxylic-acid hydroxyl is not an acceptor; conjugated bonds are not
  rotatable). Those compounds carry an `rdkit_*` value in the reference table plus the reason,
  and the test asserts a reason exists — the divergence matters because these feed the Ro5
  verdict.
- **cLogP.** Wildman–Crippen (RDKit) and XLogP3 (PubChem) are different estimators and neither
  is a measured log P, so the test asserts agreement within 1.5 log units and, more usefully,
  that the two rank the reference set the same way (≥90% concordant pairs, ignoring pairs closer
  than 0.5 units where neither estimator is precise enough for the order to mean anything).

## Limits

- Descriptors are 2D. No tautomer enumeration, no protonation-state handling at pH 7.4, no
  conformer generation; a zwitterion is described as drawn.
- Rule sets are guidelines for oral drug-likeness, not gates. Lipinski himself treats two or
  more violations as the signal, and many marketed drugs violate one.
- Suggestions are single-point ideas, not a synthesis plan, and nothing checks that the proposed
  product is synthetically accessible.
