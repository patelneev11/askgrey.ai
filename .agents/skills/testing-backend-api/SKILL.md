---
name: testing-backend-api
description: How to run and end-to-end test the askgrey.ai FastAPI backend (auth, screening/status routes, external-API-backed services) with a live uvicorn server and HTTP calls.
---

# Testing the askgrey.ai backend over HTTP

## Run the server
```bash
cd backend && .venv/bin/uvicorn app.main:app --port 8000 > /tmp/uvicorn8000.log 2>&1 &
```
Logs are single-line JSON on stdout (`askgrey.request` per request, plus per-service loggers
such as `app.services.screening.patents.service` with `outcome`/`status` fields) — redirect them
to a file and grep, that is the primary evidence source for "what happened server-side".

## Auth
```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"tester1@example.com","password":"Str0ngPassw0rd!23"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -H "Authorization: Bearer $TOKEN" ...
```
API rate limit is ~120 requests/min per account; on `429` just register a fresh email.
Unauthenticated calls to routed endpoints return `401 {"detail":"Not authenticated"}`.

## Route prefixes (easy to get wrong)
- All routers are mounted under `/api` (`app/main.py`).
- Health is `GET /api/health` — **not** `/health`.
- The system router's prefix is `/status`, so it is `GET /api/status/dependencies` and
  `GET /api/status/llm-cost` — **not** `/api/system/...`.
- External-API providers appear in `/api/status/dependencies` only after a call is attempted;
  the provider name must be in `KNOWN_PROVIDERS` (`app/core/dependency_health.py`).
  Note: an HTTP 4xx from upstream still counts as a completed call there, so a rejected API key
  can show as `status: "healthy"` — do not use that endpoint to prove upstream auth worked.

## Testing services that call external APIs without having the API key
Every external client takes its base URL from `Settings` (e.g. `USPTO_ODP_BASE_URL`,
env-var-overridable), so you can point it at a local server and get full end-to-end coverage:

1. **Prove no egress happens** when the key is unset: start a tiny `http.server` that logs every
   request, run the app with `<SERVICE>_BASE_URL=http://127.0.0.1:9101/api/v1` and no key, issue
   requests, assert the sink log has **0** lines. Then repeat with `<SERVICE>_API_KEY=fake` as a
   control to prove the sink would have caught a call (avoids a vacuous pass).
2. **Prove the happy path** by having the local server return the repo's own fixtures
   (`backend/tests/fixtures/<service>/*.json`) — this exercises parsing, paging and the
   "no matches" branch through the real route.
3. **Prove degradation** by returning 401/403/5xx from the local server, or by using a fake key
   against the real upstream if outbound network is allowed.

Also inspect the sink's recorded query string to verify exactly what user input became upstream
parameters (a good way to catch query-injection or filter-construction bugs).

## Gotchas
- Do **not** use `pkill -f "port 8001"` to stop a server: `pkill -f` also matches your own shell
  command line and kills the calling shell. Use `pkill -f "app.main:app --port 8001"` from a
  different phrasing, or record the PID with `$!`.
- When a key *is* configured, the `httpx` INFO logger prints the full outbound URL, including the
  derived query text. If you are asserting "no user query text in logs", expect this line.

## Devin Secrets Needed
None for the default path. Optional, only to exercise real upstream success paths:
`USPTO_ODP_API_KEY` (free USPTO Open Data Portal key), `ANTHROPIC_API_KEY` (LLM-backed routes).
