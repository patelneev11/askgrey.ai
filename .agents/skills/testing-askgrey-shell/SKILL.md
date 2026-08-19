---
name: testing-askgrey-shell
description: How to run and end-to-end test the askgrey.ai app locally (FastAPI backend + React/Vite frontend), including auth, the navigation shell, and the dual-pane workspace.
---

# Testing the askgrey.ai app locally

## Running the stack

```bash
# backend (SQLite dev DB at backend/askgrey.db, auto-created)
cd backend && .venv/bin/uvicorn app.main:app --port 8000
# frontend (Vite, proxies /api -> :8000)
cd frontend && npm run dev      # http://localhost:5173
```

Check both are up before opening the browser:
`curl -s localhost:8000/api/health` → `{"status":"ok",...}`, `curl -sI localhost:5173`.

Gotcha: if a previous session already started them, `npm run dev` silently falls back to
**:5174** and uvicorn prints `address already in use`. Always `pgrep -af "vite|uvicorn"` first
and reuse the running instances instead of starting duplicates, otherwise you may test a
different port than you think.

Every LLM-backed route (extraction, protocol drafting, control review, grant matching, review
board) reads `anthropic_api_key`, which pydantic-settings populates from `ANTHROPIC_API_KEY`, so
the key must be bound to **the uvicorn process**, not merely exported in your own shell:

```
exec(command=".venv/bin/uvicorn app.main:app --port 8000", workdir="<repo>/backend",
     env={"ANTHROPIC_API_KEY": "secret:repo:patelneev11/askgrey.ai:ANTHROPIC_API_KEY"})
```

Never write the key to a file. The deterministic routes work without it; the LLM-backed ones
either 503 or fall back to a rule-based path — which one is per-tab, so check the tab's skill.

If vite fails to start, reinstall the rolldown native binding (an npm optional-dependency bug that
also breaks vitest):

```bash
(cd frontend && npm install --no-save \
  @rolldown/binding-linux-x64-gnu@$(node -p "require('rolldown/package.json').version"))
```

Node 20.18 prints a "Vite requires Node 20.19+" warning and still works — noise unless the build
itself fails.

### Reload-sensitive tests need the single-origin build, not the dev server

Pressing F5 against `:5173` logs you out, so any assertion about state surviving a reload must run
against the built SPA served by FastAPI:

```bash
(cd frontend && npm run build)
cd backend && FRONTEND_DIST_DIR=$PWD/../frontend/dist .venv/bin/uvicorn app.main:app --port 8000
```

### Environment gotchas that cost time

- Chrome's CDP endpoint here is **IPv6-only**: `http://[::1]:29229/json/list`. The IPv4 port hosts a
  different Chrome, as do the Vite listeners.
- `export DISPLAY=:0` before any `wmctrl`/`xdotool` call, otherwise they fail with no display.
- There is **no `sqlite3` CLI** — query the dev DB with `backend/.venv/bin/python` and the stdlib
  `sqlite3` module.
- The login password field intermittently drops a trailing `!`. Type `TestPassword123`, then send
  `shift+1` as a separate keystroke.

## Auth

- Register from the login page: click **"No workspace yet? Create one"**, which reveals a
  *Full name* field above *Work email* — the form fields shift down, so re-locate fields after
  toggling the mode or you will type into the wrong input.
- Password must be **>= 12 characters** (enforced client-side via `minLength` and server-side by
  pydantic). Example working credentials: `grey.tester@example.com` / `TestPassword123!`.
- **Do not use `@*.test` / `@*.example` / `@localhost` email domains.** The backend uses
  `EmailStr` (email-validator), which rejects special-use/reserved TLDs with a 422. Use
  `@example.com` or a real-looking domain.
- The first registered user becomes `OWNER`. Inspect users with:
  `.venv/bin/python -c "import sqlite3;print(sqlite3.connect('askgrey.db').execute('select id,email,role from users').fetchall())"`
- Tokens live in `localStorage` under `askgrey:access-token` / `askgrey:refresh-token`. To force a
  clean logged-out state during *setup* (not during a recording), run `localStorage.clear()` and
  reload.

## UI state that persists in localStorage

| Key | Meaning |
| --- | --- |
| `askgrey:sidebar-collapsed` | `"true"`/`"false"` sidebar rail state |
| `askgrey:pane:<tabKey>` | dual-pane split ratio per tab (`literature`, `screening`, `protocol`, `regulatory`, `grants`, `workspace`, `audit`, `settings`) |
| `askgrey:onboarding:v1` | first-run tour + per-tab notices (see "Onboarding" section below) |

Clear these before testing default behaviour, otherwise a previous run's split/collapse state
makes "default" assertions meaningless.

## Onboarding: first-run tour and per-tab notices

All onboarding state is **browser-local**, so a "fresh user" means clearing
`askgrey:onboarding:v1` — **registering a new account does not reset it**. Shape:

```json
{ "tour": "unseen" | "skipped" | "completed", "step": 0, "acknowledged": ["literature", ...] }
```

- Tour modal renders iff `tour === "unseen"`; counter is `step+1 of 4`, so `step: 2` shows `3 of 4`.
- A tab notice renders iff `tour !== "unseen" && !acknowledged.includes(<routeId>)`. That is the
  no-stacking guard: notices are structurally impossible while the tour is open, so "no notice
  behind the scrim" is guaranteed, not luck.
- `acknowledged` ids are the route names without the slash: `literature`, `screening`, `protocol`,
  `regulatory`, `grants`, `workspace`, `audit`, `settings`.
- Button label is `"I understand"` when the intro has a caveat (literature, screening, protocol,
  regulatory) and `"Got it"` otherwise (grants, workspace, audit, settings).
- Settings → **Replay tour** calls `restartTour()`, which sets `tour: 'unseen', step: 0` but
  **deliberately preserves `acknowledged`** — dismissed tab notices must NOT come back. Assert this;
  resurrecting them would make the button punishing to press.

### Editing localStorage mid-test requires a reload

`OnboardingProvider` seeds React state with `useState(read)` — it reads localStorage **once at
mount**. If you hand-edit `askgrey:onboarding:v1` to re-show a notice, client-side navigation will
NOT pick it up; you must reload the page. Forgetting this looks like "the notice is broken".

