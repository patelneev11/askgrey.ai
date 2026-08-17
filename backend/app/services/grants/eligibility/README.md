# SBIR/STTR eligibility checker

Rules-based, deterministic. A `CompanyProfile` in, an `EligibilityReport` out: one
pass / fail / needs-review verdict per rule with a plain-language explanation and the
authority it comes from.

```python
from app.services.grants.eligibility import CompanyProfile, EligibilityChecker
from app.services.grants.models import GrantProgram

report = EligibilityChecker.from_config_file().check(profile, GrantProgram.SBIR)
report.verdict          # worst outcome across the rules
report.summary          # one sentence for a human
report.outcomes         # per-rule detail
```

## Why the thresholds live in `rules.json`

Size standards, ownership percentages and work-split minimums are legal thresholds. They are
either met or not, so nothing here consults a model: the same profile always produces the same
report. Editing a threshold means editing `rules.json`; the file is versioned and the version is
stamped onto every report, so a verdict can be traced to the numbers that produced it.

Each entry is `{id, title, citation, applies_to, enabled, parameters}`. `parameters` holds
numeric thresholds only — anything that cannot be written as a number is a judgement call and
belongs in `needs_review`. Setting `enabled: false` keeps a rule visible in review while taking
it out of reports; an `id` with no evaluator behind it raises `EligibilityConfigError` at
construction rather than being skipped silently.

## What `needs_review` means

Not a soft fail. It means the rule cannot be decided from the profile — either a fact is missing
(the outcome names it in `missing_fields`) or the threshold is agency-specific rather than
statutory: majority venture-capital ownership, Direct-to-Phase-II, SBA performance benchmarks,
and topic fit all land here by design.

## HTTP API

`POST /api/grants/eligibility` takes `{profile, program}` and returns the report, including the
derived `verdict` and `summary`. `GET /api/grants/eligibility/rules` returns the thresholds the
report was produced under. Both are authenticated and throttled; the profile is bounded
server-side (percentages 0-100, string lengths, non-negative counts) and a programme with no
rules behind it is a 422 rather than an empty pass.

## Limits

This is an aid to a human reviewer, not a legal determination, and it encodes the SBA baseline
rather than any one agency's solicitation. Affiliate headcount, ownership control (as opposed to
percentages) and the agency's own supplements still need a person.
