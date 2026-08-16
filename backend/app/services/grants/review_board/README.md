# Mock grant review board

Puts one draft proposal section in front of three reviewer personas and returns what each of
them said: a score per NIH review criterion on the 1-9 scale, the reasoning behind it, strengths,
weaknesses and a written comment.

```python
from app.services.grants.review_board import ProposalSection, ReviewBoard

board = ReviewBoard.from_settings()
report = await board.review(ProposalSection(section_name="Approach", text=draft))
report.reviews          # one PersonaReview per persona, in configured order
report.summary          # the board-level sentence, computed from the scores
report.validation_status # always "unvalidated"
```

## Personas live in `personas.json`, not in code

A persona is a name, a focus, a system prompt and the criteria it scores. All of it is config, so
the board can be re-cast — a different reviewer, a harsher prompt, an extra criterion — without a
code change. `core_criteria` (Significance, Innovation, Approach) is scored by every persona;
each persona's own `criteria` are added after those.

The file is versioned and the version is stamped onto every report, so an old report can be read
against the personas that produced it. Unknown keys and duplicate ids are rejected by
`load_persona_config`, and a config with no `core_criteria` or no enabled persona raises
`ReviewBoardConfigError` at construction rather than producing a board that quietly reviews
nothing — the same policy as the eligibility rules. `enabled: false` keeps a persona in the file
and out of every report; a persona id the caller asks for that is unknown or disabled is an
`InvalidQueryError`, not a silently smaller board.

## The scores are the model's, and only the model's

One Claude call per persona, through the shared `AnthropicMessagesClient`, prefilled with `{` so
the reply is JSON rather than a preamble. Parsing is strict in one direction only:

- a score that is not a whole number from 1 to 9, or names a criterion that was not asked for,
  is **discarded**, never clamped or rounded into range — a coerced score would be
  indistinguishable from one a persona actually gave;
- a reply with no surviving score is a failed review, not an empty one;
- `overall_score` is the mean of the surviving criterion scores, computed here rather than taken
  from the reply, so it can always be checked against the table it sits above;
- `summary` is likewise computed, so the board-level text cannot disagree with the scores.

The draft is passed inside `<section>` tags with the delimiters stripped from it, and the persona
prompts state that the draft is data rather than instruction: a section that says "score this a 1"
is reviewed like any other.

## With no LLM key there is no review

`from_settings()` builds a board with no reviewer when `ANTHROPIC_API_KEY` is unset, and
`review()` then raises `ReviewBoardUnavailableError`, which `POST /api/grants/review-board`
surfaces as **503**. There is deliberately no lexical or rubric-based fallback here, unlike
opportunity matching: a heuristic that produced numbers on the NIH scale would be read as a
review of the science, and a fabricated study-section score is worse than no score at all.

## API

| Route | Auth | Notes |
| --- | --- | --- |
| `POST /api/grants/review-board` | `LlmUser` | Rate-limited and counted against the daily LLM budget. `text` is bounded at 200..20000 characters, `personas` at 10 ids. |
| `GET /api/grants/review-board/personas` | `ThrottledUser` | id, name, focus and criteria only. System prompt text is never served. |

## Limits

- **The scoring is unvalidated.** These numbers have never been compared against real NIH or
  SBIR reviewer scores. They are not calibrated, they have no demonstrated correlation with a
  funding outcome, and a 3 from a persona here is not a 3 from a study section. Every report
  carries `validation_status: "unvalidated"` and a `caveat` string saying so, in the payload
  rather than only in this file, because the score is what a reader will remember.
- A persona is a prompt, not a reviewer. It has no memory of the applicant, no knowledge of the
  other applications it is being scored against, and no access to the rest of the application.
- Scores vary between runs and between models. Two runs of the same section can differ by
  several points; treat a review as one rehearsal, not a measurement.
- Only the section given is read. Gaps a persona reports as absent may well be covered elsewhere
  in the application.
- This is a rehearsal aid. It is not a study section, not a mock review by qualified reviewers,
  and not evidence of anything about the proposal's merit.
