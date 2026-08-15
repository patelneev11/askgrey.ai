# Security review — askgrey.ai

Scope: the application as it exists across PRs #1–#11 (FastAPI backend, React/Vite frontend).
Method: source review of every route, auth path, provider client, upload path and export writer;
dependency audit (`pip-audit`, `npm audit`); git-history secret search. No live pentest was run
against a deployed environment, so anything that depends on deployment configuration is marked as
such rather than asserted.

Date: 2026-08-13. Reviewed commit: head of `devin/1786752944-ux-fixes`.

---

## Fixed in this pass — CRITICAL: deployable auth bypass via the shipped JWT secret

`Settings.jwt_secret` defaulted to the literal `"dev-secret-change-me"`, committed in
`backend/app/core/config.py`, and nothing checked it at startup. A deployment that forgot
`JWT_SECRET` (Railway env var, `.env` missing, typo'd key) would boot and serve traffic happily
while signing HS256 tokens with a value published in a public repo. Anyone reading the repo could
mint `{"sub": "<any user id>", "type": "access"}` and be that user — every `CurrentUser` route,
including all extraction and export endpoints, falls open. That is an unauthenticated full account
takeover reachable by configuration omission, so it was fixed immediately rather than ticketed.

Fix (deliberately minimal, no architectural change): `Settings` now refuses to construct when
`ENVIRONMENT` is anything other than `development` and the secret is a known placeholder or shorter
than 32 characters. The process fails to boot instead of silently accepting forged tokens.
Development is untouched. Covered by `backend/tests/test_config.py`.

Nothing else in this report was changed; the rest are follow-up tickets.

Also worth knowing: no other authentication bypass was found. Every non-auth route
(`pubmed`, `pubchem`, `clinicaltrials`, `pdf-extraction`, `export`, `grants`) declares `CurrentUser`,
verified by reading each handler, not by grep alone. The intentionally public surface is
`POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/refresh`, `GET /api/auth/sso`
and `GET /api/health`.

---

## Findings by severity

### HIGH

**H1 — Blind SSRF through `POST /api/pdf-extraction/url`** (`backend/app/services/pdf_extraction/fetch.py`)
The endpoint fetches any caller-supplied URL. Scheme is restricted to http(s), but the client sets
`follow_redirects=True` and nothing blocks private, loopback or link-local destinations, and no
re-check happens per redirect hop. An authenticated user can reach `http://169.254.169.254/...`
(cloud metadata), `http://localhost:8000/...`, or any host inside the deployment VPC. The response
body is not returned to the caller, but upstream errors are surfaced verbatim in the 502 detail
(`f"could not fetch {target}: {exc}"`), which distinguishes connection-refused from
timeout from HTTP status — enough to port-scan and fingerprint internal services. If the target
returns a parseable PDF, its content is returned outright.
Fix: resolve DNS and reject non-public IPs before connecting, validate every redirect hop the same
way (or disable redirects and follow manually), and return a generic fetch error to the client.

**H2 — No rate limiting or spend ceiling on any endpoint** (`backend/app/main.py`, all routers)
There is no inbound throttle, per-user quota, concurrency cap or cost budget anywhere. The
per-provider limiters in the service clients are outbound politeness only, and because each route
dependency builds a fresh service per request (`PdfExtractionService.from_settings()` and
equivalents), those limiters are per-request objects and throttle nothing across requests. One
authenticated account can loop `POST /api/pdf-extraction/upload` or `/api/grants/match` and bill
Claude tokens without limit (each extraction is up to 40k context chars + 2048 output tokens; grants
matching enriches up to 25 opportunities per call). This is both a cost-overrun and an availability
exposure, and it is also how NCBI/grants.gov get the deployment's IP blocked.
Fix: per-user and per-IP limits on `/auth/*`, `/pdf-extraction/*`, `/grants/match`; a shared
process-level limiter for outbound provider calls; a daily per-workspace LLM token budget.

**H3 — No login throttling or lockout** (`backend/app/api/auth.py`)
`POST /api/auth/login` has no attempt counter, backoff, lockout or CAPTCHA, so credential stuffing
is limited only by bcrypt cost. `POST /api/auth/register` returns 409 `"Email is already
registered"`, which is a clean account-enumeration oracle. Login itself correctly returns a generic
`"Invalid email or password"`.
Fix: per-account and per-IP throttling with exponential backoff, plus lockout notification; make
registration response timing/shape non-distinguishing or gate it behind email verification.

**H4 — Vulnerable dependencies shipped** (`backend/pyproject.toml`, `frontend/package-lock.json`)
`pip-audit` reports 39 known advisories across 8 packages; `npm audit --omit=dev` reports 3 high.
The ones that matter here: `python-jose==3.3.0` (PYSEC-2024-232/233 — algorithm-confusion and a
JWE decompression DoS; our fixed `algorithms=["HS256"]` list limits but does not eliminate
exposure), `starlette==0.41.3` and `python-multipart==0.0.20` (multiple advisories, both directly
on the multipart upload path this app exposes), `pdfminer-six==20231228` (parser advisories, and it
parses untrusted PDFs by design). Frontend: `@remix-run/router` / `react-router-dom` high advisories.
Fix: upgrade all four backend packages, upgrade react-router, and add `pip-audit` + `npm audit` to
CI so this does not silently rot.

### MEDIUM

**M1 — Refresh tokens cannot be revoked and are never rotated** (`backend/app/core/security.py`,
`backend/app/api/auth.py`) Tokens are stateless JWTs with no server-side registry, no `jti`, and no
denylist. A 14-day refresh token is replayable by anyone who captures it, for its full lifetime;
`POST /api/auth/refresh` issues a fresh pair without invalidating the presented one, so a stolen
token can be used indefinitely in parallel with the legitimate user. There is no logout that
actually ends a session, no "sign out other devices", and no way to cut off a compromised account
short of deleting the user. Password change does not invalidate anything.
Fix: store refresh tokens (hashed) with rotation and reuse detection; add a `token_version` on the
user that password change bumps.

**M2 — Access and refresh tokens live in `localStorage`** (`frontend/src/lib/session.ts`)
Both tokens are readable by any JavaScript on the origin, so a single XSS becomes durable account
takeover (the 14-day refresh token is the prize, not the 30-minute access token). No XSS was found
in the current frontend — React escapes by default and there is no `dangerouslySetInnerHTML` — but
the app renders LLM output and third-party PDF text, which is exactly the content class that turns
into an injection later.
Fix: refresh token in an HttpOnly, Secure, SameSite=Strict cookie (or a BFF session), keeping only
the short-lived access token in memory.

**M3 — Uploads are fully buffered before the size check** (`backend/app/api/pdf_extraction.py`)
`data = await file.read()` reads the entire body into memory, and only then compares against the
25 MB cap; the 413 is returned after the cost has been paid. Concurrent large uploads are a cheap
memory-exhaustion vector, made worse by H2's absence of concurrency limits. There is also no
`Content-Type` or magic-byte check — `%PDF` is never verified — so arbitrary bytes reach pdfplumber
(see H4's pdfminer advisories). The failure is graceful (`UnsupportedPdfError`), so this is defence
in depth, not a live crash.
Fix: enforce the limit while streaming (reject on `Content-Length` and abort mid-stream), verify the
`%PDF-` signature before parsing, and cap concurrent parses.

**M4 — Proprietary document text is sent to Anthropic with no tenant-level control or disclosure**
(`backend/app/services/pdf_extraction/extractor.py`) Up to 40k characters of every uploaded PDF —
which the product explicitly invites to be proprietary compound data — is sent to the Anthropic API.
That is the intended design and the key is server-side only, but there is no per-workspace opt-out,
no data-processing disclosure in the UI, no zero-retention agreement referenced, and no audit record
of what left the perimeter. For the pharma buyers this product targets, that is a procurement
blocker before it is a vulnerability.
Fix: document the flow in the UI and README, confirm Anthropic zero-retention terms, log every
outbound document with workspace attribution, and offer a no-LLM mode.

**M5 — Prompt injection from PDFs and NL queries is unmitigated**
(`backend/app/services/pdf_extraction/extractor.py`, `backend/app/services/pubmed/translation.py`)
Untrusted PDF text is concatenated into the extraction prompt, and untrusted NL queries into the
translation prompt. A crafted paper can instruct the model to fabricate extracted values, which then
appear in the review table as if grounded, and can steer the generated Entrez query. Impact is
bounded — outputs are parsed as JSON, quotes are matched back against the real document (ungrounded
values are marked, not silently trusted), and the generated query is only ever sent to NCBI as an
encoded parameter, never executed locally — but "the citation grounding is the product" makes
fabricated-but-plausible output a correctness and trust issue.
Fix: delimit untrusted spans explicitly in the prompt, treat model output as data only (already
mostly true), and keep surfacing grounding status prominently.

### LOW / INFORMATIONAL

**L1 — `GET /api/health` discloses the environment string** (`backend/app/main.py`) Unauthenticated
callers learn `{"environment": "..."}`. Minor fingerprinting; drop the field or gate it.

**L2 — CORS is permissive within the configured origins** (`backend/app/main.py`)
`allow_credentials=True` with `allow_methods=["*"]`/`allow_headers=["*"]`. Safe today because
`CORS_ORIGINS` is an explicit list and the app uses bearer tokens rather than cookies, but it
becomes load-bearing the moment M2 is fixed with cookies. Deployment-dependent: verify the deployed
`CORS_ORIGINS` is not `*`.

**L3 — No security response headers** No HSTS, `X-Content-Type-Options`, `X-Frame-Options`,
`Referrer-Policy` or CSP is set by the app. A CSP in particular is the mitigation that keeps M2
from being fatal.

**L4 — SSO is an advertisement, not an implementation** (`backend/app/api/auth.py`) `GET /api/auth/sso`
builds an authorize URL, but no code exchange, state/PKCE validation or nonce checking exists yet.
Not a vulnerability today; flagged so the missing state/PKCE is not forgotten when it lands.

**L5 — No audit log of security-relevant events** No record of logins, failed logins, token refreshes,
uploads or exports. The UI has an Audit Trails tab backed by sample data. Required for the SOC 2
posture the product implies.

---

## Areas audited and found clean

- **Password storage** — bcrypt (`bcrypt.hashpw`/`checkpw`) with a per-password salt; input is length-bounded to
  bcrypt's 72-byte truncation limit and a 12-character minimum; hashes are never serialized
  (`UserRead` omits them); login errors are generic; email comparison is case-insensitive.
- **Token verification** — signature and `exp` are checked by the library, the `type` claim is
  checked explicitly so a refresh token cannot be used as an access token, the subject must be a
  string, and the referenced user must still exist on every request.
- **SQL injection** — every query is a SQLAlchemy 2 expression (`select(User).where(func.lower(...))`);
  there is no raw SQL, no string-built query, and no `text()` anywhere in the app.
- **Cross-user file access / IDOR** — there is nothing to reference. Uploads are parsed in memory
  (`pdfplumber.open(io.BytesIO(data))`), never written to disk or object storage, and there is no
  document id, download URL or persisted record. Consequently there is also no at-rest encryption,
  retention policy or deletion behaviour to audit — see the note below.
- **Third-party credentials** — `ANTHROPIC_API_KEY` and `NCBI_API_KEY` are server-side settings only;
  the Anthropic key is used solely as an `x-api-key` request header and appears in no response model,
  no error message (error paths quote status code and body of the upstream response, not headers) and
  no frontend code. PubChem, ClinicalTrials.gov, grants.gov and SBIR.gov need no credentials. No ELN
  or patent provider is integrated, so no credentials exist for them. The frontend reads exactly one
  env var, `VITE_API_URL`. `.env` is gitignored; only `.env.example` (placeholders) is tracked. A
  history search for the previously exposed Anthropic key found no commit containing it. CI/deploy
  workflows reference tokens only as `${{ secrets.* }}`.
- **Plaintext credential logging** — the backend has no `print`, `logging` or logger calls at all, so
  nothing is logged in plaintext (which is its own gap — see L5).
- **CSV/XLSX formula injection** — already handled: `escape_formula` is applied to every CSV field and
  `_text_cell` forces text typing in xlsx, so an extracted value beginning `=`, `+`, `-` or `@` cannot
  execute when the export is opened.
- **Input validation on provider routes** — every query parameter is bounded (`max_length`, `ge`/`le`,
  regex-pinned `sort`), so unbounded fan-out via oversized parameters is not available.
- **XSS** — no `dangerouslySetInnerHTML`, no `innerHTML`, no `eval` in the frontend source.

**On the ticket's storage questions specifically:** "can User A read User B's uploads via a guessable
URL or ID" has no answer today because uploads are never stored — the risk is entirely prospective.
Before any persistence lands (which the workspace-reload gap already argues for), the design needs
tenant-scoped object keys, unguessable ids, authorization on every read, encryption at rest, and a
retention/deletion policy. That is ticket T7 rather than a finding.

---

## Follow-up tickets

| ID | Severity | Title |
| --- | --- | --- |
| T1 | High | Block private/link-local targets and revalidate every redirect hop in the PDF fetcher (H1) |
| T2 | High | Per-user/IP rate limiting, concurrency caps and an LLM spend budget (H2) |
| T3 | High | Login throttling, lockout and non-enumerable registration (H3) |
| T4 | High | Upgrade python-jose, starlette, python-multipart, pdfminer-six, react-router; add audit steps to CI (H4) |
| T5 | Medium | Refresh-token rotation, hashed server-side registry and revocation (M1) |
| T6 | Medium | Move the refresh token to an HttpOnly SameSite cookie; access token in memory (M2) |
| T7 | Medium | Streaming upload limits, `%PDF` signature check, parse concurrency cap (M3) |
| T8 | Medium | Data-handling disclosure, zero-retention confirmation and outbound-document audit for LLM calls (M4) |
| T9 | Medium | Prompt-injection hardening for PDF text and NL queries (M5) |
| T10 | Low | Security response headers incl. CSP; drop the environment string from `/api/health`; verify deployed CORS (L1–L3) |
| T11 | Low | Security event audit log wired to the Audit Trails tab (L5) |
| T12 | Prospective | Tenant-scoped encrypted document storage with retention/deletion, before any upload persistence ships |
