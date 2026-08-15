# What is monitored, and what is not

## Monitored

**Liveness** — `GET /api/health`, unauthenticated, returns `{"status":"ok"}` and names nothing
about the deployment. Point an external uptime monitor at it; the deploy workflow polls it
after every deploy.

**Runtime errors** — Sentry on both sides (`backend/app/core/errors.py`,
`frontend/src/lib/observability.ts`). Off unless a DSN is set, which is how development and CI
run. Request bodies, cookies, `Authorization`/`x-api-key` headers and the refresh cookie are
dropped before an event is sent; `send_default_pii` is off, so no email addresses or IPs — a
Sentry event identifies a user by id only. Backend log records at WARNING and above become
events; INFO becomes breadcrumbs.

**Dependency health** — `GET /api/status/dependencies` (authenticated). Every outbound call to
PubMed, PubChem, ClinicalTrials.gov, grants.gov, SBIR.gov, the PDF fetcher and Anthropic goes
through `MonitoredAsyncClient`, which records outcome and latency. Status over the last 50
calls per provider:

| Status | Meaning |
| --- | --- |
| `unused` | no calls in the window — no opinion, deliberately not "healthy" |
| `healthy` | <20% failures, or fewer than 5 calls |
| `degraded` | ≥20% failures |
| `unhealthy` | ≥50% failures |

5xx, 429 and transport errors count against the provider. 4xx does not: a rejected query is
our bug or the user's, not an outage.

**LLM spend** — `GET /api/status/llm-cost` (authenticated) meters Anthropic's reported input
and output tokens against per-model prices in `backend/app/core/llm_cost.py`, attributed to the
feature that spent it (`pdf_extraction`, `pubmed_translation`, `grants_matching`). Every call
logs its cost at INFO; crossing `LLM_DAILY_COST_ALERT_USD` logs one WARNING for the day, which
also becomes a Sentry event. The separate per-account daily *call* budget still applies and is
the hard ceiling.

**Structured logs** — one JSON object per line, every line carrying the `request_id` that is
returned to the caller as `X-Request-ID`. Access lines record method, path, status and
duration; audit events, LLM spend and dependency failures share the same stream. Set
`LOG_JSON=false` for human-readable output locally.

**Frontend logs** — one `logger` (`src/lib/observability.ts`) instead of scattered
`console.*`: sign-in/out, extraction start/finish, export completion, and every failed API call
with route, status, duration and the backend's `X-Request-ID`. Query strings and extraction
goals are never logged, only their shape.

## Not monitored yet

- **No external uptime monitor is configured.** The endpoint exists; nothing polls it between
  deploys. Point Better Stack / UptimeRobot / Checkly at `/api/health` — this is the single
  biggest remaining gap.
- **No alert destination.** Alerts are WARNING log lines and Sentry events. Nothing pages
  anyone; wire Sentry to Slack/PagerDuty.
- **Counters are process-local.** Dependency health, the cost meter and the rate limiters live
  in memory in one process. With more than one API instance each sees only its own traffic, and
  a restart zeroes all of them. Treat `/api/status/*` as a live gauge, not a ledger.
- **Cost figures are estimates.** They come from Anthropic's reported token counts and prices
  hard-coded in this repo, and drift the moment provider pricing changes. Reconcile against the
  Anthropic console before believing a number that matters.
- **No metrics backend.** No Prometheus/OpenTelemetry, no dashboards, no retained time series —
  history exists only as long as the log retention of the host.
- **No log aggregation.** Logs go to stdout; whatever the host keeps is what there is. No
  cross-service search.
- **No tracing.** `traces_sample_rate` defaults to 0. Request ids make a single request
  followable in logs, not a distributed trace.
- **No synthetic checks of user journeys.** Nothing exercises login → extraction → export on a
  schedule, so a break in that flow surfaces when a user hits it.
- **No business/product analytics.** Deliberate: usage telemetry on research content is not
  something to add without an explicit decision.
- **Operational endpoints are authenticated, not role-restricted.** Any signed-in user can read
  them. There is no admin role yet; add one before the workspace has untrusted members.
