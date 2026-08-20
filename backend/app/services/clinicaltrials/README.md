# ClinicalTrials.gov service

Filtered, paginated search over the [ClinicalTrials.gov v2 API](https://clinicaltrials.gov/data-api/api),
normalized into `TrialRecord` and projected into the shared `SourceRecord` review row used by the
PubMed and PubChem services.

The API is unauthenticated — no key or env var is required to run it.

## Public interface

```python
from app.services.clinicaltrials import (
    ClinicalTrialsService, TrialSearch, TrialPhase, TrialStatus,
)

service = ClinicalTrialsService.from_settings()
page = await service.search(
    TrialSearch(
        sponsor="Merck",
        condition="melanoma",
        intervention="pembrolizumab",
        phases=[TrialPhase.PHASE3],
        statuses=[TrialStatus.RECRUITING, TrialStatus.COMPLETED],
    ),
    page_size=25,
)
await service.aclose()
```

### `ClinicalTrialsService`

| Member | Description |
| --- | --- |
| `from_settings(settings=None)` | Build a service from app settings (base URL, timeout, rate limit). |
| `search(search, *, page_size=25, page_token=None) -> TrialPage` | One page of matching trials. |
| `iter_pages(search, *, page_size=25, max_pages=10) -> AsyncIterator[TrialPage]` | Walk pages until the cursor runs out. |
| `aclose()` | Close the underlying HTTP client. |

### `TrialSearch`

Every field is optional but at least one is required; supplied filters are AND-ed.

| Field | Maps to | Notes |
| --- | --- | --- |
| `sponsor` | `query.spons` | Lead sponsor or collaborator, phrase search. |
| `condition` | `query.cond` | Disease or condition. |
| `intervention` | `query.intr` | Drug or other intervention. |
| `term` | `query.term` | Free text across the whole study record. |
| `phases` | `filter.advanced=AREA[Phase]…` | `TrialPhase` values, OR-ed within the facet. |
| `statuses` | `filter.overallStatus` | `TrialStatus` values, OR-ed within the facet. |

Phase has no dedicated filter parameter in v2, so it is expressed as an Essie advanced-filter
expression; multiple phases become `AREA[Phase](PHASE2 OR PHASE3)`.

### `TrialRecord`

`nct_id`, `title`, `official_title`, `status`, `phases`, `study_type`, `sponsor`, `collaborators`,
`conditions`, `interventions` (name + type), `enrollment`, `enrollment_type`, `start_date`,
`primary_completion_date`, `completion_date`, `url`.

Dates are the API's own strings and vary in precision (`2024`, `2024-03`, `2024-03-15`). Status and
phase values from a future API revision degrade to `None`/omitted rather than raising.
`phase_label` renders `["PHASE1","PHASE2"]` as `Phase 1/2`; `to_source_record()` produces the shared
review row.

### `TrialPage`

`trials`, `total_count`, `total_count_known`, `page_size`, `next_page_token`, `has_more`. v2
paginates with an opaque cursor rather than offsets: pass `next_page_token` back into `search()` for
the following page. The API only returns `totalCount` on the first page of a walk, so later pages
fall back to the number of trials on that page and set `total_count_known` false — check it before
reporting a total, or a search matching 143,516 studies is reported as having matched 50.

## Errors

| Exception | Raised when |
| --- | --- |
| `InvalidQueryError` | No filters, an out-of-range `page_size`, or a filter expression the API rejects (HTTP 400). |
| `ClinicalTrialsRequestError` | Non-400 error status, or the API is unreachable after retries. Carries `status_code`. |
| `ClinicalTrialsResponseError` | The body was not a JSON object containing a `studies` list. |

429/5xx and transport failures are retried with exponential backoff; requests are rate limited
(default 5/s) as a politeness measure.

## HTTP route

`GET /api/clinicaltrials/search` (authenticated) exposes the same filters:
`sponsor`, `condition`, `intervention`, `term`, repeatable `phase` and `status`, `page_size`
(1–100), `page_token`. It returns a `TrialPage`; invalid filters are 422 and upstream failures 502.

## Tests

`tests/clinicaltrials/` runs entirely against recorded fixtures in `tests/fixtures/clinicaltrials/`
— no live network calls in CI.
