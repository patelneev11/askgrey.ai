# Integration verification — PRs #1–#9

Scope: foundation (#1) and per-tab layouts (#3), PubMed (#2), PubChem (#4), ClinicalTrials.gov
(#5), PDF extraction (#6), export (#7), review table (#8), grants (#9). Verified by reading every
schema boundary and by a manual browser run against a live backend — not by the test suites.

## What works end to end

The Literature golden path runs clean: sign in → Literature → upload a paper → type an extraction
goal → columns generate → click a populated cell → the right pane renders that PDF page with the
quote highlighted → run a second goal → columns merge onto the existing rows rather than replacing
them → export XLSX and CSV, both of which download real files. The XLSX `Review table` sheet and
its linked `Sources` sheet agree: three cited cells on screen produced exactly three source rows.

Schema boundaries hold in practice, not just in unit tests:

- Every provider (PubMed, PubChem, ClinicalTrials, PDF extraction, grants) exposes
  `to_source_record()` into the one shared `SourceRecord`. No provider invented a parallel shape.
- Export consumes `ExtractionTable` from the PDF extraction module directly
  (`ExportRequest.table: ExtractionTable`) — it was reused, not duplicated, and the frontend posts
  the same object the extraction endpoint returned rather than a re-derived table of its own.
- The frontend TypeScript contract in `frontend/src/lib/extraction.ts` matches the backend OpenAPI
  output schemas field for field, including the citation geometry (`bbox`, `rects`, page size) and
  all three enums (`CellStatus`, `RowStatus`, match quality).

Degraded paths behave: a killed backend fails both extraction and export with a readable error and
leaves the existing table intact; oversized, non-PDF and scanned/image-only PDFs produce honest
errors instead of crashing; an empty goal is blocked client-side; a nonsense goal completes with
`not_found` cells rather than inventing values; a PMC link that the browser cannot re-fetch falls
back to the verbatim quote plus a page deep link.

## What was broken, and is now fixed

1. **Literature workspace was destroyed by ordinary tab navigation.** All workspace state lived in
   `LiteraturePage`, which React Router unmounts — clicking Screening and back emptied the table,
   the source list, the goal and the viewer. State now lives in a `WorkspaceProvider` mounted above
   the router outlet; an extraction still in flight also survives the navigation and lands when it
   finishes.
2. **A hung backend hung the UI forever.** `fetch` had no timeout, so with uvicorn `SIGSTOP`ed the
   Generate button sat disabled on "Generating…" indefinitely with no error and no way out. Every
   request now runs under an `AbortController` (30 s default, 180 s for extraction, which is an
   LLM pass per paper) and surfaces a readable timeout error.
3. **Stale error banners blamed the wrong paper.** A failure from a removed source stayed on screen
   while the user queued a different one. Changing the queued sources now clears the banner.
4. **Screening queue rows looked clickable and were not.** They were real `<button>`s with hover
   affordance, but clicking one never changed the profile pane. They are now non-interactive rows —
   there is only one sample profile behind them, so the honest fix was to drop the affordance.
5. **Grants looked live while being entirely hardcoded.** A pulsing "Mock review running" pill and
   "3 opportunities matched" implied the real `/api/grants` endpoints were driving the page. The
   page is now marked "Sample data · /api/grants not wired up yet"; Protocol and Regulatory carry
   the same marker, and Protocol no longer claims it was "last edited 2 hours ago".

## Duplication found and removed

Three services had independently reimplemented the Anthropic Messages API — same URL, headers,
`temperature`, prefill trick, block-joining and error strings, copied three times. They now share
`app/services/llm/AnthropicMessagesClient`; each service keeps its own prompt, prefill and error
type, and the shared client is tested directly.

## Design-token and pattern drift

None found. Panels, buttons and typography are consistent across all nine destinations; acid blue
is used only for pipeline activity, emerald only for passed validation, amber only for warnings.
The one pattern violation was semantic rather than visual — the pulsing "running" pills on static
tabs, which is what the sample-data markers above replace.

## Known limitations (unchanged, by design)

- A browser reload still clears the Literature workspace: papers and tables are in memory only,
  with no persistence layer yet.
- Citations on papers added by PMC link cannot render the page (cross-origin fetch); they fall back
  to the quote and a page deep link. A small backend byte-proxy would fix it.
- Screening, Protocol and Regulatory remain sample data on top of live backends; only Literature
  and the grants API are wired end to end.
- SBIR.gov's live path is unverified from this VM (CloudFront blocks its egress IP); that client is
  fixture-backed.