### The sharpest tour assertion is resume-at-step-3

`goToStep` writes localStorage on every step change, so advancing to step 3 and reloading must
reopen the tour at `3 of 4`, not `1 of 4`. This single check distinguishes a real per-step write
from a no-op, and is worth more than clicking Next four times.

### The notice overlaps the citation viewer, not the controls

The notice is `position: fixed; right/bottom: var(--space-5); z-index: 30; width: min(24rem, ...)`
— roughly 384×342px pinned bottom-right. Measured overlap:

| Surface | 1440×900 | 1280×800 |
| --- | --- | --- |
| Literature controls (goal input, Generate, Export .xlsx/.csv, Upload) | none | none |
| Citation **PDF canvas** | ~26% covered | ~38% covered |

So judge "does it cover important controls" by comparing `getBoundingClientRect()` rects, not by
eye, and check the **PDF canvas separately** — that is the only thing it actually covers. It is
first-run-only and fully restores on dismissal, which caps the severity.

To prove the card does not swallow pointer/focus events, type into the Extraction goal field while
the notice is showing and confirm the text lands.

## Dual-pane resizer

- Ratio is clamped to **0.2 – 0.8**; each pane also has `min-width: 320px`.
- Drag it with `mouse_move` → `left_mouse_down` (no coordinate arg — `left_mouse_down` rejects
  `coordinate`) → several `mouse_move` steps → `left_mouse_up`. Screenshot mid-drag to prove live
  tracking.
- To assert the exact clamp, read the geometry rather than eyeballing pixels:
  `document.querySelectorAll('main > div > *')` → pane widths, and the separator's
  `aria-valuenow` (integer percent) is the cleanest oracle.
- The separator also supports ArrowLeft/ArrowRight (2% steps), `Home` and double-click to reset.

## Inspecting the sidebar rail icons

Icons are 16px inline SVGs from `frontend/src/components/icons.tsx`. At the default 1024-wide
screenshot scale they are too small to judge. Zoom the *page* (click a neutral spot in the
content area first, then `ctrl+equal` a few times — `ctrl+plus` does not work through xdotool),
then use the `zoom` action on the rail region. Reset with `ctrl+0` before continuing.

## Literature tab / Dynamic Review Table

### Extraction needs a real Anthropic key in the *backend process* env

`Settings.anthropic_api_key` drives `PdfExtractionService.from_settings`. If it is unset the
extractor is `None` and every Generate returns **503**. Exporting the var in your shell is not
enough — the already-running uvicorn keeps its old environment. Restart it with the key bound
into the process, then confirm with `tr '\0' '\n' < /proc/<pid>/environ | grep ANTHROPIC`.

**Devin Secrets Needed:** `ANTHROPIC_API_KEY`.

### Test fixtures

Real open-access PDFs live in `backend/tests/fixtures/pdf_extraction/` (note: `tests/fixtures/…`,
not `tests/pdf_extraction/fixtures/`): `trial_ziprasidone.pdf`, `trial_mipomersen.pdf`,
`trial_linaclotide.pdf`, `trial_silymarin.pdf`, plus `scanned_no_text_layer.pdf` for the
no-text-layer path. A single-paper run against Claude takes roughly **5–20 s**, so wait
generously before declaring a failure, and screenshot within ~2 s of clicking to catch the
in-flight `extracting` pill and skeleton cells.

### Getting a real value out of the run quickly

Before driving the UI, do an API smoke run to learn the *expected* values, so you can assert on
real content instead of "something appeared". Ground truth for `trial_ziprasidone.pdf` with goal
`sample size, primary endpoint`: `73 patients` and the MADRS endpoint, both page 1, match
`normalized`, 2 rects each.

### Behaviours that are by design (do not report as bugs)

- Papers added **by URL** intentionally fall back to a quote + `#page=N` link instead of a raster
  (the bytes are fetched server-side and cannot be re-fetched cross-origin). Assert this with
  `document.querySelectorAll('canvas').length === 0` plus a `<blockquote>` and a link whose href
  ends `#page=N` — a screenshot alone can look like a failed render.
- The table is **in-memory only** — a page reload clears it. Only the sidebar-collapse and
  per-tab pane ratio persist.
- Re-running a *different* goal is expected to **append** columns (`mergeTables` in
  `lib/extraction.ts` appends columns and merges rows by `document_id`); cells a given run did
  not cover show an em dash.

### Workspace state survives in-app navigation (since PR #10), but not a reload

Historically all Literature workspace state was component-local `useState` in `LiteraturePage`,
so a router unmount on tab switch wiped the table. **PR #10 moved it into a `WorkspaceProvider`
(`frontend/src/lib/workspace.tsx`) mounted above the router outlet in `App.tsx`**, so `table`,
`sources`, `goal` and the selected citation now survive Literature → Screening → Literature.

Two things worth knowing when testing this:

- Because `runExtraction` lives in the **provider**, an extraction started in Literature keeps
  running while the page is unmounted and its result lands when you come back. The strongest
  test is: start a multi-column goal, navigate away within ~2 s (screenshot the `extracting`
  pill first to prove it was genuinely in flight), stay away ~30 s, return and assert the new
  columns are populated and the run is no longer pending.
- A **full reload still clears the workspace** — the provider uses `useState`, not storage. This
  is by design; confirm it rather than re-reporting it. Auth, sidebar collapse and pane ratio do
  survive a reload.
- If a regression ever reappears here, the tell is a *partial* fix: the table surviving while the
  citation viewer reverts to the "No passage selected" placeholder. Assert all four (table,
  source chips, goal text, viewer) separately.
- Distinguish the two state classes explicitly, because they behave differently:

```js
({sidebar: localStorage.getItem('askgrey:sidebar-collapsed'),      // survives everything
  pane:    localStorage.getItem('askgrey:pane:literature'),        // survives everything
  rows:    document.querySelectorAll('tbody tr').length,           // survives nav, lost on reload
  chips:   document.querySelectorAll('button[aria-label^="Remove"]').length});
```

### Request timeouts are bounded (since PR #10) — elapsed time is the oracle

