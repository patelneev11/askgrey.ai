# PDF extraction

Turns a research PDF into a review-table row whose every cell cites the exact span of the
source it came from.

```
PDF bytes ──▶ parse_pdf ──▶ ParsedDocument (blocks + geometry)
                              │
                              ├──▶ DataPointExtractor (Claude) ──▶ RawDataPoint {value, quote}
                              │
                              └──▶ grounding.cite(quote) ──▶ Citation ──▶ ExtractionCell
```

The LLM only ever proposes a value plus a verbatim quote. The quote is then matched back
against the parsed text by a deterministic string search, and only a quote that is actually
found produces a citation — a value the model could not quote is surfaced as `ungrounded`,
never as sourced.

## Why pdfplumber

pdfplumber (MIT) rather than PyMuPDF (AGPL — a closed product needs a commercial licence).
pdfplumber exposes per-word boxes, which is all the geometry a highlight needs. It is
roughly an order of magnitude slower; that is irrelevant for a per-paper background job.
Neither library does OCR, so scanned PDFs are unsupported in both cases.

## Public interface

```python
from app.services.pdf_extraction import PdfExtractionService

service = PdfExtractionService.from_settings()          # Claude extractor + HTTP fetcher
table = await service.extract_from_bytes(pdf_bytes, goal="sample size, dosing regimen")
table = await service.extract_from_url("https://pmc.ncbi.nlm.nih.gov/articles/PMC5334499/")
await service.aclose()
```

| Callable | Purpose |
| --- | --- |
| `parse_pdf(data, *, filename, source_url, max_pages)` | Bytes → `ParsedDocument`. Raises `UnsupportedPdfError` / `PdfParseError`. |
| `find_span(document, quote, *, block_id)` | Locate a quote; exact → normalized → fuzzy. |
| `cite(document, quote, *, block_id)` | `Citation` for a quote, or `None` if it is not in the document. |
| `PdfExtractionService.parse / fetch / resolve_fields` | The stages, individually, for callers that batch. |
| `PdfExtractionService.extract_row(document, fields)` | One paper → one `PaperRow`. |
| `PdfExtractionService.extract_table(documents, goal=…)` | Many papers → one `ExtractionTable`; a paper that fails still gets a row. |
| `PdfExtractionService.extract_from_bytes / extract_from_url` | Upload and full-text-link entry points. |

`DataPointExtractor` is a Protocol (`extract(document, fields) -> list[RawDataPoint]`), so the
model can be swapped or stubbed without touching parsing or grounding.

### HTTP API

| Route | Body |
| --- | --- |
| `POST /api/pdf-extraction/upload` | multipart: `file`, `goal` |
| `POST /api/pdf-extraction/url` | JSON: `{"url": …, "goal": …, "fields": [...]}`; a PMC article URL is rewritten to its `/pdf/` form |

Both require a bearer token and return an `ExtractionTable`. Errors: `415` scanned or
non-PDF, `400` corrupt PDF, `422` empty goal, `502` fetch or model failure, `503` no
`ANTHROPIC_API_KEY`.

## Citation object schema — stable contract

The frontend depends on this shape directly. **Fields are only ever added, never renamed or
removed.**

```jsonc
{
  "document_id": "35929b2d1a75ac1c",   // sha256 prefix of the file bytes
  "source_url": "https://…/paper.pdf", // empty for a direct upload
  "page_number": 1,                    // 1-based
  "page_width": 612.28,                // points, for scaling to the rendered page
  "page_height": 790.87,
  "block_id": "p1-b4",                 // stable within a document: p<page>-b<index>
  "text": "73 patients were randomized…",   // the exact source text, as parsed
  "start_char": 9,                     // offsets into the block's text
  "end_char": 82,
  "bbox":  {"x0": 58.1, "top": 300.4, "x1": 296.1, "bottom": 312.2},
  "rects": [{"x0": 58.1, "top": 300.4, "x1": 296.1, "bottom": 312.2}],
  "match": "exact"                     // exact | normalized | fuzzy
}
```

**Coordinates** are PDF points (1/72") with the origin at the **top-left** of the page and
`top` growing downwards — pdfplumber's convention, which matches CSS. To highlight:

```js
const scale = renderedWidth / citation.page_width;
rects.map(r => ({ left: r.x0 * scale, top: r.top * scale,
                  width: (r.x1 - r.x0) * scale, height: (r.bottom - r.top) * scale }))
```

`rects` is one rectangle per line the span crosses (that is what to paint); `bbox` is their
union (enough for a scroll-to). `match` tells you how the span was found: `exact` is a
character-for-character hit, `normalized` folded whitespace/ligatures/hyphenation, `fuzzy` is
an approximate hit and its rectangle should be treated as indicative — worth rendering
differently.

## Dynamic Column Generator shape

```jsonc
{
  "goal": "sample size, dosing regimen",
  "columns": [{"key": "sample_size", "label": "sample size", "description": ""}],
  "rows": [{
    "document_id": "35929b2d1a75ac1c",
    "title": "A 6 Week Randomized Double-Blind…",
    "source_url": "", "filename": "trial.pdf", "page_count": 3,
    "status": "extracted",                       // extracted | unsupported | failed
    "cells": {
      "sample_size": {
        "value": "73 patients",
        "citation": { /* as above */ },
        "status": "grounded",                    // grounded | ungrounded | not_found
        "note": ""
      }
    },
    "warnings": []
  }]
}
```

One row per paper, one column per requested field, one `{value, citation}` per cell. Columns
come from splitting the goal on commas/semicolons/newlines — deterministic, so re-running a
goal never shifts the column keys. Callers that want their own keys pass `fields` instead.
`PaperRow.to_source_record()` projects a row into the shared `SourceRecord` used by the
PubMed/PubChem/ClinicalTrials review tables.

## Unsupported input

A PDF averaging under 40 extractable characters per page is treated as scanned or
image-only: `UnsupportedPdfError` (HTTP 415), never a crash and never a silently empty row.
OCR is deliberately out of scope — adding it would change the citation contract, because OCR
boxes are recognition guesses rather than the document's own geometry.

## Accuracy limits

- **Reading order.** Blocks are grouped by column and vertical gap. Sidebars, floating
  metadata and figure captions can interleave with body text on a two-column page, so a
  block's text is not always contiguous prose. Citations still point at exactly the text
  they quote; it is the surrounding context that may read oddly.
- **Tables.** A table is flattened into rows of text without cell structure, so a value read
  out of a wide table can be cited to the right row but the wrong-looking span.
- **Superscripts and ligatures.** Reference markers land inline (`efficacy12`), and ligatures
  are folded only during matching, not in the stored text.
- **Fuzzy matches.** A `fuzzy` citation's boundaries are approximate by construction.
- **The model.** Values are as good as Claude's reading of the paper; grounding proves a
  quote exists, not that the quote supports the value.
