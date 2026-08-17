---
name: testing-backend-api
description: How to run and end-to-end test the askgrey.ai FastAPI backend (auth tokens, LLM-backed grant routes, audit-log/leak probes) without any external API keys.
---

# Testing the askgrey.ai backend API

## Run the server
```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn app.main:app --port 8000    # logs are JSON lines on stdout
```
Health check: `GET /api/health` → `{"status":"ok"}` (note the `/api` prefix; `/health` is 404).
Checks: `.venv/bin/pytest -q`, `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app`.

## Get a bearer token
All non-auth routes use `HTTPBearer`. Register once (password must be >= 12 chars):
```bash
curl -s -X POST localhost:8000/api/auth/register -H 'content-type: application/json' \
  -d '{"email":"tester@example.com","password":"TestPassword123!","full_name":"Tester"}'
# -> {"access_token": "...", "token_type": "bearer"}   (access token TTL is short; re-login via /api/auth/login if it expires)
```
Then send `Authorization: Bearer <token>`. Missing/invalid token → 401 `{"detail":"Not authenticated"}`.

## Swagger UI may be unusable
`/docs` loads swagger-ui JS from cdn.jsdelivr.net and can render as a **blank page** in the sandboxed
browser even when the CDN is reachable from the shell. `/openapi.json` renders fine in Chrome and is the
better visual artifact: use Chrome's Ctrl+F on it to demonstrate schema field names and to prove that
secrets/prompts do not appear (e.g. `system_prompt` → 0/0 matches).

## Testing LLM-backed routes with no ANTHROPIC_API_KEY
This environment usually has no `ANTHROPIC_API_KEY`, so `Settings.anthropic_api_key == ""` and LLM-backed
services intentionally return **503** instead of fabricating output. To exercise a happy path against a
live server without any network call, wrap the real app and override the FastAPI dependency, e.g. for the
grant review board:
```python
# /tmp/rb_stub_app.py
from app.api.grants import get_review_board
from app.main import app
from app.services.grants.review_board import ReviewBoard, PersonaReview, CriterionScore

class StubReviewer:
    model = "stub-model-not-anthropic"
    async def review(self, persona, criteria, section): ...  # return a PersonaReview

app.dependency_overrides[get_review_board] = lambda: ReviewBoard.from_config_file(reviewer=StubReviewer())
```
```bash
cd backend && PYTHONPATH=/tmp .venv/bin/uvicorn rb_stub_app:app --port 8001
```
Run the no-key (503) assertions against :8000 and the full-shape assertions against :8001. Unit-level
recorded-transport stubs for the same services live in `backend/tests/**/conftest.py` (e.g.
`tests/grants/review_board/conftest.py`'s `ScriptedClaude`). Never call the real vendor API.

## Leak / audit probes worth repeating
- Service configs that carry prompts (e.g. `app/services/grants/review_board/personas.json`) must never
  reach a response: grep raw response bodies and `/openapi.json` for distinctive prompt substrings.
- `app/core/audit.py` writes one JSON line to the `askgrey.audit` logger. Put a unique sentinel phrase in
  the user text you submit and grep the server log for it — user content, prompts and keys must not appear.
- Beware ordering: audit `*.sent_to_llm` events are recorded *before* the vendor call, so a request that
  then fails (e.g. 503 with no key) still logs a "sent" provenance line. Check this when auditing accuracy.

## Devin Secrets Needed
- `ANTHROPIC_API_KEY` — only if a real (non-stubbed) LLM round trip must be proven; all other backend
  testing works without it.