`frontend/src/lib/api.ts` wraps every fetch in an `AbortController`: `DEFAULT_TIMEOUT_MS = 30_000`
and `EXTRACTION_TIMEOUT_MS = 180_000` for the two `/pdf-extraction` endpoints. A timeout throws
`TimeoutError` rendering exactly:

```
The server did not respond within {30|180}s. It may be busy — try again.
```

Extraction failures are prefixed with the source label (`trial_x.pdf: ...`); **export failures are
not prefixed**. To test, `kill -STOP` the uvicorn pid and note that the Vite proxy sets no timeout,
so the client abort is what fires:

- **Fast path (~35 s):** trigger an **export** while stopped to exercise the 30 s bound. Screenshot
  at ~20 s to prove it was still `Exporting…` (rules out an unrelated instant failure).
- **Slow path (~3.5 min):** trigger **Generate** to exercise the 180 s bound. A screenshot at ~60 s
  still reading `Generating…` is the key discriminator — if one 30 s bound had been wired
  everywhere, it would already have errored.
- Assert the button returns to its idle label and the existing table stays on screen. Then
  `kill -CONT` and run a successful extraction to prove recovery.

### The error banner clears when the queued sources change

`updateSources` in `workspace.tsx` calls `setError(null)`, so the banner disappears **immediately**
on both add and remove — no extraction needed. Test both paths: a failing source such as
`https://example.org/not-a-paper.pdf` (yields `... returned HTTP 404`) then remove it; re-trigger
the failure and add a *file* instead.

### Verifying exports

Buttons are disabled until a table exists. Downloads land in `~/Downloads` as
`review-table.xlsx` / `review-table.csv`; clear that folder first so anything present is
attributable to the run. The strongest assertion is that the **number of rows in the `Sources`
sheet equals the number of cited cells visible in the UI**, with matching `Value`/`Page`:

```bash
backend/.venv/bin/python -c "
import openpyxl; wb=openpyxl.load_workbook('$HOME/Downloads/review-table.xlsx')
print(wb.sheetnames); [print(r) for r in wb['Sources'].iter_rows(values_only=True)]"
```

CSV should carry a `<label> — source` column per goal phrase, each reading `p<N> · \"<quote>\"`.
Note the separator is an **em dash**, and the file is UTF-8 BOM — read it with
`encoding='utf-8-sig'`.

### Asserting the citation highlight (the part that is easy to get wrong)

Highlights are `[data-testid="citation-highlight"]` absolutely positioned inside `.pageStack`,
siblings of the `<canvas>`. **A non-zero `getBoundingClientRect()` does not mean the user can see
them.** Check the *computed* style too — `mix-blend-mode` and the resolved background:

```js
document.querySelectorAll('[data-testid="citation-highlight"]').forEach(h=>{
  const s=getComputedStyle(h); console.log(s.mixBlendMode, s.backgroundColor);});
```

`mix-blend-mode: screen` with a dark fill is **invisible over a white PDF page** (screen blend
against white always yields white); the shipped fix uses `multiply` with a translucent
`color-mix(... 28%, transparent)` fill. To prove causation on a *broken* build, flip only that
property (`h.style.mixBlendMode='normal'`) and re-zoom — if the band appears, the geometry was
fine and the blend mode is the defect.

#### The strongest proof: compare screen pixels against the canvas's own pixels

Highlights are DOM overlays, so the `<canvas>` still holds the **unhighlighted** raster. That
gives a free before/after at the same coordinates: read the canvas pixel with `getImageData`,
read the real composited screen pixel from a screenshot, and check which prediction it matches.
This distinguishes "painted" from "present in the DOM but invisible" with no code changes.

```js
// in the page: get canvas RGB + the screen coords of the same point
const c=document.querySelector('canvas'), cr=c.getBoundingClientRect(), ctx=c.getContext('2d');
const sx=c.width/cr.width, sy=c.height/cr.height;
const offY = window.outerHeight-window.innerHeight;   // browser chrome; offX is usually 0
const px = ctx.getImageData(Math.round((cssX-cr.x)*sx), Math.round((cssY-cr.y)*sy),1,1).data;
```

```bash
# grab the REAL screen (not the scaled tool screenshot) and sample it
DISPLAY=:1 import -window root /tmp/screen.png   # or: scrot -o /tmp/screen.png
```

Then for `multiply` at alpha `a` over base `b` with source `s`:
`expected = (1-a)*b + a*(b*s/255)`. Sample points **inside** the band and **outside** it; inside
must match the painted prediction and outside must match the raw canvas. On a correct build the
inside deltas come out at 0–1/255, which is unambiguous. Note the tool's screenshot space is
1024x768 while the real display is 1600x1200, so always sample the raw `import`/`scrot` capture
at CSS-pixel coordinates (devicePixelRatio is 1 here, so CSS px == screen px, plus the chrome
offset of ~87 px vertically).

Also note React **reuses** these DOM nodes when you click a different cell, so inline styles you
injected for diagnosis persist across citation switches — remove them explicitly
(`h.style.removeProperty('mix-blend-mode')`) before judging the shipped rendering.

### Proving the PDF actually re-rasterizes on a pane resize

`.canvas` is `width: 100%` of `.pageStack`, so a **stale bitmap still visually fits** the pane
after a resize — a screenshot alone cannot tell a re-raster from a CSS stretch. The only honest
oracle is the canvas's **intrinsic** size (`canvas.width`), which `CitationViewer` sets from the
pdf.js viewport on every render. Capture it before, mid-drag and after release:

```js
const c=document.querySelector('canvas'), cr=c.getBoundingClientRect();
const frame=c.closest('div[class*=frame]'), fr=frame.getBoundingClientRect();
const padR=parseFloat(getComputedStyle(frame).paddingRight);
({intrinsic:[c.width,c.height], cssW:cr.width,
  overflowPx:cr.right-(fr.right-padR), hasHScroll:frame.scrollWidth>frame.clientWidth});
```

A healthy result: intrinsic width changes in the same direction as the pane (e.g. 560 → 278 →
919), `overflowPx <= 0` and no horizontal scrollbar at every width. Measure at **both** a
narrower and a wider width — the old `window.resize`-only bug only clipped when narrowing.

