# PubMed service (`app.services.pubmed`)

Natural-language question in, normalized PubMed records out. Wraps the NCBI Entrez
E-utilities (`esearch`, `efetch`, `esummary`) with rate limiting, retry/backoff, and a
Claude-backed natural-language → Entrez query translator.

Nothing in this module touches the network at import time, and the whole test suite runs
against recorded fixtures — CI never calls NCBI.

## Quick start

```python
from app.services.pubmed import PubMedService

service = PubMedService.from_settings()
try:
    result = await service.search(
        "randomized controlled trials of semaglutide for obesity since 2021", limit=20
    )
finally:
    await service.aclose()

result.query.term          # '("Semaglutide"[MeSH Terms] OR "semaglutide"[tiab]) AND ...'
result.total_results       # 412 — total PubMed hits, not the page size
result.articles[0].full_text_url  # PMC link when the record has a PMCID, else None
```

HTTP surface: `GET /api/pubmed/search?q=<natural language>&limit=20&offset=0&sort=relevance`
(bearer token required). `sort` is one of `relevance`, `pub_date`, `author`, `journal`.

## Public interface

### `PubMedService`

| Member | Description |
| --- | --- |
| `PubMedService(client, translator)` | Explicit construction; used by tests to inject a mock transport. |
| `PubMedService.from_settings(settings=None)` | Builds the client, rate limiter, and translator from app settings. |
| `await search(query, *, limit=20, offset=0, sort="relevance") -> SearchResult` | Translate → `esearch` → `efetch` → normalize. `limit` is clamped to 1–100. |
| `await summaries(pmids) -> dict` | Raw `esummary` payload for known PMIDs, keyed by PMID. |
| `await aclose()` | Closes the underlying HTTP client. |

`search` skips `efetch` entirely when `esearch` returns no IDs, and re-orders fetched
records to match ESearch's relevance ranking.

### `EntrezClient`

`EntrezClient(*, api_key="", tool="askgrey", email="", timeout=20.0, rate_limiter=None,
transport=None, base_url=..., max_attempts=4, base_delay=0.5)`

- `await esearch(term, *, retmax=20, retstart=0, sort="relevance") -> dict` — raw `esearchresult`.
- `await efetch(pmids) -> str` — `PubmedArticleSet` XML (`""` for an empty list).
- `await esummary(pmids) -> dict` — raw `result` payload (`{}` for an empty list).

Every request carries `db=pubmed`, `tool`, and — when configured — `email` and `api_key`.
Supports `async with`.

### Translators

All implement `QueryTranslator`: `await translate(query) -> TranslatedQuery`.

- `RuleBasedQueryTranslator` — deterministic fallback. Recognizes publication types
  (review, systematic review, meta-analysis, RCT, clinical trial, case reports) and date
  phrasing (`last 5 years`, `since 2021`, `between 2018 and 2020`, `before 2015`), keeps
  quoted phrases intact, drops stopwords, and emits `[tiab]` clauses. It cannot infer MeSH
  descriptors.
- `ClaudeQueryTranslator` — Anthropic Messages API. The system prompt requires a JSON object
  (`term`, `mesh_terms`, `keywords`, `publication_types`, `date_start`, `date_end`,
  `rationale`) so the structured filters stay inspectable and a missing `term` can be
  rebuilt locally. The Messages API has no JSON response mode, so the assistant turn is
  prefilled with `{` to suppress any prose preamble; the brace is re-attached before parsing.
- `FallbackQueryTranslator(primary, fallback)` — what `from_settings` wires up when
  `ANTHROPIC_API_KEY` is present: any `TranslationError` retranslates through the rule-based
  path, so a provider outage degrades instead of failing.

`normalize_query(query)` validates raw input up front and raises `InvalidQueryError` for
empty, whitespace-only, punctuation-only, non-string, or >1000-character queries.

### Models (`models.py`, all Pydantic)

- `Article` — `pmid`, `title`, `abstract`, `authors`, `journal`, `journal_abbreviation`,
  `publication_date`, `publication_types`, `doi`, `pmcid`, `pubmed_url`, `doi_url`,
  `full_text_url`.
- `Author` — `last_name`, `fore_name`, `initials`, `collective_name`, `display_name`.
- `TranslatedQuery` — `original`, `term`, `mesh_terms`, `keywords`, `publication_types`,
  `date_range`, `translator`, `rationale`.
- `SearchResult` — `query`, `total_results`, `returned`, `retstart`, `articles`, `warnings`.
- `PublicationTypeFilter` / `DateRangeFilter` — both expose `to_entrez()`.

`publication_date` preserves the precision PubMed provided: `YYYY-MM-DD`, `YYYY-MM`, or
`YYYY` (including the `MedlineDate` fallback for ranges like `2021 Mar-Apr`).

### Errors (`errors.py`)

`PubMedError` is the base. `InvalidQueryError` (bad user input, surfaced as HTTP 422),
`TranslationError` (translator failed), `EntrezRequestError` (HTTP/transport failure,
carries `status_code`), `EntrezResponseError` (unparseable payload).

## Rate limiting and retries

`RateLimiter` serializes requests to at most `rate` per second — **3/s without an API key,
10/s with one**, chosen by `Settings.entrez_rate_limit`. NCBI enforces the limit per key,
so spacing is applied globally rather than per connection.

`retry_with_backoff` retries transport failures and HTTP 429/500/502/503/504 up to
`max_attempts` (default 4) with exponential delays of 0.5s, 1s, 2s… capped at 8s. 4xx
responses other than 429 fail immediately.

## Configuration

| Env var | Default | Purpose |
| --- | --- | --- |
| `NCBI_API_KEY` | *(empty)* | Raises the Entrez limit from 3/s to 10/s. |
| `NCBI_TOOL_NAME` | `askgrey` | `tool` parameter NCBI requires for identification. |
| `NCBI_CONTACT_EMAIL` | *(empty)* | `email` parameter NCBI uses to contact heavy users. |
| `NCBI_TIMEOUT_SECONDS` | `20` | Per-request HTTP timeout. |
| `ANTHROPIC_API_KEY` | *(empty)* | When empty, translation is rule-based only. |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com/v1` | Messages API base URL. |
| `ANTHROPIC_VERSION` | `2023-06-01` | `anthropic-version` header. |
| `LLM_MODEL` | `claude-sonnet-4-5` | Translation model. |
| `LLM_MAX_TOKENS` | `1024` | `max_tokens` for the translation response. |
| `LLM_TIMEOUT_SECONDS` | `30` | Per-request timeout for translation. |

## Testing

`tests/pubmed/` covers translation, malformed input, rate-limit backoff, empty results,
XML normalization, and the HTTP route. Integration tests replay the fixtures in
`tests/fixtures/pubmed/` through an `httpx` transport that also records outgoing requests,
so tests assert on the exact parameters sent to NCBI.

```bash
cd backend && .venv/bin/pytest tests/pubmed -q
```
