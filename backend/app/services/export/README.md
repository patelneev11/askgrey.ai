# Export

Renders an `ExtractionTable` (the review-table schema from the PDF extraction module) into a
downloadable `.xlsx` or `.csv`.

```python
from app.services.export import ExportService, ExportFormat, ExportOptions

file = ExportService().render(table, ExportFormat.XLSX, ExportOptions(filename_stem="ctd-lit"))
file.filename      # "ctd-lit.xlsx"
file.media_type    # "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
file.content       # bytes, ready to stream
```

The service is stateless and synchronous — rendering is pure CPU over an in-memory table — so
unlike the provider services there is no `from_settings()` and nothing to close.
`ExportService.xlsx(table, options)` / `.csv(table, options)` are the direct equivalents of
`write_xlsx` / `write_csv`.

| Callable | Purpose |
| --- | --- |
| `write_xlsx(table, options)` | `ExtractionTable` → workbook bytes. |
| `write_csv(table, options)` | `ExtractionTable` → RFC 4180 CSV bytes. |
| `build_rows(table, options)` | The CSV grid as `list[list[str]]`, header first. |
| `citation_entries(table)` | The sources rows (`C1`, `C2`, …) behind both formats. |

`ExportOptions`: `include_citations` (default true), `include_metadata` (paper/source/pages/
status columns, default true), `bom` (CSV only, default true), `filename_stem`.
Errors are `EmptyTableError` (nothing to write) and `TableTooLargeError` (>100k rows or >512
columns), both subclasses of `ExportError` and both mapped to HTTP 422.

### HTTP API

`POST /api/export/xlsx` and `POST /api/export/csv`, both authenticated, both taking
`{"table": ExtractionTable, "options": ExportOptions}` and returning the file as an
attachment. The name is sent twice — an ASCII `filename` and a percent-encoded
`filename*` (RFC 6266) — because HTTP headers are latin-1 on the wire.

## Workbook layout

**Sheet 1 `Review table`** — one row per paper, one column per extracted field, preceded by
`Paper | Source | Pages | Row status`. Header is frozen, filled and auto-filtered; the
`Source` cell is a real hyperlink. Each **cited** value is an internal hyperlink into its
`Sources` row, with the quote as the hover tooltip. Each **unverified** value (the model
produced it but its quote could not be found in the PDF) is rendered in amber italics and
suffixed `(unverified)`.

**Sheet 2 `Sources`** — one row per cited cell:

```
Ref | Paper | Column | Value | Page | Match | Quote | Block | Position (x0, top, x1, bottom) | Source
C1  | …     | sample size | 73 patients | 1 | exact | "73 patients were randomized" | p1-b4 | 58.1, 300.4, 296.1, 312.2 | https://…
```

### Why a sources sheet rather than per-cell comments

Comments were the other option in the ticket. The sheet wins on every axis that matters here:

- **Comments are lossy.** Google Sheets imports xlsx comments as notes and drops the
  threading; LibreOffice renders them but re-exports them differently; CSV cannot carry them
  at all, so the two formats would diverge in what they preserve.
- **Comments are not data.** A sources sheet can be sorted, filtered and pivoted — "show me
  every fuzzy-matched value", "which paper did all these numbers come from" — and a reviewer
  can paste it into an appendix. A comment can only be hovered, one cell at a time.
- **Quotes are long.** Comment boxes are fixed-size popups; a 300-character quote plus page
  and coordinates is unreadable in one.
- **The link is the good part of comments.** Internal hyperlinks plus tooltips give the
  hover affordance anyway, so nothing is lost.

The cost is that deleting a data row does not delete its sources rows — the file is a
snapshot for review, not a live document, so that is acceptable.

## CSV layout

Same leading columns, then for each field a value column and a `<label> — source` column
holding `p3 · "the supporting quote" · fuzzy match`. `include_citations=False` drops the
source columns for a plain paste-able grid.

- Encoded UTF-8 **with BOM** by default: without it Excel on Windows decodes the file as the
  local codepage and mangles every non-ASCII character (µ, ±, ₅₀, CJK). Set `bom=False` for
  pipelines that would rather not see it.
- `\r\n` terminators and minimal quoting, per RFC 4180.

## Safety and encoding

- **Formula injection.** A value like `=HYPERLINK("http://evil")` is executed on open by
  Excel, Sheets and LibreOffice, and every value here is untrusted text lifted out of a
  third-party PDF. CSV cells beginning with `= + - @ TAB CR` are prefixed with `'`; xlsx
  cells are instead written with an explicitly pinned string type, which blocks the same
  attack **without** altering the text.
- **Illegal characters.** `\x00-\x08`, `\x0b`, `\x0c`, `\x0e-\x1f` make Excel refuse to open
  a workbook, so they are stripped. Tabs and newlines are kept.
- **Length.** Values longer than Excel's 32,767-character cell limit are truncated with an
  ellipsis; quotes on the sources sheet are capped at 1,000 characters.

## Limits

500 rows × 2 cited columns renders in well under a second and is covered by a test. The
workbook is built in memory (openpyxl's normal, not write-only, mode) — fine to a few
thousand papers; past that, `MAX_ROWS` rejects rather than exhausting memory, and the writer
would need converting to `write_only` streaming.
