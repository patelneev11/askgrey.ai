# Multi-jurisdictional guideline checker

Deterministic and offline. A CTD section id plus its draft text in, a
`GuidelineCheckReport` out: one `addressed` / `missing` / `indeterminate` finding per requirement,
each carrying the requirement's citation, the signal that matched, and where it matched.

```python
from app.services.regulatory.guidelines import GuidelineChecker, Jurisdiction

checker = GuidelineChecker.from_reference_files()
report = checker.check("3.2.S.4", draft_text, [Jurisdiction.FDA, Jurisdiction.EMA])
report.requires_expert_review        # always True
report.jurisdictions[0].version      # vintage of the data the findings came from
report.jurisdictions[0].findings     # per-requirement status, evidence, citation
checker.reference()                  # what is checked, with no draft involved
```

No model is consulted and nothing is fetched at runtime, so the same section text always produces
the same report. The reference data is shipped as `reference/<jurisdiction>.json`.

## What the datasets cover

| File | Jurisdiction | Transcribed from |
| --- | --- | --- |
| `reference/fda.json` | FDA (IND) | 21 CFR 312.23(a)(7)–(a)(8), plus the CTD section trees in ICH M4Q(R1) and M4S(R2) |
| `reference/ema.json` | EMA / EU CTR | Regulation (EU) No 536/2014 Annex I paragraphs 40–45, and EMA/CHMP/QWP/545525/2017 Rev. 2 |
| `reference/pmda.json` | PMDA | PMDA Center for Product Evaluation points to consider on nonclinical safety for an initial clinical trial notification |

Every document above is listed with its URL in `docs/regulatory-sources.md`, which is the only
place citations come from; each requirement's `citation` names the document, its date, and that
URL. Coverage is Module 3 (quality) and Module 4 / 2.6 (nonclinical) only, and within those it is
the subset each authority states in its own terms — it is not a transcription of the whole of any
document.

## How old the data is allowed to get

Every dataset's age is computed from its `retrieved` date on each request and travels with the
payload as `freshness` (per jurisdiction) and `snapshot` (the worst-aged one), so the UI can state
the vintage instead of implying the comparison is current:

| Age since `retrieved` | `status` | What it means |
| --- | --- | --- |
| under 90 days | `current` | A human read the sources within the review interval. Not a claim that the encoded set is complete or legally in force. |
| 90–179 days | `review_due` | The quarterly review is overdue; the sources have not been re-read. |
| 180 days or more | `stale` | Findings may reflect superseded guidance and must be checked requirement by requirement against the cited document. |

A `retrieved` date in the future is reported as `review_due` with an age of 0 rather than as fresh.
The thresholds live in `models.py` (`SNAPSHOT_REVIEW_INTERVAL_DAYS`, `SNAPSHOT_STALE_AFTER_DAYS`)
and are a maintenance policy of this repo, not anything an authority publishes.

`tests/test_regulatory_guidelines_freshness.py::test_shipped_snapshots_are_within_the_staleness_limit`
is the forcing function: it warns once a review is overdue and **fails** once any shipped dataset
passes 180 days. A red build there is not a broken test — it is the refresh below coming due.

## Refreshing the data

Nobody automates this, and nothing is fetched at runtime by design: the checker must stay
deterministic and offline, and pulling regulatory sites from a request path would add both an SSRF
surface and a silent dependency on someone else's uptime. The files are a snapshot read on the
`retrieved` date: the FDA and EMA texts change rarely, but PMDA's points-to-consider document is
revised roughly annually. Refreshing is a manual review against the source:

1. Open the document in `docs/regulatory-sources.md` for the jurisdiction you are refreshing and
   read it against the file's `requirements`.
2. Edit `reference/<jurisdiction>.json`: `title`, `ctd_sections`, `citation`
   (`document` / `document_date` / `url`), `expectation`, `signals`, `negative_signals`. Keep `id`
   stable when a requirement's substance is unchanged so past reports stay comparable; use a new
   `id` when it is a different requirement. Add the document to `docs/regulatory-sources.md` first
   if it is not already there.
3. Bump the dataset's `version` (`YYYY-MM-<jurisdiction>-<n>`) and set `retrieved` to the date you
   read the source. Both are stamped onto every report, so a finding can be traced to the vintage
   that produced it; a dataset with a stale `retrieved` date is worse than a missing one only in
   that it looks current.
4. Update `notes` if the scope of what is encoded changed, then run
   `.venv/bin/pytest tests/test_regulatory_guidelines_reference.py` — it validates every file,
   requires non-empty `version`/`retrieved` and a URL on every citation, and checks the URLs
   against `docs/regulatory-sources.md`.

## How matching works, and what that costs

A requirement is recognised by literal phrase matching over normalised text (case, whitespace,
hyphen and dash variants, quotes). `signals` is a list of alternative groups, each of which is a
set of phrases that must all be present; the first group that matches wins and is recorded with
each phrase's offset and surrounding text. `negative_signals` (e.g. "to be determined") force
`indeterminate` even when a group matched. A section under `MIN_WORDS_TO_JUDGE` (40 words) is
`indeterminate` for everything, because a heading or a placeholder sentence containing a signal
phrase would otherwise read as `addressed` — a false `addressed` is the dangerous direction here.
Requirements are only evaluated against a section whose id shares a dotted prefix with one of their
`ctd_sections`, in either direction; the rest are returned in `out_of_scope_requirement_ids`.

There is no semantic or fuzzy matching, so the failure modes are direct and in both directions:
content written in wording the dataset does not look for reads `missing`, and a section that names
a topic without substantiating it reads `addressed`. `addressed` therefore means "the phrases the
dataset looks for are present", never "the requirement is met", and `missing` is a prompt to
check. An IND is also a thinner submission than a marketing application — 21 CFR 312.23(a)(7)(i)
scales expected content with the phase of the investigation — so a `missing` finding on an early
phase draft is frequently correct as drafted.

## Limits

Neither complete nor authoritative. This is an unvalidated drafting aid whose output requires
review by qualified regulatory affairs personnel; every report says so in its own
`requires_expert_review`, `review_notice` and `limitations` fields rather than leaving it to the
UI. It is not a regulatory determination, does not judge the adequacy of any content, and the
requirement text is a transcription that can be wrong or out of date — the cited document, not
this dataset, is the authority.