The viewer measures a zero-height `.sizer` div inside the padded `.frame` (measuring the padded
frame itself over-measures by the padding), so compare the canvas against the frame's **content**
box, not its border box.

## Driving the divider precisely

The separator is only **5 CSS px** wide (~3 px in the 1024-wide tool coordinate space), so a
press even 5 tool-px off silently misses it and the drag does nothing. Don't guess from a
screenshot — read its centre and convert:

```js
const r=document.querySelector('[aria-label="Resize workspace panes"]').getBoundingClientRect();
({toolX:(r.x+r.width/2)/1.5625, aria:$0.getAttribute('aria-valuenow')});  // 1600/1024 = 1.5625
```

If `aria-valuenow` is already `20` or `80` you are clamped and further dragging that direction is
a no-op — drag the other way first.

## Testing backend-failure integration states from the UI

There is **no `AbortController` or timeout anywhere in `lib/api.ts`**, which makes "backend down"
and "backend slow" behave completely differently. Test both — they are separate defect classes.

| Scenario | How | Observed behaviour |
| --- | --- | --- |
| Backend **killed** | `kill -9 <uvicorn pid>` | Fails in ~1 s, `role="alert"` banner, buttons return to idle, table preserved |
| Backend **paused** | `kill -STOP <pid>` … `kill -CONT <pid>` | **Hangs indefinitely** (>65 s), button stuck disabled on `Generating…`, no error; recovers and completes correctly on `CONT` |

SIGSTOP is the only way to reproduce the hang — a killed process refuses the connection instantly
and therefore *cannot* surface a missing-timeout bug. Always resume with `kill -CONT` afterwards.

Note the Vite dev proxy converts a refused upstream connection into **`Request failed (500)`**, so
a dead backend shows a generic 500 rather than `Failed to fetch`. Do not read that 500 as a real
server-side error.

### Resolving the uvicorn pid correctly

`pgrep -f` returns a wrapper pid that is **not** the process you can signal. Always resolve with:

```bash
ps -eo pid,stat,cmd | grep "uvicorn app.main" | grep -v grep
```

The `STAT` column is also your confirmation that SIGSTOP landed: `S` = running, `T` = stopped.
A backgrounded `nohup … &` started inside an `exec` call survives, but its pid differs from the
one `pgrep` reports.

### Bad-input matrix (all surface readable messages, table preserved)

| Input | Banner text |
| --- | --- |
| >25 MiB PDF | `PDF is larger than 26214400 bytes` |
| text file named `.pdf` | `file is not a PDF` |
| `scanned_no_text_layer.pdf` | `PDF has no extractable text layer (scanned or image-only); OCR is not supported` |
| empty goal | no error — **Generate stays disabled** (client guard) |
| nonsense goal | run succeeds, new column filled with an em dash |

To attach files the chooser's `accept` filter or the Recent list will not show (e.g. `/tmp/…`),
open the GTK dialog and press **`ctrl+l`**, then type the absolute path and Enter.

## Known rough edges to re-check

- `frontend/src/lib/api.ts` reads `body.detail` as a string; FastAPI 422 responses return an
  **array** of error objects, so validation failures render as `[object Object]` in the login
  error banner. 401/409 (string details) render correctly. If you see `[object Object]`, that is
  this bug, not your input being unparseable. **Still open as of `ac94f55`.**
- Vite HMR errors from earlier edits linger in the console log; do a hard reload before judging
  console cleanliness. A clean load shows only two React Router v7 future-flag warnings. Use
  `console.clear()` to set an explicit baseline before a multi-tab sweep so anything that appears
  is attributable to the tabs you just visited.
