---
name: testing-protocol-tab
description: How to end-to-end test the askgrey.ai Protocol Creation tab (LLM drafting, control review, master-mix calculator, version history, ELN notebook-bundle download and Benchling payload).
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
- The Benchling path is payload-only: it never contacts Benchling, and must stay labelled
  `schema_ready_untested` with the amber "Untested against live API" pill, positioned *below* the
  notebook-bundle button.

## ELN notebook bundle (`POST /api/protocols/export/eln/bundle`)

The "Download for my notebook (.zip)" button (`data-testid="eln-bundle"`) needs no API key — it is
deterministic — but it needs a draft in memory, so plan the order of your tests around that:

- The draft lives only in React state. **Navigating away (e.g. to `/audit`) loses it** and the button
  goes `disabled`. Do all export tests before leaving `/protocol`, or re-draft afterwards. This is
  the single easiest way to waste a 50 s drafting call.
- Filename is server-chosen `<slug-of-title>-eln.zip`, and Chrome silently suffixes ` (1)`, ` (2)`
  for repeats — take a `ls ~/Downloads` inventory before the run so you can tell exports apart.
- Inspect the zip, do not trust the response: `python3 -m zipfile -e <zip> <dir>` should yield
  exactly `IMPORT.txt`, `record.html`, `record.md`, `record.json`, all non-empty. The review notice
  "Requires qualified researcher review before lab use." must appear in all four.
- Step order comes from `order`, renumbered by `reorderSteps()`, so the left-pane ↑/↓ buttons are the
  real oracle: reorder, export again, and diff the Method lists of the two `record.md` files.
- Escaping: type `<script>alert(1)</script> <b>b</b> & <img src=x onerror=alert(2)>` into the goal or
  a step title, export, then grep the HTML — there must be no `<script`, `<img`, `<iframe`, `onerror`
  or `http(s)://` reference; the only tag-ish content is the inline `<style>`. Open the file in a tab
  to confirm literal characters and no dialog.
- Audit: the event is `eln.bundle_exported` with detail exactly `{steps, origin}`. Grep the whole
  feed for the title, a reagent and a step phrase — zero hits expected. A **failed** export writes no
  audit row at all.
- Failure path: `kill -TERM` the uvicorn pid (Vite keeps serving, so its proxy answers **502**). The
  page shows `Request failed (502)`, writes no zip, and leaves the button on its idle label. Note the
  error renders in the **left draft pane**, not beside the bundle button — easy to miss on a
  screenshot cropped to the ELN section. Restart the backend and re-click to prove recovery.
- `POST /api/protocols/export/eln/bundle` with no bearer, or a bogus one, must be **401** with no zip.

## Safety invariant to re-check on any UI change

The `CaveatBand` — "DRAFT — Agent-drafted content. Requires qualified researcher review before lab
use." — must render unconditionally, and the only `data-tone="validated"` pill on the page must be
"Arithmetic verified · this panel only". Enumerate with
`document.querySelectorAll('[data-tone]')` and confirm with a screenshot; a validated-looking pill
next to LLM-drafted steps is a reportable bug, not a cosmetic one.

## Devin secrets needed

- `ANTHROPIC_API_KEY` (repo scope) — drafting and control review only.
