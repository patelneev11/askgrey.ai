# Patent search fixtures

Recorded from live calls to the USPTO Open Data Portal search API
(`https://api.uspto.gov/api/v1/patent/applications/search`) with a real `X-API-KEY`. The key is
never part of a response, so nothing here is secret.

| File | Request | Upstream response |
| --- | --- | --- |
| `search_page1.json` | `q=+salicylate +composition&limit=3&offset=0` | `200`, `count: 16` |
| `search_granted.json` | `q=+aspirin +crystalline&limit=2&offset=0` | `200`, `count: 7` |
| `search_no_match_404.json` | `q=+zzqxwvtherm +nonexistentterm&limit=3&offset=0` | `404`, verbatim body |

The two `200` payloads are real records with the keys the parser does not read removed
(prosecution `eventDataBag`, correspondence addresses, attorney and continuity records, and the
metadata fields no response field maps to). Every key and value that remains is verbatim, so the
parser is tested against real spellings: padded CPC symbols (`A61K  31/616`), applicants carried
as `applicantNameText`, inventors carried as first/last name parts, and pending applications with
no `patentNumber` or `grantDate` (`search_page1.json`) alongside granted ones
(`search_granted.json`).

Two things these recordings establish about the live API, both of which the module depends on:

- `count` is the size of the whole match set, not of the page: `search_granted.json` carries two
  records and `count: 7`. There is no `totalNumFound` field on this endpoint.
- A search that matches nothing answers **`404`** with the body in `search_no_match_404.json`,
  not an empty `200`. `search_no_match_404.json` is what lets the tests prove that case is
  reported as a zero-hit search rather than as a degraded source.

No record here carries abstract text, because the dataset does not have any — which is why
`PatentHit` has no abstract field.