- The Literature error banner **is** cleared when sources change (since PR #10). If you ever see a
  banner naming a file you no longer have queued, that is a regression — check the banner text
  names the file you actually just submitted before attributing an error to it.

## The four static Wave-0 tabs (Screening / Protocol / Regulatory / Grants)

None of `ScreeningPage`, `ProtocolPage`, `RegulatoryPage` or `GrantsPage` imports `api` or `fetch`
(verify with a grep before testing). They render hard-coded content, so only assess **rendering,
layout and console cleanliness** — never backend behaviour.

Since PR #10 each of these tabs carries a **"Sample data"** status pill, and the previously
misleading affordances were removed. Regression-check the honest state rather than re-reporting:

- **Screening** queue rows are now inert `<div>`s (were `<button>`s). The valid test is the
  **affordance, not the click outcome** — clicking did nothing before the fix too, so that proves
  nothing. Instead hover a non-selected row and compare pixels against its resting state, and
  assert computed style:

```js
[...document.querySelectorAll('main ul li')].slice(0,4).map(li => {
  const el = li.firstElementChild, cs = getComputedStyle(el);
  return {id: li.innerText.split('\n')[0], tag: el.tagName, cursor: cs.cursor, bg: cs.backgroundColor};
});
// expect tag DIV and cursor "auto" for every row; only the selected row differs in bg
```

- **Grants** should read `Sample data · /api/grants not wired up yet` and `3 opportunities shown`.
  The old pulsing "Mock review running" pill and "3 opportunities matched" are gone. The hard-coded
  IDs (`PA-24-118`, `RFA-TR-25-004`) remain but are now honestly labelled — they are **not** from
  the real `/api/grants` service, which is still backend-only.
- **Protocol** no longer claims "last edited 2 hours ago"; it reads
  `Sample draft in the protocol agent's output shape`.

A quick inertness oracle for any tab: record `performance.getEntriesByType('resource')` length,
interact, and confirm no new `/api/` entries appear.

### Fixed in `ac94f55` — regression-check these rather than re-reporting them

All five were verified fixed in the browser; if any resurfaces, this is where to look.

- **File inputs silently dropping the selection.** `addFiles` used to pass the live `FileList`
  into a *lazy* `setSources` updater while the change handler immediately reset
  `event.target.value`, so React saw an empty list and no chip appeared. Any React upload handler
  here must snapshot `Array.from(files)` **eagerly** before calling `set…`. Symptom: the native
  chooser closes cleanly but no source chip appears and Generate stays disabled. Assert on the
  **chip**, never on the input's `files`.
- **Highlight blend mode** — was `screen` over a white raster (invisible); now `multiply` with a
  translucent fill.
- **Pane-resize re-render** — was `window.resize` only; now a `ResizeObserver` on `.sizer`.
- **Match styling** — `ReviewTable.tsx` used to paint acid-blue only for `match === 'exact'`, but
  real Claude runs return `normalized` almost every time, so every cell showed the amber `p1~`.
  Now `approximate = match === 'fuzzy'`, so `normalized` renders acid-blue `p1` (`rgb(46,217,255)`,
  class `pageRef`) with a green "normalized match" pill. When checking this, assert on the span's
  **textContent and class**, not just colour — `p1` vs `p1~` is a one-character difference that is
  easy to misread in a screenshot.
- **Duplicated error label** — the banner used to read `<url>: <url> returned HTTP 404`. Assert by
  *counting* occurrences (`text.split(url).length-1 === 1`), not by eyeballing.

## Testing the grants service (`/api/grants`, backend-only)

These endpoints have **no UI** in the grants-service commit, so test them with curl/python, not a
browser, and do not record a screencast for them.

```bash
# token
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"review.tester@example.com","password":"TestPassword123!"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s -H "Authorization: Bearer $TOKEN" "localhost:8000/api/grants/search?keyword=organoid&source=grants_gov&page_size=5"
```

### Controlling the ranker

There is **no `backend/.env`**, so `ANTHROPIC_API_KEY` in the uvicorn *process* env is the only
thing that selects the ranker (`GrantsService.from_settings`). To exercise the deterministic
fallback, restart with `env -u ANTHROPIC_API_KEY .venv/bin/uvicorn ...`.

Two traps when restarting:

- `pkill -f "uvicorn app.main"` also matches your own shell command and kills the exec call. Use
  `pkill -f "app.main:app"` from a command that does not itself contain that string, or accept the
  killed shell and just verify afterwards.
- `pgrep -f` matches wrapper/bash pids whose env still holds the key, so checking
  `/proc/<pid>/environ` on the wrong pid gives a false positive. Resolve the pid with
  `ps -eo pid,cmd | grep "app.main:app" | grep -v grep` and check *that* pid.

### `matcher` does NOT tell you which ranker ran

`FallbackMatchRanker.name` is built once at construction (`matching.py:298`), so `matcher` reads
`claude+lexical` whenever a key is set — **even if the Claude call failed and lexical produced the
ranking**. Never treat `matcher` as proof Claude ran. Discriminate on output shape instead:

| | Claude | Lexical |
| --- | --- | --- |
| `matched_terms` | empty | populated |
| `rationale` | free prose | contains `"no LLM configured"` |

### Provider reachability

- grants.gov (`POST https://api.grants.gov/v1/api/search2`) is reachable and needs no key.
- SBIR.gov (`https://api.www.sbir.gov/public/api/solicitations`) returns CloudFront **403**
  (`x-amzn-errortype: ForbiddenException`) from Devin VMs. This is an egress/WAF block, so the SBIR
  half can only be tested as *degradation* (`sources[].ok == false`, request still 200). Re-curl it
  each run — if it ever returns 200, the SBIR path becomes testable live.
- There are **two different** SBIR failure branches: the WAF 403, and an
  `agency=NIH`-style sub-agency alias that short-circuits to `ok:false` *before* any HTTP call
  (`service.py:240-248`). Test both; a WAF block can otherwise mask the second.

### Filter oracles that actually catch a no-op filter

Always compare two contrasting runs — a filter that is ignored returns the *same* rows.

- `program` values are **uppercase** `SBIR|STTR|BOTH|OTHER`. Lowercase `sbir` and `sbir_sttr` are
  422. A `BOTH` opportunity legitimately satisfies an `SBIR` *or* `STTR` filter.
- grants.gov `agencies` matches the **exact** code, with no prefix expansion. So an alias mapping to
  a bare department code can silently return zero — verify any agency alias against
  `POST search2 {"agencies":"<code>"}` directly before trusting it.
- Date-window and `program` filters run **locally**, so `total_count` is an upper bound measured
  *before* them; never assert `len(opportunities) == total_count`.
- Sorting is deadline-ascending, so `open_only=false` is *not* a strict superset of `open_only=true`
  at a fixed `page_size` — old closed items crowd out open ones on page 0.
- Ground the data itself: re-fetch one opportunity with
  `POST https://api.grants.gov/v1/api/fetchOpportunity {"opportunityId":<id>}` and compare
  title/close date. This is what catches fabricated or mis-normalized values.

---

## Running a UX / first-time-user review (as opposed to a correctness pass)

A UX pass has a different failure mode from a correctness pass: the app *works*, so it is easy to
write a report full of "passed". Force the persona — a user who does not know what a "goal" is,
what "grounded" means, or which tabs are real — and judge each screen on **"what do I do next, and
is that obvious from the screen alone?"**

### Get a genuine first-run state

Sign out and **register a new account** (`ux.newcomer+<ts>@example.com`). Reusing an existing
account hides the real first authenticated screen. Also clear persisted layout state, or earlier
testing will confound responsive measurements:

```js
Object.keys(localStorage).filter(k => k.startsWith('askgrey:pane')).forEach(k => localStorage.removeItem(k));
localStorage.setItem('askgrey:sidebar-collapsed', 'false');
```

Then reload — Literature returns to its default pane ratio of `0.58`.

### Copy worth knowing before you start

The two empty states (`LiteraturePage` "No columns yet" and `CitationViewer` "No passage selected")
are the **only** places the app explains the goal→column model and that cells are clickable. Both
are destroyed as soon as data exists and never return. Any UX review should check whether the
explanation survives first use — this is usually the highest-value finding on the tab.

### Signals the backend sends that the UI may not show

Worth re-checking after any `ReviewTable` change:

| Signal | Where it surfaces | Trap |
|---|---|---|
| cell `status` | `unverified` tag / em dash | visible |
| citation `match` | `normalized match` pill, `p1` vs `p1~` | visible but jargon |
| cell `note` | **`title=` tooltip only** | invisible without hover |
| row `warnings` | **only `warnings[0]` rendered** | extras silently dropped |

Test `note`/`warnings` visibility by screenshotting the cell **at rest**, then hovering, and
comparing. "It's in the DOM" is not the same as "the user sees it".

### Responsive testing — measure the viewport, not the window

There are **zero width media queries** in the codebase (only `prefers-reduced-motion`), so nothing
adapts by width; every size needs evidence. Window size ≠ CSS viewport because of browser chrome:

```bash
export DISPLAY=:0            # wmctrl fails with "Cannot open display" without this
wmctrl -r :ACTIVE: -e 0,0,0,<W>,<H>
```

then verify and iterate until `window.innerWidth/innerHeight` hit the target exactly.

Distinguish **document-level overflow** (a real break) from **intentional internal scrolling**
(the review table's own scroll container). The useful oracle is hidden width, not "is there a
scrollbar":

```js
const sc = document.querySelector('table').closest('div');
({ scrollW: sc.scrollWidth, clientW: sc.clientWidth, hidden: sc.scrollWidth - sc.clientWidth })
```

Review-table columns are `min-width: 200px`, so 3+ columns clip on every laptop size. Collapsing
the sidebar recovers 176px (232px → 56px) and is roughly the difference between usable and not at
1280. Measure the citation `<canvas>` CSS width too — below ~400px the PDF text is unreadable.

### Comparing design-token consistency

Measure rather than eyeball, then report only what is visible. Three header systems exist:
`Panel` (Literature/Screening/Protocol/Regulatory), `PageCanvas` (Workspace/Audit/Settings), and a
bespoke header on Grants. Reference numbers at a fixed viewport on `684c20c`:

- `PageCanvas` page title 20px / header 88px · Grants title 26px / header 73px · `Panel` title 13px
  / header 48px (a panel title is a different role — do not report it as drift).
- `StatusPill` is shared and pixel-identical everywhere: 22px tall, 11px type, 8px horizontal
  padding, 999px radius. Find instances via the CSS-module class prefix, since the text is often
  split across nodes:

```js
[...document.querySelectorAll('main *')].filter(e => /_pill_/.test(String(e.className)))
```

Text matching on `textContent` alone returns ancestor wrappers — always take the leaf.

### Triggering bad-input UX (not just the error string)

Non-PDF files are hidden by the chooser's `accept="application/pdf"`; type an absolute path into
the GTK chooser's location entry (`ctrl+l`) to attach one anyway. Note that both a `.txt` file and
a junk string like `not-a-url` are **accepted into the source queue as chips** and only rejected
after Generate — the delayed validation is itself the finding, separate from the message wording.

### Disclaimers

Grep is a legitimate *starting* point for absence (`predict|approximat|unvalidated|requires review|
caveat`), but the deliverable is a screenshot of the screen showing no caveat. Screening's
predicted pKi/ADMET/toxicity values and Protocol/Regulatory's drafted IND/CTD text are the
surfaces where a missing "unvalidated / requires researcher review" warning is highest-consequence.
Note that a `Sample data` pill speaks to *provenance*, not *reliability* — it does not discharge
the disclaimer requirement.

## Encrypted document storage + audit trail (tickets #23/#24, PR #74)

### Serve the built SPA single-origin when the test involves a reload

Reload-persistence assertions are untestable on the Vite dev server, because F5 at `:5173` can log
you out (StrictMode double-mount → `auth.refresh_reuse` denied). Build once and let FastAPI serve
it, then do all browser work at `:8000`:

```bash
(cd frontend && npm run build)
(cd backend && ANTHROPIC_API_KEY=… FRONTEND_DIST_DIR="$PWD/../frontend/dist" \
   .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000)
```

F5 at `:8000` keeps the session. Verify that before trusting any "survives reload" result.

### Inspecting the DB: there is no `sqlite3` CLI

Use the venv interpreter and the stdlib module instead:
`backend/.venv/bin/python -c "import sqlite3; ..."` against `backend/askgrey.db`.

### Proving `literature_documents.content` is really ciphertext

Four independent checks, all cheap — don't stop at the first:

- `content[:5] != b"%PDF-"` **and** `b"%PDF" not in content` (a partially-encrypted blob still
  contains the marker somewhere).
- `len(content) == byte_size + 28` — a 12-byte nonce plus a 16-byte GCM tag. If the length *equals*
  `byte_size`, plaintext is being stored.
- Distinctive plaintext from the paper (e.g. `b"Ziprasidone"`, an extracted value) is absent.
- **The strongest discriminator:** upload the *same* PDF from two accounts. `document_id` is a digest
  of the bytes, so both rows share it — but the two `content` blobs must **differ**, which is what
  actually demonstrates a fresh nonce and AAD bound to `user_id:document_id`. Identical blobs would
  mean deterministic encryption even though every other check above passes.

Round-trip matters too: the owner's `GET /api/literature/documents/{id}/pdf` must return `200` with
a body starting `%PDF-`, or you've proven storage is opaque but not that it's *recoverable*.

### Cross-account 404s: compare the response *bytes*, not just the status

The security property is indistinguishability, so assert the foreign-but-existing id and a
never-existing id (`deadbeefdeadbeef`) return byte-identical bodies:

```python
s1,_,b1 = req(f'/api/literature/documents/{A_DOC}/pdf', B_TOKEN)   # expect 404
s2,_,b2 = req('/api/literature/documents/deadbeefdeadbeef/pdf', B_TOKEN)
assert s1==s2 and b1==b2   # b'{"detail":"no such document"}'
```

Use **B's own bearer token** from B's own login, not a cookie lifted from A's browser session.
Two traps: run these while A's document still **exists** (otherwise a 404 proves absence, not
isolation), and never let B upload the same PDF first — the byte-digest id would collide and a `200`
would legitimately be B's own copy.

Deletion is scoped the same way. After the owner deletes, another account's row holding the *same*
`document_id` must survive — that's what shows delete is per-user rather than keyed on the digest.

### Make "no prompt/document text leaks into the audit log" greppable

Plant a sentinel in the extraction goal (e.g. `sample size, primary efficacy endpoint,
QTCSENTINEL9142`). It becomes a real column, so it travels the whole prompt path; then assert the
string is absent from both the raw `GET /api/audit/events` JSON and the rendered `/audit` text.
Also check extracted values, `sk-ant`, `Bearer `, the literal `ANTHROPIC_API_KEY`, and a `"goal"`
key inside `detail`. `AuditPage.tsx`'s `detailOf` prints **every** `detail` key verbatim on screen,
so a new backend detail field surfaces in the UI without a frontend change — re-check the rendered
page, not only the JSON.

**Expected `detail` keys are provenance only:** `document_id`, `bytes`, `vendor`, `model`, `source`,
`format`, `rows`, `documents_deleted`. Note `source` is the **filename**, so a paper's subject can
appear in the audit feed via its own filename (e.g. `trial_ziprasidone.pdf`) — that is user-supplied
provenance rather than document text, but flag it if filenames could be sensitive.

### Giving the Exports filter something real without a browser

Exports are audited server-side, so POST the *real* table straight from the saved workspace:

```python
ws = GET /api/literature/workspace            # -> {'goal','sources','table','stored_document_ids'}
POST /api/export/xlsx  {'table': ws['table']} # -> 200, body starts b'PK', logs export.downloaded
```

`kind` bucketing lives in `services/audit.py`: `export` markers win, then `agent`
(`sent_to_llm`, `llm.`, `extraction.`, `budget_`), else `human`. Good API-level filter oracle:
`agent` → only `document.sent_to_llm`; `human` → auth events + `literature.document_read`;
`export` → only `export.downloaded`. Identical counts across all three means the filter never
reached the API.

Note `auth.register` renders as "Created this workspace" and `auth.refresh` as "Renewed a session" —
registering via the UI auto-signs-in, so a fresh account shows **no** separate "Signed in" row until
an explicit login. Don't report that as a missing login event.

Retention text is API-driven: `/audit` shows `retention_days` (**365**, `audit_retention_days`),
while document `expires_at` uses `DOCUMENT_RETENTION_DAYS` (**90**). Two different windows — don't
conflate them.

## When the X server dies mid-run

This box has twice lost the whole GUI stack mid-session (uvicorn, Chrome and X all gone;
`/tmp/.X11-unix` empty; `computer` returns "Computer-use engine is not yet initialized"). You can
restart uvicorn yourself, but **re-provisioning X is not something the agent can do** — escalate it.

Salvage the recording from the raw segments; the final segment is usually truncated
(`ffmpeg.log` ends `received signal 15`) and needs a remux before it will concat:

```bash
ffmpeg -y -i <run>-raw-001.mkv -c copy /tmp/fix001.mkv     # "File ended prematurely" is expected
printf "file '<abs>/…-raw-000.mkv'\nfile '/tmp/fix001.mkv'\n" > /tmp/cc.txt
ffmpeg -y -f concat -safe 0 -i /tmp/cc.txt -c:v libx264 -crf 26 -pix_fmt yuv420p salvaged.mp4
```

The salvaged file has **no annotation overlays** (those are added by the editing pass that died), so
say so when handing it over. Prefer finishing blocked steps API-only and labelling the UI portion
untested over silently dropping them.

### Uploading a PDF without the GTK chooser

The native chooser doesn't hand files back to Chrome here; set the file input over CDP
(`/home/ubuntu/cdp_setfile.py`, which calls `DOM.setFileInputFiles`). Its target filter must match
the port under test — it defaults to matching `localhost:` so it works at both `:5173` and `:8000`.

Chrome's CDP endpoint has appeared on **both** `http://[::1]:29229/json/list` (IPv6) and
`http://127.0.0.1:29229/json/list` (IPv4) on different boots. If the helper fails with connection
refused, check `ss -ltnp | grep 29229` and swap the host rather than assuming Chrome is down.

### If Chrome died (renderer crash) but X is still up

Check `ls /tmp/.X11-unix` first: if `X0` exists, X is fine and only Chrome needs restarting — you do
not need the platform to re-provision anything.

```bash
DISPLAY=:0 setsid nohup /home/ubuntu/.local/bin/google-chrome --remote-debugging-port=29229 \
  --remote-allow-origins='*' --no-first-run --no-default-browser-check \
  --user-data-dir=/home/ubuntu/.config/google-chrome > /tmp/chrome.log 2>&1 < /dev/null &
```

Reusing the same `--user-data-dir` preserves the login **and** the Literature extraction state, so
you usually land straight back on a populated workspace and can skip re-upload/re-extraction. Two
follow-ups: dismiss the "Restore pages?" bubble and the onboarding tour, and note that
`wmctrl -r :ACTIVE: -b add,maximized_vert,maximized_horz` *does* work against this Chrome.

**Caveat that will cost you time:** the platform `browser_console` tool fails with "Could not connect
to Chrome via CDP" against a Chrome you started by hand, even though the `computer` tool still
screenshots and clicks it fine. Drive JS evaluation over CDP yourself instead —
`/home/ubuntu/cdp_eval.py '<js expr>'` evaluates with `awaitPromise`/`returnByValue`, so
`(async()=>{...})()` works and is what you want for multi-second sampling loops.

### Backgrounded servers keep dying with the shell (exit -1)

Under memory pressure the `exec` shells here get killed (`exit code: -1`), taking any `cmd &`
child with them, so the backend silently never comes up. Start long-lived servers from a
**detached script** instead, then poll health separately:

```bash
cat > /tmp/start_real.sh <<'EOF'
#!/bin/bash
pkill -9 -f 'uvicorn app.main:app' >/dev/null 2>&1; sleep 3
cd /home/ubuntu/repos/askgrey/backend || exit 1
export FRONTEND_DIST_DIR='/home/ubuntu/repos/askgrey/frontend/dist'
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
EOF
chmod +x /tmp/start_real.sh
(setsid nohup /tmp/start_real.sh > /tmp/uv.log 2>&1 &)
```

### Forcing an LLM failure: the `env` parameter will NOT override the session secret

`ANTHROPIC_API_KEY` is auto-injected into every shell, and it **wins over** the `exec` tool's
`env` parameter. A "forced failure" started that way silently runs against the *real* key and
returns `200`, which looks like the failure path is broken when it is really untested. Override on
the command line and always verify before trusting the result:

```bash
exec env ANTHROPIC_API_KEY='sk-ant-api03-BOGUS…' .venv/bin/uvicorn app.main:app --port 8000
tr '\0' '\n' < /proc/$(pgrep -f 'uvicorn app.main:app' | head -1)/environ | grep ANTHROPIC
```

A bogus-but-well-formed key is the path that produces an audited failure: the board reports itself
`available`, attempts the call, gets `Claude returned HTTP 401`, returns **502** with the detail in
`ApiError`, and audits `grant_section.sent_to_llm` with `outcome=failure`. An **absent** key instead
503s and audits *nothing* by design — so use a bogus key, not no key, to test failure auditing.

### Diagnosing a blank pdf.js citation canvas (recurring bug)

Symptom: the citation pane header reads `quote found on this page`, highlight rects are positioned
correctly, but the `<canvas>` stays at its browser-default **300x150** intrinsic size and paints
nothing, with **no** error text (`CitationViewer` only renders `error` when the `catch` runs; the
`width === 0` and `cancelled || !canvas || !context` branches return silently).

Storage, asset paths and CSP have all been ruled out in past runs — don't re-litigate them. The
fast discriminator is to **count worker fetches**, which exposes a respawn loop:

```js
performance.getEntriesByType('resource').filter(e => /pdf\.worker/.test(e.name)).length
```

A healthy render fetches the worker once or twice. Seeing the resource buffer saturated (240 of 250
entries in ~7 s) means pdf.js is being re-instantiated tens of times per second: `getDocument()`
never settles, so `canvas.width` is never assigned, and the renderer eventually OOMs (`Aw, Snap!`,
error code 5) — which on this box also takes down Chrome, X and uvicorn. Note that the effect's
cleanup only sets `cancelled = true`; it never calls `doc.destroy()`/`worker.destroy()`, so every
re-run leaks a worker. Check whether `fitWidth` is oscillating (a scrollbar toggling flips the
frame width, retriggering the `[file, citation, width]` effect) before blaming the file identity —
`fileFor` is memoised on `filesByDocument` and the PDF is fetched once.

**Root cause and fix (resolved at `ea2b06c`; keep this as the reference pattern).** The oscillation
was a *self-referential layout loop*, not sub-pixel jitter: `.frame` had `overflow: auto`, so the
scrollbar's appearance narrowed the frame → the page re-fitted smaller → the shorter page stopped
overflowing → the scrollbar left → the width swung back, forever, spawning a worker per swing. The
swing was between **integer** widths exactly one scrollbar apart (measured 625px ↔ 635px), which is
why an earlier `Math.floor` fix did nothing. Two things fixed it: `scrollbar-gutter: stable` on
`.frame` (the gutter is reserved whether or not the page overflows, so width no longer depends on
content height) and a `Set` of already-painted widths that refuses to raster the same width twice.

If a blank canvas ever returns, measure in this order — each step distinguishes a different cause:

```js
// 1. is the width oscillating? sample repeatedly; a healthy pane reports ONE distinct value
const ps = document.querySelector('[class*=pageStack]');
setInterval(() => console.log(ps.style.width), 250);   // two values ~10-17px apart = the loop
// 2. did it actually paint pixels? a correctly-SIZED but white canvas must not pass
const c = document.querySelector('canvas'); const d = c.getContext('2d')
  .getImageData(0, 0, c.width, c.height).data;
let painted = 0; for (let i = 0; i < d.length; i += 4 * 97)
  if (d[i + 3] > 0 && !(d[i] > 245 && d[i + 1] > 245 && d[i + 2] > 245)) painted++;
```

Healthy reference numbers at a ~580px pane: `canvas.width/height` ≈ `582x751`, ~1600 of ~4500
sampled pixels painted, **2** worker fetches, one distinct `.pageStack` width, `load` well under 1.
Raise the buffer first (`performance.setResourceTimingBufferSize(3000)`) or a loop will saturate it
and hide its own size. Always `performance.clearResourceTimings()` right before the click you are
measuring, otherwise you attribute an earlier render's workers to this one.

Two traps when asserting the *fixed* behaviour:

- **A settled width is not proof on its own.** `!rendered && !error` renders `Rendering page N…`.
  Assert that this text is **absent** as well as `role="alert"` count 0 — "no alert" was the old
  silent-failure signature, so it is only good news when the placeholder is gone too.
- **Zoom-out intentionally does not re-raster.** Returning to a width already in the painted set
  early-returns, so `canvas.width` keeps the *larger* raster while `.pageStack` shrinks (e.g. canvas
  stays `1137x1468` at a 758px pane). The canvas is `width/height: 100%`, so this only ever costs
  sharpness. Do not file it as a stale-canvas bug — but do check the pane is not stranded on
  `Rendering page N…`, which is the one way that early return could theoretically strand it.
- A continuous splitter **drag** passes through many intermediate widths and rasters each once, so
  expect a bounded bump (~8 workers for one drag), not 1. What matters is that it **stops growing**
  once you release.

### API-only payload shapes (for when the browser is unavailable)

These bit me; the validation errors are the only documentation:

- `BoundingBox` is `{x0, top, x1, bottom}` — *not* `x0/y0/x1/y1` and *not* `left/top/right/bottom`.
- `ExtractionCell.status` ∈ `grounded | ungrounded | not_found` (not `extracted`).
- `PreclinicalReport` input: `DoseGroup` uses `label` (not `name`), `dose` is a
  `Quantity {value, unit}`, `glp_status` ∈ `compliant | non_compliant | not_reported`.
- `POST /api/library` re-validates `payload` against the model that produced it, so you must feed
  it a genuine endpoint response; hand-written payloads 422. Kinds are a closed set
  (`screening_*`, `regulatory_preclinical|regulatory_ind`, `grants_eligibility|budget|review_board`).
- A fresh `POST /api/auth/login` is a reasonable stand-in for F5 when proving the saved library is
  server-side: list `/api/library`, then `GET /api/library/{id}` and compare the payload for
  equality against what was saved.
- The xlsx export writes two sheets — `Review table` and a `Sources` sheet carrying page, quote,
  block id and position — so verify with `openpyxl`, not by grepping `xl/sharedStrings.xml`.
