# PubChem service

Resolves a chemical identifier — SMILES, IUPAC name, or common synonym — to PubChem compounds
via [PUG-REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest), and normalizes the result into
the record shape the review tables consume.

No API key is required. PubChem allows **5 requests/second per IP**, which the client enforces.

## Public interface

### `PubChemService`

```python
from app.services.pubchem import IdentifierKind, PubChemService

service = PubChemService.from_settings()
try:
    result = await service.lookup("aspirin")            # name or synonym
    result = await service.lookup("CC(=O)Oc1ccccc1C(=O)O")  # SMILES
    result = await service.lookup("2244", kind=IdentifierKind.CID)
    records = await service.records_for_cids([2244, 5793])
finally:
    await service.aclose()
```

`lookup(identifier, *, kind=None, limit=None) -> CompoundLookup`

- `kind` forces an interpretation (`smiles` / `name` / `cid`). Left unset, the identifier is
  sniffed and, if the first endpoint draws a blank, the other one is tried — a name that looks
  like a structure costs one extra request rather than a miss.
- `limit` caps how many candidates are hydrated (default `pubchem_max_candidates`, hard cap 25).

Name resolution is two-stage: PubChem's exact name index first, then its looser `name_type=word`
search. The widened search is the usual source of ambiguity, and it is recorded in `warnings`.

### `CompoundLookup`

| Field | Meaning |
| --- | --- |
| `query`, `resolved_as` | The trimmed identifier and how it was ultimately interpreted |
| `ambiguous` | `True` when the identifier matched more than one compound |
| `total_matches` | Matches PubChem reported, which may exceed `len(candidates)` |
| `match` | The top-ranked compound, for callers that just want one |
| `candidates` | Every hydrated compound in rank order (`rank`, `quality`, `score`) |
| `warnings` | Human-readable notes: widened search, truncated candidate list |

Ambiguity is never an error. Candidates are ranked `EXACT` (the compound's own title or IUPAC
name *is* the query) > `SYNONYM` (a registered synonym is the query) > `WORD` (word-search hit),
with PubChem's own ordering as the tie-breaker.

### `CompoundRecord`

`cid`, `title`, `iupac_name`, `molecular_formula`, `molecular_weight`, `canonical_smiles`,
`isomeric_smiles`, `xlogp`, `synonyms`, `pubchem_url`.

`to_source_record()` projects it into `app.services.records.SourceRecord`, the provider-agnostic
review-table row that `pubmed.Article` also produces, so literature and chemistry rows mix in one
table with their provenance intact.

### `PugRestClient`

The transport layer, useful directly for endpoints the service does not wrap:
`cids_for_name`, `cids_for_smiles`, `properties`, `synonyms`. It rate-limits, retries 429/5xx and
transport failures with exponential backoff, and sends identifiers as **form bodies** rather than
path segments — names and SMILES routinely contain `/`, `#` and `+`, which PUG-REST would
otherwise read as its own path syntax.

PubChem renamed two properties in 2025 (`SMILES` was `IsomericSMILES`, `ConnectivitySMILES` was
`CanonicalSMILES`); both spellings are parsed.

### Errors

| Exception | Raised when |
| --- | --- |
| `InvalidIdentifierError` | Empty, over-long, or not parseable as the forced `kind` |
| `CompoundNotFoundError` | No interpretation of the identifier matched anything |
| `PubChemRequestError` | PUG-REST error status, or unreachable after all retries (`status_code`, `code`) |
| `PubChemResponseError` | Response body was not the JSON shape PUG-REST documents |

## HTTP API

```
GET /api/pubchem/compound?q=<identifier>&kind=<smiles|name|cid>&limit=<1-25>
```

Requires a bearer token. Returns `CompoundLookup`; `422` invalid identifier, `404` no match,
`502` PubChem unavailable or unparseable.

## Configuration

| Setting | Default |
| --- | --- |
| `PUBCHEM_BASE_URL` | `https://pubchem.ncbi.nlm.nih.gov/rest/pug` |
| `PUBCHEM_TIMEOUT_SECONDS` | `20` |
| `PUBCHEM_RATE_LIMIT` | `5` requests/second |
| `PUBCHEM_MAX_CANDIDATES` | `10` |

## Tests

`backend/tests/pubchem/` runs entirely against recorded PUG-REST payloads in
`backend/tests/fixtures/pubchem/` through an injected `httpx` transport — CI never touches the
live API. To refresh a fixture, capture the real response and overwrite the file; the transport
asserts on request bodies, so a shape change surfaces as a failing test rather than a silent drift.
