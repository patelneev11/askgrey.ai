---
name: testing-protocol-tab
description: How to end-to-end test the askgrey.ai Protocol Creation tab (LLM drafting, control review, master-mix calculator, version history, ELN export payload).
---

# Testing the askgrey.ai Protocol tab

Bring-up, auth, onboarding overlays and the `ANTHROPIC_API_KEY`-in-the-uvicorn-process rule are in
the `testing-askgrey-shell` skill. This file is only what is specific to `/protocol`.

Without the key, `/api/protocols/draft` and `/api/protocols/controls/review` return **503**; the
deterministic routes (`/calculator/*`, `/checklist`, save/history, `/export/eln`) still work, so
most of the tab is testable unkeyed.

## What to expect

- Drafting is a real Anthropic call, ~40–60 s: the submit button reads "Drafting…" beside a
  pulsing `drafting` pill. Control review is ~15–20 s. Wait rather than re-clicking.
- Version history only diffs after two saves: the first "Save version" records
  `v1 Initial draft saved`; edit a step and save again for `v2 … (modified)`.
- The master mix calculator recalculates **server-side** on every keystroke or scale change
  (`POST /api/protocols/calculator/recalculate`), and the backend applies a default **10 %
  dead-volume overage**, so totals are `per_reaction × wells × 1.10` (5 µL × 24 → **132 µL**). A
  browser-side reimplementation would show 120 µL — the cheapest check that the numbers really
  come from the API.
- ELN export is payload-only: it never contacts Benchling, and must stay labelled
  `schema_ready_untested` with the amber "Untested against live API" pill.

## Safety invariant to re-check on any UI change

The `CaveatBand` — "DRAFT — Agent-drafted content. Requires qualified researcher review before lab
use." — must render unconditionally, and the only `data-tone="validated"` pill on the page must be
"Arithmetic verified · this panel only". Enumerate with
`document.querySelectorAll('[data-tone]')` and confirm with a screenshot; a validated-looking pill
next to LLM-drafted steps is a reportable bug, not a cosmetic one.

## Devin secrets needed

- `ANTHROPIC_API_KEY` (repo scope) — drafting and control review only.
