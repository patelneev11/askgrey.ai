# IND Module 3 / Module 4 drafting

Drafts CTD-shaped sections from data a sponsor submits, and says what the data does not cover.
It is a drafting aid for a regulatory affairs professional. It is not an autofill, it does not
decide what an IND must contain, and nothing it produces is submission-ready.

## Where the section tree comes from

`reference/ctd_structure.json` is a dated transcription of two documents, both read directly
(see `docs/regulatory-sources.md`):

| Covers | Document | Date |
| --- | --- | --- |
| Module 3 headings | ICH M4Q(R1), table of contents of Module 3 | 12 September 2002 |
| Module 4 headings | ICH M4S(R2), section 4.2 Study Reports | 20 December 2002 |
| What an IND must contain | 21 CFR 312.23 | as retrieved |

Two limits on how that tree may be read:

- M4S(R2) says of Module 4: "This guideline is not intended to indicate what studies are
  required. It merely indicates an appropriate format for the nonclinical data that have been
  acquired." So a section missing from a draft is never reported as a deficiency.
- M4Q/M4S describe the organisation of a marketing application. An IND is thinner, and FDA's
  content requirement is 21 CFR 312.23. This service organises text; it does not tell anyone
  which sections their IND needs.

The tree is data, not prompt text, so every draft states the `version` and `retrieved` date of
the transcription that produced it. Refreshing it against a newer ICH revision is a data change
plus a test update, and it needs a real owner: **there is no automated check that this file still
matches the current guidelines.**

## How a section gets drafted

```
IndDraftRequest (evidence records, section ids)
  -> evidence_for(section)        which submitted records this section may use
  -> gaps_for(section)            what is missing, computed from the request alone
  -> ClaudeIndDrafter             prose for sections that have data behind them
  -> IndSection[]                 status, gaps, evidence used, source reference
```

Two properties worth keeping:

- **Gaps are deterministic.** They come from comparing the submitted record kinds against the
  section's declared `requires`, before and independently of the model. A model asked what it
  was missing would answer from the text it just wrote.
- **A section with no data behind it is never sent to the model.** It returns
  `status: not_drafted` with an empty `text` and a `no_evidence_submitted` gap, so the caller
  sees a hole rather than plausible prose.

Facts no drafter can supply — who evaluated the nonclinical results and concluded it is
reasonably safe to begin, where the studies were run and where records are kept
(21 CFR 312.23(a)(8)), the names and addresses of manufacturing sites — are emitted as
`author_must_supply` gaps rather than written.

Every section carries `requires_expert_completion`, `requires_expert_review` and the review
notice in its own data, not only on the response envelope, because a section is what gets
copied out of the UI.
