# Literature tab hardening — PRs #34, #36, #42

Scope: the known issues carried over from the integration (#1–#9) and UX (#11) passes — no
persistence, PMC citations that cannot render a page, dropped backend signals, exposed jargon,
table clipping on laptop viewports, and several missing explanations. Verified by the test suites
and by a recorded end-to-end browser run against a live backend with a real open-access PDF.

## What was broken, and is now fixed

1. **A reload emptied the tab.** Papers, goal and table lived in memory only. There are now two
   tables — `literature_workspaces` (one row per user: goal, sources, table) and
   `literature_documents` (the uploaded/fetched PDF bytes, keyed by user and document id) — behind
   `GET/PUT/DELETE /api/literature/workspace`. The provider loads once on mount and saves 800 ms
   after editing settles; saving is skipped mid-extraction so a half-filled table is never what
   persists, and a failed save is logged rather than surfaced, since it must not interrupt a
   review. Reload and sign-out/sign-in both restore the workspace.
2. **PMC-link citations could not show the page.** The browser cannot re-fetch a PMC PDF
   cross-origin, so those citations degraded to quote-plus-link. The backend now keeps the bytes it
   already fetched and serves them from `GET /api/literature/documents/{id}/pdf`; the viewer pulls
   a paper's bytes once, on first citation click. This is deliberately **not** a proxy: the route
   takes a bounded document id, looks it up scoped to the calling user, and returns only bytes
   already stored — an unknown or another user's id is a 404, and no caller-supplied URL is ever
   fetched. Generating a new column for a restored upload posts to
   `POST /api/pdf-extraction/documents/{id}` rather than re-uploading bytes the browser no longer
   has.
3. **The table kept describing a paper that was gone.** Removing the only source left its columns
   and cited-value count on screen. Removal now drops that paper's rows, and the last removal
   empties the table — columns without papers describe nothing.
4. **Backend signals were dropped in the UI.** Per-cell `note` was tooltip-only and per-row
   warnings rendered `warnings[0]` and discarded the rest. Notes now render inline under the value
   in muted type; a single warning renders inline and several collapse into a `<details>` listing
   every one.
5. **The review grid broke the page at laptop widths.** `table-layout: auto` let the grid's
   intrinsic width propagate up the flex chain. The grid is now fixed-layout with explicit column
   widths, the horizontal scrollbar lives on its own element, and every flex ancestor got
   `min-width: 0`. At 1280/1366/1440 there is no page-level horizontal scrollbar; the grid scrolls
   inside its pane.
6. **The citation viewer rendered at ~373 px on a 1280 px screen.** The default pane split and
   `.frame` padding were the cause; it is ~481 px measured at 1280 now, and pdf.js already tracked
   the frame width via `ResizeObserver` (now covered by a test).
7. **Jargon leaked into the primary UI.** `p4` → `page 4`, `p4~` → `page 4, close wording`,
   `unverified` → `no source found`, and the match vocabulary is spelled out. The precision is
   demoted, not deleted: the exact terms (`exact`/`normalized`/`fuzzy`, the `p1-b4` block
   reference) live in hover titles and a `<details>` legend.
8. **Nothing explained what was missing or what an export contains.** A disabled `Generate columns`
   now names what is absent (goal, papers, or both); `Export .xlsx` / `Export .csv` each carry a
   one-line description, with the xlsx line calling out the Sources sheet carrying quote and page
   for every cited value; and the goal → column → citation explanation survives as a persistent
   `How this works` disclosure instead of vanishing with the empty state.
9. **A bad source failed silently.** A non-PDF upload or malformed link is now rejected at queue
   time with what to do instead, and a source that fails during extraction is named in the error
   (e.g. a 404 URL) rather than disappearing.
10. **A reload could sign the user out.** Two overlapping `POST /auth/refresh` calls (React
    `StrictMode` double-invoking the restore effect; equally, two tabs restoring at once) replayed
    an already-rotated refresh token, which the server correctly treats as theft and answers by
    revoking the session. Overlapping callers now share one in-flight refresh.

## Security posture of the new surface

- The byte route cannot be an open proxy: bounded id pattern, user-scoped lookup, stored bytes
  only, 404 on anything else. All new routes require the same bearer auth as the rest of the API.
- Workspace writes are bounded by schema (goal length, source count, field lengths) and by quota:
  40 documents and 250 MB of stored bytes per user, 4 MB of serialised table, oldest documents
  evicted first.
- Extraction endpoints are now rate-limited per IP (20/min) in addition to the existing per-account
  limit and daily LLM spend budget, since each call is a paid model pass.
- The URL-fetch path is unchanged and still resolves DNS, rejects private/loopback/link-local
  targets before connecting, re-validates every redirect hop manually, caps the download, and
  returns a generic error rather than upstream connection detail.

## What is now tested

Backend: 570 tests pass. New coverage for workspace round-trip, cross-user isolation, clearing,
schema and quota rejection, oldest-first eviction, stored-byte serving including the cross-user
404, re-extraction from a stored document, and the per-IP limiter.

Frontend: 97 tests pass (lint, typecheck and build clean). New coverage for restore-on-mount, the
debounced save payload, stale-table clearing on removal, re-extraction of a restored upload,
refresh de-duplication, all-warnings rendering, inline notes, the disabled-button explanation, the
export descriptions, and the viewer's width tracking.

Browser: a recorded run on a production build with a brand-new account — upload, goal, generate,
citation click, reload, sign-out/sign-in, both exports, bad link, source removal, and the three
laptop viewport widths.

## Known limitations

- Extraction requires `ANTHROPIC_API_KEY` in the backend environment; without it every extraction
  returns 503. There is no offline fallback path.
- Hover tooltips and the exported Sources sheet still contain the precise vocabulary (`normalized`,
  `p2-b7`). That is deliberate — the export is the audit trail — but it means the jargon is
  reachable, not gone.
- The end-to-end run used a local static+proxy harness for single-origin serving; this branch's
  `main.py` does not serve the SPA, so the real deployment path was not exercised.
- Every extracted value remains model-derived. The UNVALIDATED band above the grid and the caveat
  under the rendered page are permanent for that reason: locating a quote proves where a value came
  from, not that it is correct.
- Screening, Protocol and Regulatory are still sample data; only Literature and grants are wired.
