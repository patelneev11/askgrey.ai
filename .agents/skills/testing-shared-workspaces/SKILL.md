---
name: testing-shared-workspaces
description: How to end-to-end test askgrey.ai shared workspaces (invitations, seats, viewer/member/admin/owner roles, private-vs-shared scoping, removal/leave, non-member disclosure) with several accounts locally.
---

# Testing shared workspaces / seats / roles

Applies to the Workspace tab panel (`frontend/src/components/SharedWorkspaces.tsx`),
`backend/app/api/workspaces.py` and `backend/app/services/workspaces.py`.

## Bring-up

1. `cd backend && .venv/bin/alembic upgrade head` — the workspace tables live in `0007_workspaces`;
   without it every workspace call 500s.
2. `cd frontend && npm run build`, then start uvicorn detached with
   `setsid nohup … < /dev/null` and `FRONTEND_DIST_DIR=frontend/dist`, single origin
   `http://localhost:8000`. Confirm `/api/health`.
3. DB oracle: `backend/askgrey.db` through `backend/.venv/bin/python` + stdlib `sqlite3`
   (there is no `sqlite3` CLI). Useful tables: `workspaces`, `workspace_members`,
   `workspace_invites`, `saved_artifacts.workspace_id`, `saved_protocols.workspace_id`,
   `users.active_workspace_id`, `audit_events(event, outcome, kind, detail_json)`.

## Running two accounts at once

The access token is module memory but the refresh token is a shared HttpOnly cookie
(`askgrey_refresh`), so two tabs of one Chrome profile fight over it on reload. Put the second
account in an **Incognito window**; keep the first in the normal window. Always navigate with an
explicit `http://localhost:8000/...` — a bare host string can open an external anti-bot page.

## Invitation tokens

- The raw token is returned **once**, only in the `POST /api/workspaces/{id}/invites` response
  (`CreatedInvite.token`); the row stores only `token_hash`. Reloading the panel never shows it
  again, so **transcribing a token from a screenshot is unreliable** (l/1/I, O/0 confusions).
  Prefer issuing the invite over the API with the owner's bearer token, capture `token` from the
  JSON, then *paste/type it into the UI Join field* so the flow is still exercised in the browser.
- Read the API response with plain `urllib.request` and `resp.read()`; helper wrappers that
  truncate the body will break JSON parsing of the token.
- Only one pending invite per address: revoke the existing one first, or you get
  `that address already has an invitation waiting`.

## Levers with no UI

- **Expiry** (TTL 14 days) — age `workspace_invites.expires_at` in SQLite. Label as DB-forced.
- **Seat oversubscription** — an invitation reserves its own seat, so acceptance can never see an
  over-limit state through supported operations; lower `workspaces.seat_limit` in SQLite to reach
  the defensive branch (expect `409 that workspace has no seat free`). Restore the limit after.

## Judging role claims

`SavedLibrary` has **no role awareness**: Save/Delete buttons render for viewers and for
colleagues' rows. Never treat a hidden or shown button as enforcement — fire every owner/admin
route with that role's own bearer token as well:
`POST /invites`, `PATCH /{id}`, `POST /{id}/owner/{member}`, `DELETE /{id}`,
`PUT /{id}/members/{member}`, `DELETE /{id}/members/{member}`.
Insufficient role → **404** with role wording; stranger → **404** `no workspace with that id`
(compare byte-for-byte against a random UUID to prove non-disclosure), seat limit → **409**.

## Known UI traps

- **The panel does not refresh after several mutations** (Remove, Invite, role change): the server
  write succeeds and is audited, but the table only updates after F5. Verify in the DB before
  concluding a click "did nothing", and re-check after a reload.
- Refusals appear as page text via `run()`/`messageOf`, not as toasts — read the paragraph.
- `Leave` does refresh immediately; `Remove` does not (asymmetry worth re-checking each run).

## Scoping oracles

`Shared · saved <date>` in the saved list is the visible discriminator; `Saved <date>` = private.
Always re-fetch (tab change or F5) before asserting, and cross-check
`saved_artifacts.workspace_id`.

## Shared stored papers (migration `0008_shared_documents` and later)

Before `0008`, stored papers were always personal. From `0008` on, `literature_documents` has a
nullable `workspace_id`: a paper added while the account works in a workspace it can **write** to
(member/admin/owner) is stamped with that workspace and is readable by every member — viewers
included: a viewer may *read* shared papers, it just cannot contribute one. Private and viewer
uploads keep `workspace_id NULL` forever. Oracles and traps:

