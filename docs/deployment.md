# Deployment: environments, variables and secrets

Two deployed environments, identical in code and different in data:

| | staging | production |
| --- | --- | --- |
| Deploys on | every push to `main` | manual `workflow_dispatch` → `target: production` |
| Data | throwaway; safe to reset | real user workspaces |
| Anthropic key | separate key, low spend cap | production key |
| `LLM_DAILY_COST_ALERT_USD` | low (e.g. `5`) so the alert path is exercised | real budget |

Both are GitHub Environments of those names. Secrets live in the environment, not in the
repository, so a run targeting staging cannot read the production token — that separation is
the point of the split and is lost if the same secrets are set at repository level.

## Required per environment

Configure under **Settings → Environments → {staging,production}**.

Secrets:

| Name | Used by | Notes |
| --- | --- | --- |
| `RAILWAY_TOKEN` | deploy workflow | project-scoped token, not an account token |
| `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | deploy workflow | separate Vercel project per environment |

Variables (non-secret):

| Name | Notes |
| --- | --- |
| `RAILWAY_SERVICE` | defaults to `askgrey-backend` |
| `HEALTHCHECK_URL` | e.g. `https://api.askgrey.ai/api/health`; the deploy fails if this never returns `{"status":"ok"}` |

## Runtime configuration (set on the host, not in the repo)

Backend — the full list is in `backend/.env.example`. The ones that must differ per
environment:

| Variable | Production value |
| --- | --- |
| `ENVIRONMENT` | `production` (or `staging`) — anything other than `development` enables HSTS and enforces the secret checks below |
| `JWT_SECRET` | ≥32 chars, unique per environment; the app refuses to boot on the placeholder. `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `DATABASE_URL` | a managed Postgres URL; the app refuses to boot outside development on a SQLite file, which is per-container and disappears on redeploy. `postgres://`/`postgresql://` are rewritten to the `psycopg` driver, so a provider-supplied URL works unchanged |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE_SECONDS` | optional; sized against the database's connection limit divided by replica count |
| `CORS_ORIGINS` | exact origins; `*` is rejected outside development. Empty is correct when the API serves the SPA itself |
| `ANTHROPIC_API_KEY` | server-side only, never in a `VITE_` variable |
| `SENTRY_DSN`, `RELEASE` | see [monitoring](./monitoring.md) |
| `LLM_DAILY_COST_ALERT_USD`, `LLM_DAILY_CALL_BUDGET` | spend guards |
| `FRONTEND_DIST_DIR` | set only for single-origin hosting, where FastAPI serves the built SPA (see below) |

Frontend — `frontend/.env.example`. Everything prefixed `VITE_` is compiled into the bundle
and is public: `VITE_SENTRY_DSN` is designed to be, an API key never is.

## Schema changes

The schema is owned by Alembic (`backend/migrations`), and the deploy runs `alembic upgrade
head` before starting the server — see `backend/railway.toml`. `Base.metadata.create_all` now
runs only in development and in tests, so a deployed database never has its schema created as a
side effect of a boot.

The baseline revision adopts a database that predates Alembic: it creates each table only if it
is missing, so a deployment whose tables came from the old startup `create_all` can be stamped
by simply upgrading. Migrations read `DATABASE_URL` from the same settings the app uses, so
nothing about the connection lives in `alembic.ini`.

A new migration is written against a database that matches `main`:

```
cd backend && alembic revision --autogenerate -m "what changed"
```

`tests/test_migrations.py` fails if the migrations and the models drift apart, so an autogenerate
diff that is not empty at `head` is a missing migration, not a test problem.

## Single origin or split origin

Both are supported:

- **Split** (what the pipeline does today): Railway serves the API, Vercel serves the SPA.
  `CORS_ORIGINS` must name the frontend origin exactly, and `FRONTEND_DIST_DIR` stays empty.
- **Single origin**: build the frontend and point `FRONTEND_DIST_DIR` at `frontend/dist`. The
  API then serves `index.html` for every non-`/api/` path so client-side routes survive a
  reload, hashed files under `/assets` are served immutable, and `CORS_ORIGINS` can be empty
  because the browser makes same-origin requests. Unknown `/api/` paths still return JSON 404s
  rather than the HTML shell. The process fails to start if the directory has no `index.html`,
  so a missing frontend build is a failed deploy rather than a site of 404s.

## Secret handling rules

- Secrets reach the app as environment variables. Nothing is read from a committed file;
  `.env` is git-ignored and `backend/.env.example` holds names and blanks only.
- Rotation is a host-side variable change plus a redeploy. Rotating `JWT_SECRET` invalidates
  every access token immediately and every refresh session at next use — expected, and the
  correct response to a suspected leak.
- Logs are structured and never include header, cookie or key values; Sentry payloads are
  scrubbed in `backend/app/core/errors.py`.
- A leaked key is disabled at the provider first and rotated second. Removing it from a repo
  is not a remediation on its own.

## Not covered yet

- No infrastructure-as-code: environments are configured by hand in Railway/Vercel/GitHub.
- Migrations run on deploy but are not gated: a release whose migration fails leaves the
  previous container serving traffic, and nothing takes a backup first.
- Uploaded PDFs are `LargeBinary` rows rather than object-storage keys, so the database carries
  up to the per-user quota in blobs and every backup copies them.
- No blue/green or automatic rollback. Rollback is redeploying the previous commit.
- No secret manager (Vault/KMS) — provider-held environment variables are the store.
