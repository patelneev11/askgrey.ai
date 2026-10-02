---
name: testing-screening-tab
description: How to end-to-end test the askgrey.ai Screening tab (/screening) — SMILES profiling, the "Review first" digest, anchor links into evidence, ADMET card ordering and ungrounded-property handling — including how to compute exact deterministic oracles from the backend services and how to isolate your run when the shared checkout moves.
---

# Testing the askgrey.ai Screening tab

`/screening` takes a SMILES string and renders a right-hand "Compound profile" pane:
a **Review first** digest, then `Toxicity & liability flags`, `Identity`, `Computed descriptors`,
`Drug-likeness rule sets` and `ADMET prediction`.

## Why this tab is the easiest one to test rigorously

**Screening needs no LLM key.** Descriptors (RDKit) and ADMET (published physicochemical rules +
QSAR models) are fully deterministic, so you can compute the *exact* expected screen contents
before opening the browser and assert strings and counts rather than eyeballing. Only
**"Suggest modifications"** and the **patent search** need `ANTHROPIC_API_KEY`.

### Compute the oracle first (do this before any browser work)

Note the service module paths — they are nested, and guessing `app.services.sar` fails:

```python
# backend/.venv/bin/python
from app.services.screening.sar.service import SarService     # .profile(smiles)
from app.services.screening.admet.service import AdmetService # .evaluate(smiles)
sar = SarService.from_settings(); adm = AdmetService()
d = sar.profile(smiles); a = adm.evaluate(smiles)
```

Then replay the digest algorithm from `frontend/src/lib/screening.ts` (`screeningConcerns`):
liability flags (`available and outcome=='unfavourable'`, plus `alerts` where `matched`) →
borderline available estimates → non-compliant `d.rule_sets` → unavailable estimates and
`d.unavailable` descriptors. `actionable` = everything except the unavailable/ungrounded rows.

The summary line is built from two counts, so assert it verbatim, e.g.:

> `8 items fired or sit outside a published threshold; 2 properties could not be grounded at all. Each row links to the evidence below.`

Useful fixtures (stable at time of writing):
- **Terfenadine** `CC(C)(C)c1ccc(cc1)C(O)CCCN1CCC(CC1)C(O)(c1ccccc1)c1ccccc1` — liability-heavy:
  10 digest rows (8 actionable + 2 ungrounded), 11 ADMET cards (6 unfavourable → 1 unavailable → 4 favourable).
- **Aspirin** `CC(=O)OC1=CC=CC=C1C(=O)O` — 3 rows (1 borderline in-vivo-tolerability + 2 ungrounded).

## The trap: "benign" compounds are not zero-concern

Do **not** assume an example like Aspirin exercises the digest's empty state. Two properties
(`binding_affinity` and the CYP1A2/CYP2C19 estimate) are ungrounded for essentially every
structure, and the `general_toxicity` (3/75) estimate lands `borderline` for most small molecules
while `bbb_penetration` flags most polar ones. Across **20** probed structures (the 4 example
buttons plus methane, ethanol, water, benzene, glycine, urea, acetamide, paracetamol, metformin,
mannitol, glucose, ascorbic acid, citric acid, glycerol, sorbitol, sucrose, adenosine, cytosine,
ribose, taurine) **none** had `actionable == 0`, and none had zero ungrounded properties.

Consequences to report honestly rather than claim as passing:
- the digest's `concerns.length === 0` branch ("…That is not a safety assessment — it means only
  that nothing on the screened list is present.") appears **unreachable / dead code**;
- the `'Nothing fired'` half of the summary ternary is likewise unreachable.

