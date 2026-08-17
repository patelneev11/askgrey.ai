---
name: testing-grants-tab
description: How to bring up askgrey.ai locally and exercise the /grants tab (opportunity search, eligibility, budget, mock review board) end to end, including the keyed and no-key LLM paths.
---

# Testing the AskGrey Grants tab end to end

## Bring-up

Stack, auth, onboarding overlays and the `ANTHROPIC_API_KEY`-in-the-uvicorn-process rule are in
the `testing-askgrey-shell` skill. Grants-specific: all `/api/grants/*` routes need a bearer
token, and the quick keyed/unkeyed oracle is `POST /api/grants/match`, which returns
`"matcher":"claude"` with a key and `"matcher":"lexical"` (or `claude+lexical`) without one.

## Flow tips

- `/grants` renders four panels in order: OpportunityFinder, EligibilityChecklist, BudgetPlanner,
  ReviewBoard. Everything is on one long scroll; after any scroll re-locate inputs before typing,
  or text lands in the wrong field.
- Search hits grants.gov live. SBIR.gov returns HTTP 403 from CI/dev boxes — the expected UI state
  is a warning pill `SBIR.gov unavailable · solicitations failed (HTTP 403)`, not a silent drop.
- Good "is this really live?" probe: set **Closing before** and re-search; the count in the panel
  header and the per-card deadlines must both change. Date inputs need `MM/DD/YYYY`; a partial
  value triggers the browser's "field is incomplete or has an invalid date" bubble.
- Entering a **Research focus** switches the submit button to "Search and rank by focus" and adds
  `NN% predicted fit` plus the "Unvalidated prediction." caveat band.
- Eligibility: blank selects (`Not recorded`) must come back as *needs review* naming the missing
  field, never *pass*. Employees > 500 must fail with a 13 CFR 121.702 citation; flipping it to a
  small number should flip that one rule to pass — a good static-output check.
- Budget: a `$250,000` base salary must be capped (currently `$225,700`, Exec Level II) and a
  blank indirect rate must use the 15% de minimis rate on MTDC with equipment excluded. Verify
  screen totals against the exported CSV; exports land in `~/Downloads` as `grant-budget.csv` /
  `grant-budget.xlsx` (the xlsx is a zip — `unzip -l` to sanity-check it).
- Review board: submit is disabled under 200 characters. LLM runs take ~30-40s; wait rather than
  re-clicking. Expect only the ticked personas back, `X.X / 9 overall`, 1-9 per-criterion scores,
  and a provenance line `claude-… · personas <version> · unvalidated`.

## No-key degradation (worth re-testing on every change)

Restart the backend with `env -u ANTHROPIC_API_KEY …`, reload, and re-run:

- Review board: expect an inline error naming `ANTHROPIC_API_KEY` and **zero** scores (503 from
  `ReviewBoardUnavailableError`).
- Matching does **not** error: the backend falls back to a lexical ranker. The UI must follow
  `MatchResult.matcher` — `claude` shows `NN% predicted fit` with the "Unvalidated prediction."
  band, while `lexical` / `claude+lexical` must show `NN% term overlap` under the "Keyword
  ranking, not a semantic match." band. A "predicted fit" label with no key is a provenance bug.
- Plain search must keep working (live grants.gov results, no fit percentages).

## Devin Secrets Needed

- `ANTHROPIC_API_KEY` (repo scope) — required for LLM matching and the mock review board.
