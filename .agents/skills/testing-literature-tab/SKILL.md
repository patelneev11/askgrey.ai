---
name: testing-literature-tab
description: How to run and end-to-end test the askgrey.ai Literature workspace (PDF upload, column extraction, citation viewer, exports, persistence) locally, including the Anthropic key requirement and the Vite dev-server reload pitfall.
---

# Testing the askgrey.ai Literature tab locally

## Services

```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8000
cd frontend && npm run dev            # http://localhost:5173, proxies /api to :8000
```

Node 20.18 emits a "Vite requires Node 20.19+" warning; dev server and `npm run build`
still work, so it can be ignored.

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