- The Literature tab is **per-account state** and (as of PR #93) ships **no UI** that hands a
  colleague a shared review table. To exercise a colleague's citation viewer against someone
  else's paper, seed the colleague's own saved state with the shared id using **their** token:
  `PUT /api/literature/workspace` with
  `sources:[{id,label,kind:"upload",document_id:<other account's id>}]`. The response's
  `stored_document_ids` is a fast server-side readability oracle. Everything after that is real
  UI: reload, Generate, click the cited cell. Label the seeding step in the report.
- A broken share is unmistakable: the pre-#93 path drops the chip with
  `<file> is no longer stored — upload the PDF again`, so it cannot look like a pass.
- Delete rules: only the uploader may delete. A member/admin who can see the paper gets **403**
  `only the account that added this paper can delete it` (audited `literature.document_deleted`
  with outcome `denied`); an outsider gets **404 `no such document`**, byte-identical to a
  never-stored id.
- Removal / leave / workspace deletion revoke access on the next request. Deletion sets
  `workspace_id` back to `NULL` and must **not** delete rows — count `literature_documents`
  before and after.
- Audit `literature.document_read` carries `added_by` + `workspace_id` and renders as "Opened a
  stored paper"; assert no filename and no `%PDF` anywhere in `audit_events.detail_json`.
- Document ids are **content-addressed**, so two accounts uploading identical bytes share an id
  and cross-account 404 checks get confounded by the caller's own row. Append a trailing comment
  to a PDF copy when you need a genuinely distinct id per account.
- Removing a source is optimistic: `removeSource()` in `frontend/src/lib/workspace.tsx` snapshots
  `sources` + `table` and, **only on a 403**, restores both and shows
  `<label> was added by someone else in this workspace, so only they can remove it.` (rendered as
  `<p role="alert">` in `pages/LiteraturePage.tsx`). Test all three branches: 403 (chip, rows and
  the message must survive a reload, since the state is re-persisted through
  `PUT /api/literature/workspace`), genuine 404 (chip dropped, no message — force it by deleting
  the row with the owner's token while the chip is still on the bench), and 503 (chip still dropped
  silently while the server row survives — a transient outage therefore costs the uploader the
  reference to a paper that is still stored and still billed to retention).
- Deleting a workspace used to flash `no workspace with that id`; the detail re-read now swallows a
  404 (`SharedWorkspaces.tsx`). Screenshot the panel within ~1 s of the click, not only after it
  settles, or the flash is missed.
- Watch the copy under the workspace switcher: it should mention that Literature-bench papers are
  shared, only the adder may remove one, and privately added papers stay private.
- S3 mode (`DOCUMENT_S3_BUCKET` + `AWS_ENDPOINT_URL_S3` at a local `python -m moto.server`) works
  on the shared path too: the row holds `b"AGS3\x01"+key`, the object is ciphertext (`AGD1\x01`,
  no `%PDF`), and killing moto yields **503** `stored documents are temporarily unavailable; retry
  shortly` for owner and member alike with the row intact.

## CDP file uploads with two windows

`cdp_setfile.py` picks the *first* page target matching `localhost:`, which may be the Incognito
window. Select the target whose URL contains the page you want (e.g. `/literature`), or navigate
the other window away first — otherwise the PDF chip silently lands in the wrong account.

## Typing invitation tokens

`xdotool type` occasionally **drops a character** from a 43-char token, and the join then fails
with `that invitation is not valid` — which looks like a product bug. After typing, read the field
back over CDP (`Array.from(document.querySelectorAll('input')).map(i=>i.value)`) and compare it to
the issued token before clicking Join.

## Invitation mail (`INVITE_EMAIL_SENDER` / SES)

By default `INVITE_EMAIL_SENDER` is blank, `mailer_for()` returns `None`, no boto3 client is built,
and the panel falls back to `Send this invitation to them yourself — no mail was sent …` with the
one-time token. The token is shown in **both** the delivered and undelivered cases by design, so a
visible token is not evidence that mail failed — check `delivered` in the response / the wording.

To test the configured path without AWS, run a tiny local fake SES (a plain HTTP listener that parses
the SES v1 `SendEmail` form POST and writes every field to JSON, answering with a real
`Throttling` error while a marker file exists) and restart the backend with:

```
INVITE_EMAIL_SENDER=invites@askgrey.test  INVITE_EMAIL_REPLY_TO=replies@askgrey.test
SES_CONFIGURATION_SET=askgrey-invites     PUBLIC_APP_URL=http://localhost:8000
AWS_ENDPOINT_URL_SES=http://127.0.0.1:5112  AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test
AWS_DEFAULT_REGION=us-east-1
```

`AWS_ENDPOINT_URL_SES` is honoured by botocore, so no code change is needed. Note `SesMailer`
allows **2 attempts**, so one refused invite legitimately produces two/three capture records — that
is retry behaviour, not a duplicate send. Grade the message from the capture (subject must name the
workspace on one line and must not contain the token; text and HTML must both carry
`PUBLIC_APP_URL/workspace?invite=<token>`, the recipient address and an expiry date), and always
take the token for the browser test **out of the captured message**, not the API response.

Host-header rewriting: re-issue the same invite with `Host: evil.example`; the captured link must
still use `PUBLIC_APP_URL`.

Mailed-link flow to check: `/workspace?invite=<token>` prefills the redeem field, strips `invite=`
from the URL (`replace: true`), shows "The invitation from your email is ready", and does **not**
redeem until Join — verify `workspace_invites.accepted_at` is still NULL before clicking. Logged out,
the same URL routes to `/login` and the token survives register/login because `RequireAuth` carries
`pathname + search`.

Caveat worth reporting, not a failure: the mailed-link hint names the **signed-in** account's
address, not the invited address, so opening someone else's link reads as if it were yours until
Join returns `that invitation was sent to a different address`.

Refusal cases and their exact UI strings: reused → `that invitation has already been used or was
revoked`; wrong address → `that invitation was sent to a different address`; revoked → same as
reused; expired → `that invitation has expired; ask for another` (force by backdating
`workspace_invites.expires_at` with `backend/.venv/bin/python`, there is no `sqlite3` CLI).

Leakage sweep: grep the uvicorn logs and `GET /api/audit/events` for every recipient address and
every issued token. `workspace.invited` detail should be only `{workspace_id, role, emailed}`, and
the Audit tab should render "Invited someone to a workspace · role … · emailed true|false".

## Order of operations

Run `Delete workspace` **last**: it cascades every shared artifact/protocol, every membership and
every invite row that earlier assertions depend on.

## Devin Secrets Needed

- `ANTHROPIC_API_KEY` — only for LLM-backed artifacts (protocol drafting, regulatory, Literature
  extraction). Screening profiles and grants budget/eligibility are deterministic and key-free.
