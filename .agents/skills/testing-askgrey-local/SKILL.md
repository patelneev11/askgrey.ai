---
name: testing-askgrey-local
description: How to run askgrey.ai locally (backend + frontend), authenticate, and exercise LLM-backed tabs such as Protocol Creation end-to-end in a browser.
---

# Testing askgrey.ai locally

## Bring the stack up
1. Backend (FastAPI, port 8000). LLM-backed routes read `anthropic_api_key` from settings, which
   pydantic-settings populates from the `ANTHROPIC_API_KEY` env var, so the key must be bound to the
   uvicorn process itself (not just your shell tool call):
   `exec(command=".venv/bin/uvicorn app.main:app --port 8000", workdir="<repo>/backend", env={"ANTHROPIC_API_KEY": "secret:repo:patelneev11/askgrey.ai:ANTHROPIC_API_KEY"})`
   Without the key, `/api/protocols/draft` and `/api/protocols/controls/review` return 503; the
   deterministic routes (`/calculator/*`, `/checklist`, save/history, `/export/eln`) still work.
2. Frontend: `npm run dev` in `frontend/` (port 5173, proxies `/api` to :8000). Health check is
   `GET /api/health` (there is no `/api/system/health`).
3. If vite fails to start, reinstall the rolldown native binding:
   `(cd frontend && npm install --no-save @rolldown/binding-linux-x64-gnu@$(node -p "require('rolldown/package.json').version"))`

## Auth
Every `/api/*` feature route needs a bearer token. Fastest path: register through the UI
(`/login` → "No workspace yet? Create one", password must be ≥12 chars), or seed a user with
`POST /api/auth/register {email, password, full_name}` and then sign in through the UI so the
browser holds the session. After first login two overlays appear and must be dismissed before
screenshots: the 4-step product tour ("Skip") and the per-tab intro popover ("I understand").

## Protocol Creation tab (`/protocol`)
- Drafting is a real Anthropic call and takes ~40-60 s; the submit button shows "Drafting…" and a
  pulsing "drafting" pill. Control review takes ~15-20 s.
- Version history only shows a diff after two saves: the first "Save version" records
  "v1 Initial draft saved", then edit a step and save again to get "v2 … (modified)".
- The master mix calculator recalculates **server-side** on every keystroke/scale change
  (`POST /api/protocols/calculator/recalculate`). Backend applies a default **10 % dead-volume
  overage**, so totals are `per_reaction × wells × 1.10` (e.g. 5 uL × 24 = 132 uL). A browser-side
  reimplementation would show 120 uL — a good adversarial check that the numbers come from the API.
- ELN export is payload-only: it never contacts Benchling and must stay labelled
  `schema_ready_untested` with an amber "Untested against live API" pill.
- Safety invariant to re-check on any UI change: the `CaveatBand` "DRAFT — Agent-drafted content.
  Requires qualified researcher review before lab use." renders unconditionally, and the only
  `data-tone="validated"` pill on the page is "Arithmetic verified · this panel only". Enumerate
  pills with `document.querySelectorAll('[data-tone]')` and confirm visibility with a screenshot.

## Devin Secrets Needed
- `ANTHROPIC_API_KEY` (repo scope) — required for protocol drafting and control review.
