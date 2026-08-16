# Grant budget

Turns internal R&D cost estimates into a costed SBIR/STTR budget in SF-424 (R&R) shape.

```python
from app.services.grants.budget import BudgetCalculator, render

budget = BudgetCalculator.from_config_file().build(request)
budget.total          # section K, the number the agency is asked for
budget.adjustments    # every place a federal rule changed a requested number
file = render(budget) # .xlsx through the shared export service
```

## Rules live in `rules.json`, not in code or a prompt

The salary cap, the de minimis indirect rate, the MTDC subaward cap, the fee ceiling and the
phase award guidelines are published figures that are revised on a schedule. They sit in
`rules.json` so they can be updated without a code change, and the config `version` is stamped
onto every budget produced, so an old budget can be read against the rules it was built under.

Nothing here is model-driven: the same inputs always produce the same numbers, and every
number is reproducible from the `basis` string printed beside it.

## What the rules do

| Rule | Effect |
| --- | --- |
| `salary_cap` | Salary is computed on `min(base salary, cap)`. The over-cap remainder is reported as an `Adjustment` — the company pays it, the award does not. |
| `fringe` | Charged on the salary actually requested, at the person's rate or the configured default. |
| `mtdc_exclusion` | Equipment and participant support leave the base indirect costs are charged on. |
| `subaward_mtdc_cap` | Only the first $25,000 of each subaward stays in that base. |
| `de_minimis_indirect_rate` | With no negotiated rate given, the de minimis rate is used and said so. A missing rate is not treated as zero. |
| `fee_cap` | A requested fee above the maximum is clipped to the maximum. |
| award guidelines | A total or period beyond the phase guideline is a warning, not a failure — agencies can approve larger budgets. |

## Sections

`A` Senior/Key Person, `B` Other Personnel, `C` Equipment, `D` Travel, `E` Participant/Trainee
Support, `F` Other Direct Costs, `G` total direct (A–F), `H` indirect, `I` G+H, `J` fee,
`K` total. `G`, `I` and `K` are computed properties, not stored, so they cannot drift from the
lines above them. Every amount is `Decimal`, rounded to cents once per line, so the printed
sections sum exactly to the printed total.

## Export

`to_extraction_table()` projects the budget into the review-table schema and `render()` hands it
to the Wave 1 `ExportService`. There is no second spreadsheet writer: formula-injection
escaping, illegal-character stripping, Excel's cell limits and the CSV BOM all have one
implementation. The one thing the shared exporter needed was a rename of its record column
(`ExportOptions.record_label`), which now carries the section instead of a paper title.

The cost of the reuse: amounts are written as formatted text, because `ExtractionCell.value` is
a string. A recipient who needs live spreadsheet arithmetic would want numeric cells added to
the exporter — still one writer, not two.

## Limits

- The figures in `rules.json` are the common federal ones. Agencies and solicitations vary, and
  the salary cap and award guidelines are revised annually — check the solicitation before
  submitting.
- The default fringe rate is a planning placeholder. An organization's real rate is its own.
- No negotiated indirect cost rate agreement is validated here; the rate is taken as given.
- This produces a budget to work from, not a submission. It is not the agency's form, and it is
  not a compliance review of one.