A requirement worded "if nothing fired it must still say it is not a safety assessment" is
therefore **not verifiable from the UI**. Note separately that an equivalent disclaimer *does*
render in the `Toxicity & liability flags` section when no alert matches ("…it is not a safety
assessment, and a patch-clamp or in vivo study is the only thing that clears a compound") — do not
confuse the two.

## Above-the-fold claims: measure the inner pane, not the window

The profile pane scrolls **inside** a container, not the document. `window.scrollY` stays `0` and
`document.scrollingElement.scrollTop` is useless. Find the real container and measure against it:

```js
const pane = document.querySelector('[class*="_body_"]');   // overflowY:auto, the real scroller
const pr   = pane.getBoundingClientRect();                  // visible region, e.g. top 113 → bottom 750
const rows = document.getElementById('screening-review').querySelectorAll('li');
// a row is genuinely visible only if b.top >= pr.top && b.bottom <= pr.bottom
```

`pane.clientHeight` is markedly smaller than `innerHeight` (637 vs 771 in one run) because of the
app header, workspace header and the "Saved"/"Unvalidated" bands above the digest. Always report
**how many rows fit and which ones are cut, by pill type** — whether only ungrounded rows are cut
or actionable ones too changes the fix. The result is strongly height-dependent, so quantify at
more than one viewport height:

| CSS viewport | rows fully visible (Terfenadine, 10 rows) | cut |
|---|---|---|
| 1408 × 771 | 5 of 10 | 2 × flag, 1 × borderline, 2 × not available (288 px scroll) |
| 1376 × 1071 | 9 of 10 | 1 × not available |

Resize via `wmctrl` and remember `DPR=2` on this box, so CSS px ≈ physical/2:
`export DISPLAY=:0; wmctrl -i -r <winid> -e 0,0,0,2816,2400` → CSS ≈ 1408 × 1071.

## Anchor links

The digest rows link to `#screening-liabilities`, `#screening-rules`, `#screening-admet` and
`#screening-identity` (`SCREENING_ANCHORS` in `frontend/src/lib/screening.ts`). They are
**section-level**: clicking the "CYP1A2 … not available" row lands on the top of `ADMET prediction`,
not on that specific card, so the reader still scrolls to the card. Grade that as spec-conformant
but worth mentioning.

Gotchas when driving this by mouse:
- **Re-profiling does not reset the pane's scroll position**, and the old `location.hash` persists.
  Scroll the pane to the top and *verify* with `getBoundingClientRect()` before computing click
  coordinates — a stray click in the detail sections looks exactly like a successful anchor jump.
- Confirm a jump by reading `location.hash` **and** the target's `top`, not by the screenshot alone.
- Check document order with `review.compareDocumentPosition(liabilities) & 4` to prove the digest
  really precedes the detailed sections.

## Ungrounded properties must not read as adverse

Assert both the wording and the pill *tone*, not just presence: the pill class should be
`_idle_*` (grey) rather than `_warning_*` (amber). The good-state strings are
"Not available — no fabricated value is shown here.", a "WOULD REQUIRE …" line, and a
BINDING AFFINITY entry in `Identity` saying it "will not publish a number it cannot ground".

## ADMET ordering

Expected rank order is `unfavourable(0) → borderline(1) → unavailable(2) → favourable(3)`. Read it
straight off the DOM and assert monotonicity:

```js
const grid = document.querySelector('[class*="_estimates_"]');
// per child: label = [class*="estimateLabel"], pill = [class*="_pill_"]
```

## Isolate your run: the shared checkout may move under you

The lead often switches branches in `/home/ubuntu/repos/askgrey` while you test, which silently
swaps the code Vite serves — the symptom is that `document.getElementById('screening-review')`
returns `null` and the page looks like an older revision. **Always re-check
`git rev-parse --abbrev-ref HEAD` before trusting a surprising UI result.**

Pin your own copy instead of fighting over the checkout (this only touches `.git` metadata, not the
lead's working tree):

```bash
cd /home/ubuntu/repos/askgrey && git worktree add /home/ubuntu/pr-wt <branch>
ln -s /home/ubuntu/repos/askgrey/frontend/node_modules /home/ubuntu/pr-wt/frontend/node_modules
cd /home/ubuntu/pr-wt/frontend && setsid nohup npx vite --port 5174 > /tmp/fe-wt.log 2>&1 < /dev/null &
```

Symlinking `node_modules` avoids a second `npm install` (and the rolldown-binding workaround).
Point the browser at `:5174`; the backend on `:8000` is shared and the session cookie carries over
because **cookies are per-host, not per-port**, so you stay logged in and need not re-register.

Also note a plain Vite reload/HMR clears the profile (nothing is persisted until "Save to library"),
so re-profile after any reload before asserting.

## Keeping the console check meaningful

Your own `console.log` debugging drowns the log. Do a hard reload (`ctrl+shift+r`), redo just the
profile action, then read the console. A clean tab shows only `[vite]` lines, the React DevTools
notice and `api.ok` debug events. For asset 404s prefer:

```js
performance.getEntriesByType('resource').filter(r => r.responseStatus >= 400)
```

## Devin Secrets Needed

- `ANTHROPIC_API_KEY` — **only** for "Suggest modifications" and the patent search. Everything
  described above works without it.
