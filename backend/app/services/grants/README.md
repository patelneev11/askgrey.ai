# Grants service

Tracks open SBIR/STTR and other federal funding opportunities across two providers and ranks
them against a company's research focus.

| Provider | Endpoint | Auth |
| --- | --- | --- |
| grants.gov | `POST https://api.grants.gov/v1/api/search2`, `POST .../fetchOpportunity` | none — public, no registration |
| SBIR.gov | `GET https://api.www.sbir.gov/public/api/solicitations` | none — public, no registration |

Neither provider requires an API key, an application, or an approval process. SBIR.gov is
nevertheless fronted by a WAF that answers some hosting ranges (including this project's CI
runners) with `403 Forbidden`; that is surfaced per source rather than failing the search, so a
blocked deployment still gets grants.gov results. See "SBIR.gov reachability" below.

## Public interface

```python
from app.services.grants import GrantSearch, GrantSource, GrantProgram, GrantsService

service = GrantsService.from_settings()
page = await service.search(
    GrantSearch(
        keyword="organoid",              # topic keyword, free text
        agency="NIH",                    # name, alias or literal provider code
        program=GrantProgram.SBIR,       # SBIR / STTR set-aside, applied locally
        open_only=True,                  # exclude closed and expired opportunities
        closing_after=date(2026, 9, 1),  # deadline window, applied locally
        closing_before=date(2027, 1, 1),
        sources=[GrantSource.GRANTS_GOV, GrantSource.SBIR],
    ),
    page=0,
    page_size=25,
)

matches = await service.match(
    "We develop mRNA cancer immunotherapies screened in patient-derived organoids",
    GrantSearch(keyword="cancer immunotherapy", agency="NIH"),
    limit=10,
    candidate_pool=40,
)
await service.aclose()
```

`GrantsService.from_settings()` wires both clients and picks the ranker: Claude when
`ANTHROPIC_API_KEY` is set, the deterministic lexical ranker otherwise.

### HTTP API

- `GET /api/grants/search` — query params `keyword`, `agency`, `program`, `open_only`,
  `closing_after`, `closing_before`, repeatable `source`, `page`, `page_size`. Returns a
  `GrantPage`.
- `POST /api/grants/match` — body carries `focus` plus the same filters, `limit` and
  `candidate_pool`. Returns a `MatchResult`.

Both require a bearer token. An unusable filter set is `422`; a provider outage is *not* an
error — it is reported in `sources[]` and the page is served from whatever answered.

## Normalized schema

`GrantOpportunity` is the shared shape both providers project into:

| Field | grants.gov | SBIR.gov |
| --- | --- | --- |
| `title` | `oppHits[].title` | `solicitation_title` |
| `agency` / `agency_code` | `agency` / `agencyCode` | `agency` |
| `branch` | — | `branch` |
| `number` | `number` | `solicitation_number` |
| `program` | inferred from the title ("Parent SBIR", "SBIR/STTR") | `program` |
| `status` | `oppStatus` | `current_status` |
| `posted_date` | `openDate` / synopsis `postingDate` | `open_date` or `release_date` |
| `close_date` | `closeDate` / synopsis `responseDate` | earliest of `close_date` and `application_due_date[]` |
| `funding_ceiling` / `funding_floor` | synopsis `awardCeiling` / `awardFloor` | not published |
| `topic_description` | synopsis `synopsisDesc` | topics and subtopics, concatenated |
| `topics` | — | topic and subtopic titles |
| `url` | `grants.gov/search-results-detail/{id}` | `solicitation_agency_url` |

`to_source_record()` projects an opportunity into the `SourceRecord` row shared with the
literature, chemistry and trials services, so grants can appear in the same review table.

## Behaviour worth knowing

**Enrichment.** `search2` returns no synopsis text and no award figures, so the matcher would
have nothing but a title to read. The service therefore issues one `fetchOpportunity` call per
hit (bounded by `grants_enrich_limit`, concurrency 5); a detail call that fails leaves that row
summary-only instead of failing the page.

**Agency vocabulary.** `agencies.py` maps a human name to each provider's own code —
`NIH → HHS-NIH11` on grants.gov, `Department of Defense → DOD` on grants.gov but `DOW` on
SBIR.gov. Two consequences:

- BARDA has no code of its own; it posts under its parent office ASPR, so a BARDA filter
  returns ASPR opportunities generally.
- SBIR.gov filters by department only. A sub-agency filter such as NIH is reported as an
  unsupported filter for that source rather than silently searching all of HHS.

An unrecognized value is passed through as a literal provider code, so a new agency code works
without a code change.

**Local filters.** Neither provider filters on set-aside program or a deadline window, so those
run locally after fetching; `total_count` is the providers' own hit count and is therefore an
upper bound measured *before* those filters.

**Pagination.** `page` is an offset into each provider independently — a page holds up to
`page_size` results *per source*, not `page_size` in total. SBIR.gov publishes no hit count, so
its `total_count` only reflects what has been paged through so far.

## Matching

`match()` gathers a candidate pool with the given filters and ranks it. The filters decide what
is eligible; the ranker only decides the order.

- **Claude** (`ClaudeMatchRanker`) sees the focus plus the whole numbered candidate list in one
  request, so it ranks comparatively rather than scoring in isolation, and returns
  `{index, score, rationale}` objects. Rankings with an out-of-range index or a non-numeric
  score are discarded rather than trusted.
- **Lexical** (`LexicalMatchRanker`) is the deterministic fallback used when no key is
  configured and in every test. It scores the IDF-weighted share of the focus vocabulary a
  candidate covers, weighting title hits above body hits.
- `FallbackMatchRanker` combines them: any `MatchingError` from Claude falls through to lexical,
  and `MatchResult.matcher` records which one produced the ranking.

Scores are normalized to `0-1`. Lexical scores are term overlap, not semantic fit — treat a
`matcher == "lexical"` result as a keyword ranking.

## SBIR.gov reachability

The SBIR.gov client is implemented against the documented public response shape and tested with
a fixture recorded from that documentation, because every live request from this project's
build environment returns a CloudFront `403 Forbidden` (`x-amzn-errortype: ForbiddenException`)
regardless of headers — an egress/WAF block, not an auth requirement. From an unblocked network
the client should work unmodified; until it is exercised there, treat the SBIR half of a search
as unverified against live data. grants.gov is verified live.

## Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `grants_gov_base_url` | `https://api.grants.gov/v1/api` | |
| `grants_gov_timeout_seconds` | `20` | |
| `grants_gov_rate_limit` | `5/s` | |
| `grants_enrich_limit` | `25` | max `fetchOpportunity` calls per page |
| `sbir_base_url` | `https://api.www.sbir.gov/public/api` | |
| `sbir_timeout_seconds` | `20` | |
| `sbir_rate_limit` | `2/s` | |
| `grants_match_max_tokens` | `2048` | Claude ranking budget |
| `grants_match_timeout_seconds` | `45` | |
| `ANTHROPIC_API_KEY` | unset | enables semantic matching |

Retryable failures (`429`, `5xx`, transport errors) back off exponentially; `4xx` other than
`429` fails immediately. grants.gov reports application-level failures with HTTP 200 and a
non-zero `errorcode`, which the client treats as a request error.
