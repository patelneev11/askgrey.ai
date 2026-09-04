---
name: testing-literature-tab
description: How to run and end-to-end test the askgrey.ai Literature workspace (PDF upload, column extraction, citation viewer, exports, persistence) locally, including the Anthropic key requirement and the Vite dev-server reload pitfall.
---

# Testing the askgrey.ai Literature tab locally

Bring-up, auth and onboarding overlays are in the `testing-askgrey-shell` skill, which also has
the deeper Literature material (citation-highlight assertions, export verification, timeout and
backend-failure states). This file is the extraction-specific part.

## Devin Secrets Needed

- `ANTHROPIC_API_KEY` (repo secret `secret:repo:patelneev11/askgrey.ai:ANTHROPIC_API_KEY`).
  Column extraction is **not** available without it: `backend/app/services/pdf_extraction/service.py`
  raises `ExtractorUnavailableError` ("no LLM credentials are configured") → HTTP 503. There is no
  deterministic pdfplumber-only fallback for extraction. Pass the key through the process env
  of the uvicorn command; do not write it to disk.

## Test PDF

`backend/tests/fixtures/pdf_extraction/trial_ziprasidone.pdf` is a real 3-page open-access
paper — copy it to `~/Downloads` and upload it through the UI. A good goal string is
`sample size, dosing regimen, primary efficacy endpoint` (yields 3 cited columns, ~20 s).

## Known pitfall: reload logs you out on the Vite dev server

On `http://localhost:5173`, pressing F5 redirects to `/login`. Backend logs show
`auth.refresh outcome=success` immediately followed by `auth.refresh_reuse outcome=denied`:
React `StrictMode` (`frontend/src/main.tsx`) double-invokes the `AuthProvider` mount effect,
the second `api.refresh()` replays the already-rotated refresh token, and the backend treats
that as token reuse and kills the session. This makes persistence/reload testing impossible
in dev mode.

Workaround for testing persistence: run the **production build** behind a single origin.
There is no static-file serving in `backend/app/main.py` on this branch, so use a small
local harness that serves `frontend/dist` and proxies `/api` to `:8000` (see
`/tmp/prodserve.py` pattern: `SimpleHTTPRequestHandler` with `directory=dist`, SPA fallback to
`index.html`, and `urllib` proxying for `/api`). Then test on `http://localhost:4173`.

If the reload logout ever reproduces in a production build, it is a real auth bug (refresh
rotation not tolerant of concurrent/duplicate refresh), not a StrictMode artifact.

## Measuring viewport widths without CDP

The browser-console/CDP tools are often unavailable here. The X display is 1600x1200 while
screenshots are scaled to 1024 wide (factor 1.5625), so resize the Chrome window precisely with
`DISPLAY=:0 xdotool getactivewindow windowsize 1280 1100` and measure panes by multiplying
screenshot pixel distances by 1.5625.

## Testing the S3 document object store (`DOCUMENT_S3_BUCKET`) without AWS

`backend/app/core/blobs.py` builds its boto3 client with **only** `region_name` — there is no
`endpoint_url` setting. You do **not** need a code change to point it at a fake S3: botocore
honours the `AWS_ENDPOINT_URL_S3` environment variable for an endpoint-less client. Recipe:

```bash
# fake S3 (in-memory)
cd backend && setsid nohup .venv/bin/python -m moto.server -p 5111 -H 127.0.0.1 &
# create the bucket with the same env you will give the backend
AWS_ENDPOINT_URL_S3=http://127.0.0.1:5111 AWS_ACCESS_KEY_ID=k AWS_SECRET_ACCESS_KEY=s \
  AWS_DEFAULT_REGION=us-east-1 .venv/bin/python -c \
  "import boto3;boto3.client('s3').create_bucket(Bucket='askgrey-test')"
# backend in S3 mode
DOCUMENT_S3_BUCKET=askgrey-test AWS_ENDPOINT_URL_S3=http://127.0.0.1:5111 … uvicorn app.main:app
```
Startup log line `"message": "document storage key configured", "storage": "s3"` confirms the mode,
and the Settings tab's "Stored paper location" row is the user-visible oracle.

Storage oracles (assert these, not the UI chip):
- inline row: `content[:5] == b"AGD1\x01"` and `len(content) == byte_size + 35`
- pointer row: `content == b"AGS3\x01" + "documents/<user_id>/<document_id>"`, `len(content) < 200`
- object: `len == byte_size + 35`, does not start `%PDF`, contains no `%PDF` anywhere

### Traps

- **Uploading a PDF in the UI does not store it.** The file is staged client-side; the row and the
  S3 object are only written when **Generate columns** runs. Checking the DB right after the
  chip appears will show nothing and look like a bug.
- **Document ids are content-addressed**, so re-uploading byte-identical bytes creates no new row.
  Keep a pool of distinct PDFs per account.
- **moto is in-memory**: restarting it silently destroys the bucket, so recreate the bucket before
  any test that assumes the object exists. A pointer row then resolves to `NoSuchBucket`, which is
  deliberately *not* a missing-object code — a vanished or mistyped bucket is a **503** outage, not
  an orphan, so it must never delete rows. To exercise the orphan branch (404 `no such document`,
  row dropped) delete the single object with `boto3` and leave the bucket in place.
- **Two outage shapes behave very differently, and only one shows the intended message:**
  - `kill` moto (connection *refused*) → `EndpointConnectionError` fast → HTTP **503**, banner
    `<file>: stored documents are temporarily unavailable; retry shortly` in ~3 s. Use this shape.
  - `kill -STOP` moto (socket open, never answers) → botocore retries/timeouts for ~**305 s**; the
    frontend gives up at 180 s and shows `The server did not respond within 180s…`, so the 503 text
    never reaches the user. If you only test this shape you will wrongly record a failure of the
    message; if you only test the refused shape you will miss the hang. Test both.
- **Judge the outage from a surface that renders errors.** `workspace.tsx ensureFile` swallows PDF
  fetch failures with a `logger.warn` only. Drive **Generate** on a restored source
  (`extractFromStoredDocument`), whose failure becomes the labelled red banner.
- **Delete outcomes are distinguished by status, so assert the storage oracle *and* the chip:**
  404 (object genuinely gone) drops the chip and its extracted rows; 403 (a colleague's shared
  paper) and 503 (storage outage) restore both and explain why, because the row is still stored.
- **An orphan drop clears its chip and rows**, so a dropped row no longer leaves a source that
  re-errors `no such document` on every Generate.

### Cross-account isolation on the S3 path

The app keeps the access token **in memory only** (not in localStorage/sessionStorage/cookies), so
you cannot lift account A's token out of the browser. Register account B over the API, probe with
B's token, and prove A is unharmed via the **UI** (citation still renders) plus the DB/bucket
oracle. Expect B's `GET /api/literature/documents/<A_doc>/pdf` and `DELETE …` to return a
404 body byte-identical to a never-existing id.
