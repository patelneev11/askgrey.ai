# Patent / IP landscape (keyword prior-art search)

`POST /api/screening/patents/search` takes a SMILES string, a free-text scaffold description, or
both, and returns keyword prior-art hits from one USPTO dataset. It is a **text search**. It is
not a structural search, not a novelty assessment and not a freedom-to-operate analysis, and the
response says so in fields the UI must render rather than leaving it to a tooltip.

## Which API, and why

**USPTO Open Data Portal — Patent Search**, `GET https://api.uspto.gov/api/v1/patent/applications/search`.

It is the endpoint USPTO currently maintains for programmatic search of patent applications, it
returns structured bibliographic JSON (title, abstract, filing/publication/grant dates,
applicants, inventors, CPC symbols, status), and it is free.

The alternatives were rejected:

- **PatentsView legacy API** (`api.patentsview.org`) is discontinued; its replacement
  (`search.patentsview.org`) also requires a key.
- **Patent Public Search** (`ppubs.uspto.gov`) is a browser application. Its internal endpoints
  are session-bound and undocumented, so integrating them would mean depending on an interface
  USPTO does not publish and may change without notice.
- **Patent Examination Data System** (PEDS) is retired in favour of the Open Data Portal.

## The gap: an API key is required

The Open Data Portal endpoint requires a free `X-API-KEY`
(<https://developer.uspto.gov/> → Open Data Portal → request an API key). No key was available
when this module was written; an unauthenticated request answers `401`.

Rather than inventing a credential or pretending, the client is fully implemented and the service
degrades honestly. With `USPTO_ODP_API_KEY` unset:

- the client's `configured` is `False` and **no upstream request is attempted**;
- the response is `200` with `source_available: false` and a `source_status` explaining that a
  key is required, that no search ran, and that nothing in the payload is a search result;
- `hits` is `[]`, `total_found` is `null`, and `no_match_statement` stays **empty** — an empty hit
  list from an unsearched source must never read as "no prior art found".

Set `USPTO_ODP_API_KEY` (env var, see `app/core/config.py`) to enable the source. Nothing else
changes: the same code path then returns real hits.

The same degraded payload is returned when the upstream API is reachable but unusable — a
rejected key (`401`/`403`), throttling (`429`), a `5xx`, a timeout, or an unparseable body. The
one exception is `400`, which means the query expression itself was rejected: that is a bug in
query construction, so it surfaces as a `502` instead of being hidden.

## What it can do

- Free-text search over the fields ODP indexes for an application: title, abstract and
  bibliographic metadata.
- Terms AND-ed together (`C9H8O4 AND salicylate`), reported verbatim as `query.query_used`.
- Sort by relevance (upstream order), filing date asc/desc, or grant date desc.
- Offset pagination, bounded page size, and an optional filing-date range filter.
- Return only what upstream returned: a missing patent number, assignee or date stays empty.

## What it cannot do, and deliberately does not compute

`PatentLandscape.unavailable` carries one entry per refusal, in the shared
`UnavailableProperty` shape (`key`, `label`, `available: false`, `reason`, `requires`):

| key | why not |
| --- | --- |
| `structural_similarity_search` | The source is a keyword index over text. It cannot be queried by structure, so no similarity or substructure match happens. A real structure search needs a licensed chemistry-in-patents database (SciFinder, Reaxys, SureChEMBL). |
| `novelty_score` | Novelty is a legal determination made claim by claim over all prior art in any language. A number derived from keyword hit counts would measure query wording, not novelty. |
| `freedom_to_operate` | FTO depends on in-force claim scope, jurisdiction, assignments and licences, none of which a keyword search examines. |

Two further honesty rules are enforced in the payload rather than the docs:

- **A SMILES input is never searched as a structure.** It is parsed by RDKit and reduced to its
  molecular formula, which becomes a search term. `query.derived_from`,
  `query.derivation` and `query.structure.searched_by_structure: false` say exactly that. A patent
  claiming the compound under a Markush genus, a trade name or a different formula expression
  will not match.
- **An empty result set is a statement about the query, not about the art.** When a search does
  run and matches nothing, `no_match_statement` says so and says it is not evidence of novelty.
  Claim scope is also out of reach in a subtler way: ODP indexes the abstract, not the full claim
  text, so a patent whose claims cover the compound while its abstract uses other words is
  invisible here.

`caveat` is always present, on every response, including successful ones.

## Validation and bounds

Everything is checked before any external call is made:

- **SMILES**: `parse_structure` from `app/services/screening/smiles.py` — the shared gate (≤600
  characters, SMILES charset only, RDKit sanitization, ≤200 heavy atoms). Invalid → `422`.
- **Keywords**: 3–200 characters after whitespace collapsing, and a narrow charset (letters,
  digits, spaces, `- ' , . + /`). Newlines, quotes, colons, wildcards and brackets are rejected,
  so a pasted abstract or a query-DSL fragment cannot get through. Invalid → `422`.
- **Query construction is extraction, not escaping.** Terms are pulled out with a strict token
  pattern and re-joined, capped at 12 terms; nothing the caller typed is interpolated into the
  upstream query. That is why no user input can reach the upstream query language as syntax.
- **At least one searchable term** must survive, from the structure or the keywords, or the
  request is `422`.
- **Paging**: `page_size` 1–50 (default 25), `offset` 0–500. Bounded in the request model and
  re-checked in the service.
- **Sort** is an enum, mapped to an upstream sort expression here; the caller never supplies one.
- **Dates**: `filed_from`/`filed_to` become one `rangeFilters` expression. A one-sided range is
  widened with a bound no real filing date can fall outside. `filed_from > filed_to` → `422`.
- **No SSRF**: the base URL is a setting with a constant default and the path is fixed. User
  input only ever becomes a query *parameter* on that host.
- **Outbound politeness**: a shared `RateLimiter` (default 2 req/s), a request timeout, and
  exponential backoff on `429`/`5xx`/transport failures. The API key is sent as a header only —
  never logged, never echoed into an error message, never in a response body.
- **Logging** records route, outcome, status and counts. Query text and response bodies are not
  logged.

## Known gaps

- **A key is needed for the source to work at all** (see above).
- **One dataset, one office.** ODP's application search covers US applications published from
  ~2001 onward. Pre-2001 US patents, unpublished applications (including anything inside the
  18-month window), and every non-US office (EPO, WIPO, CNIPA, JPO) are outside it.
- **Abstract-level text only.** Claims and full description text are not searched.
- **Keyword recall is a synonym problem.** Chemistry is written many ways; a formula query misses
  Markush claims, salts, solvates, trade names and IUPAC-name-only text. A null result reflects
  the wording of `query_used` and nothing more.
- **No de-duplication across family members.** A patent and its continuations appear as separate
  hits, so hit counts are not a measure of how many distinct inventions were found — which is one
  more reason no score is derived from them.
- **`total_found` is upstream's number.** It is reported when present and `null` when absent; it
  is never inferred from the page.
- **The test fixtures are schema-accurate but hand-built**, because no key was available to
  record a live response — see `tests/fixtures/patents/SOURCES.md`.
