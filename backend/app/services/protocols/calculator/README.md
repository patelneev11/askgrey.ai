# Bench calculator

Deterministic arithmetic for the numbers embedded in a protocol step: dilutions, master mixes,
stock ratios and weigh-outs.

```python
from app.services.protocols.calculator import DilutionRequest, solve_dilution

result = solve_dilution(
    DilutionRequest(
        stock_concentration={"value": "10", "unit": "mM"},
        final_concentration={"value": "10", "unit": "uM"},
        final_volume={"value": "10", "unit": "mL"},
    )
)
result.stock_volume.label   # '0.01 mL'
result.diluent_volume.label # '9.99 mL'
result.basis                # 'V1 = C2 x V2 / C1 = 10 uM x 10 mL / 10 mM'
```

## No model is consulted

Every function here is a closed-form equation over `Decimal` inputs. That is the whole point:
a drafted protocol carries a review-required caveat because a model wrote it, whereas a
calculator field carries the equation that produced it and can be checked in one line. The API
labels them differently for exactly this reason — see `basis` on every result.

## Units are converted, never assumed

Concentrations belong to a *family*: molar (`M`/`mM`/`uM`/`nM`/`pM`), mass per volume
(`mg/mL`/`ug/mL`/`ng/mL`), fold (`X`) and `% (w/v)`. Arithmetic runs in the family's canonical
unit and the answer is converted back into the unit its counterpart was supplied in.

Crossing families raises `UnitMismatchError` rather than guessing: mg/mL to M needs a molecular
weight, and a 100x stock has no molar equivalent at all. A silent unit conversion is the most
plausible route from this code to a wrong volume on a bench, so there are none.

`µ` (U+00B5) and `μ` (U+03BC) are both accepted, as are `uM`, `um` and `µM` — pasted SOPs
contain all of them.

## Rounding happens once

Results are rounded to 6 significant figures, half up, at the moment a quantity is built for
output — not between steps. Master mix component totals are each computed from the unrounded
scale factor, so the printed component volumes sum to the printed total.

## Refusals

| Input | Behaviour |
| --- | --- |
| Zero in a divisor (`C1`, `V1`, `V2`, working concentration) | `CalculatorInputError` naming the term |
| More or fewer than one unset term in `C1V1 = C2V2` | `CalculatorInputError` |
| Working concentration above the stock | `CalculatorInputError` — diluting cannot concentrate |
| Stock volume above the final volume | `CalculatorInputError` — no room for diluent |
| Concentration families crossed | `UnitMismatchError` |
| Non-molar concentration in a weigh-out | `UnitMismatchError` |

Practical-but-valid answers are returned with a note instead of an error: a sub-microlitre
transfer, or a single-step dilution beyond 200-fold, is flagged for pipetting accuracy.

## Live recalculation

`recalculate(RecalculationRequest)` takes every inline field of a protocol at once, optionally
overriding `batch_scale` (well/sample count) and `overage_percent` across all master mixes, and
returns one outcome per field id. A field that cannot be computed mid-edit comes back with an
`error` on that entry rather than failing the batch, so the rest of the protocol keeps its
numbers while the user is still typing.
