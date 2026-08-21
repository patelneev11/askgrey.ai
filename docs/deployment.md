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
| `DOCUMENT_KMS_KEY_ID` (+ `AWS_REGION`) | on AWS: a KMS key id, ARN or alias. Stored papers then get a per-document data key minted by KMS, the master key never enters the process, and every read is a CloudTrail record. The task role needs `kms:GenerateDataKey` and `kms:Decrypt` on that key only |
| `DOCUMENT_ENCRYPTION_KEY` | the alternative off AWS: base64, 32 bytes decoded. One of this and `DOCUMENT_KMS_KEY_ID` is **required** outside development — the app refuses to boot with neither, because the fallback derives the document key from `JWT_SECRET` and rotating that would make every stored paper unreadable |
| `DOCUMENT_S3_BUCKET` (+ optional `DOCUMENT_S3_PREFIX`, `AWS_REGION`) | on AWS: stored papers' ciphertext goes to `documents/<user_id>/<document_id>` in that bucket and the row keeps metadata and the key. Leave it unset and the ciphertext stays in the database, where every backup carries the PDFs. Block Public Access, disable ACLs, set default encryption to the same KMS key, and give the task role `s3:PutObject`/`s3:GetObject`/`s3:DeleteObject` on that prefix only — no `s3:List*`, no access key of its own. Turning it on later needs no migration; existing rows keep opening from the column. Details in [storage security design](./storage-security-design.md) |
| `SENTRY_DSN`, `RELEASE` | see [monitoring](./monitoring.md) |
| `LLM_DAILY_COST_ALERT_USD`, `LLM_DAILY_CALL_BUDGET` | spend guards |
| `FRONTEND_DIST_DIR` | set only for single-origin hosting, where FastAPI serves the built SPA (see below) |
| `TRUSTED_PROXY_HOPS` | `1` on Railway. The platform terminates traffic at its edge proxy, so the peer address the app sees is the proxy for every visitor; left at `0` the per-source-address sign-in limit becomes one global bucket and any single client can lock everybody out. Count only proxies you control — each claimed hop trusts one more attacker-supplied `X-Forwarded-For` entry |

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
  correct response to a suspected leak. It no longer touches stored papers, which is why a
  document key of its own is required outside development.
- Rotating the KMS master key needs nothing from this app: existing rows hold data keys wrapped
  under the previous key version, and KMS unwraps them by version. Rotating a local
  `DOCUMENT_ENCRYPTION_KEY`, by contrast, orphans every row written under the old one (they are
  then dropped on read and re-addable), so plan that as a migration rather than a variable change.
- Turning KMS on later is safe in either order: the scheme is recorded in each stored row, so
  papers sealed under the local key keep opening under it while new ones go to KMS. Keep both
  variables set until the old rows have aged out of retention.
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
- No re-encryption job: there is no command that rewrites existing rows under a new scheme or a
  new local key. Migration happens by writing new rows and letting old ones expire.
- KMS is not cached: every read of a stored paper is a `kms:Decrypt` call. Fine at this volume,
  and the first thing to revisit if per-request latency or KMS spend matters.
- No blue/green or automatic rollback. Rollback is redeploying the previous commit.
- No secret manager: provider-held environment variables are the store. KMS holds the document
  master key when `DOCUMENT_KMS_KEY_ID` is set, but `JWT_SECRET` and `ANTHROPIC_API_KEY` are still
  plain environment variables rather than Secrets Manager references.
