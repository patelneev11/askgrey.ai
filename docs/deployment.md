# Deployment: AWS, variables and secrets

One deployed environment for now — production, on AWS in the account that already holds the
documents bucket and its KMS key. One container serves both halves of the app on one origin
(`Dockerfile`), ECS Fargate runs it behind an application load balancer, RDS Postgres holds the
schema, and `JWT_SECRET`, `DATABASE_URL` and the provider keys are resolved from Secrets Manager
at task start. Infrastructure is Terraform in [`infra/aws`](../infra/aws); the deploy workflow
only ships code onto it.

A staging environment is the same `terraform apply` with a different `name`, `hostname` and
bucket. It does not exist yet, and the workflow deploys production from `main`.

## First apply

From `infra/aws`, with an admin credential in the shell (not the `askgrey-app` document key,
which deliberately cannot create anything):

```
terraform init
terraform apply \
  -var hostname=app.askgrey.ai \
  -var documents_kms_key_arn=arn:aws:kms:us-east-2:<account>:key/<key-id>
```

What the variables decide, in order of how much they matter:

| Variable | Default | Notes |
| --- | --- | --- |
| `hostname` | — | the name the certificate is issued for and the app is reached at |
| `documents_kms_key_arn` | — | the existing `askgrey-documents` key; must be in `region` |
| `route53_zone_id` | empty | given a zone, Terraform writes the validation record and the alias itself and the apply waits for the certificate. Empty, it prints the record for your registrar and the HTTPS listener needs a second apply once it validates |
| `private_tasks_with_nat` | `false` | `false` puts the task in a public subnet with a public address and inbound from the load balancer's security group only. `true` moves it to a private subnet behind a NAT gateway — no public address anywhere, for about **$33/month** more |
| `documents_bucket` | `askgrey-documents-prod` | existing bucket, not managed here |
| `desired_count` | `1` | `1` costs one task and still rolls without a gap (200% maximum). `2` survives a zone |
| `db_instance_class` / `db_allocated_storage` | `db.t4g.micro` / 20 GiB | papers are in S3, so this holds rows and audit events |
| `invite_email_sender` | empty | an SES-verified address. Empty means no `ses:SendEmail` in the task role at all, and invitations stay copyable tokens |

The apply creates the Anthropic and USPTO secrets **empty** — a key in Terraform state is a key
in a file. Paste them once, then redeploy:

```
aws secretsmanager put-secret-value --secret-id askgrey/anthropic-api-key --secret-string '<key>'
```

## Continuous deployment

Every push to `main` builds the image, pushes it to ECR, registers a task definition that
differs from the running one only by image tag, and rolls the service. The service's deployment
circuit breaker rolls back a task that fails its migration or its health check, and
`aws ecs wait services-stable` is what makes that rollback a failed run.

CI holds no AWS key: the workflow assumes `askgrey-github-deploy` over OIDC, and that role's
trust policy names `repo:<owner>/<repo>:ref:refs/heads/main` only. It can push an image and roll
the service; it cannot read the app's secrets.

Set these as **repository or `production` environment variables** (all non-secret) from the
Terraform outputs:

| Name | From | Notes |
| --- | --- | --- |
| `AWS_DEPLOY_ROLE_ARN` | `github_deploy_role_arn` | unset, the workflow fails with that instruction rather than an opaque credentials error |
| `AWS_REGION` | `us-east-2` | defaulted |
| `ECR_REPOSITORY`, `ECS_CLUSTER`, `ECS_SERVICE` | `askgrey` | defaulted; set them only if `name` was changed |
| `HEALTHCHECK_URL` | `https://<hostname>/api/health` | the deploy fails if this never returns `{"status":"ok"}` |

Rollback is `aws ecs update-service --task-definition <previous revision>`; the last 20 image
tags are kept in ECR for exactly that.

## Getting a shell

`enable_execute_command` is on, so there is no bastion:

```
aws ecs execute-command --cluster askgrey --task <task-id> --container app \
  --interactive --command /bin/sh
```

That is also how a one-off `alembic` command or a `psql` against the private database is run.

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
| `TRUSTED_PROXY_HOPS` | `1` behind the load balancer, which terminates traffic at its edge, so the peer address the app sees is the proxy for every visitor; left at `0` the per-source-address sign-in limit becomes one global bucket and any single client can lock everybody out. Count only proxies you control — each claimed hop trusts one more attacker-supplied `X-Forwarded-For` entry |

Frontend — `frontend/.env.example`. Everything prefixed `VITE_` is compiled into the bundle
and is public: `VITE_SENTRY_DSN` is designed to be, an API key never is.

## Schema changes

The schema is owned by Alembic (`backend/migrations`), and the deploy runs `alembic upgrade
head` before starting the server — see `deploy/docker-entrypoint.sh`, which is also where two
replicas would otherwise race to migrate. A development server migrates itself on startup
instead, so pulling a migration is enough and no local database is left a column behind;
`Base.metadata.create_all` survives only in the tests, which build their schema from the models.

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

- **Split**: a separate host serves the SPA. `CORS_ORIGINS` must then name the frontend origin
  exactly, and `FRONTEND_DIST_DIR` stays empty.
- **Single origin** (what the AWS deployment does): build the frontend and point
  `FRONTEND_DIST_DIR` at it — the image puts it at `/app/frontend-dist`. The
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

- One environment. Staging is the same apply under another `name`, and nobody has run it.
- Nothing takes a database snapshot before a migration; a failed migration stops the release
  (the circuit breaker keeps the previous task serving) but a migration that succeeds and is
  wrong is a restore from the automated backup.
- No re-encryption job: there is no command that rewrites existing rows under a new scheme or a
  new local key. Migration happens by writing new rows and letting old ones expire.
- KMS is not cached: every read of a stored paper is a `kms:Decrypt` call. Fine at this volume,
  and the first thing to revisit if per-request latency or KMS spend matters.
- Rolling deploys with an automatic rollback on a failed health check, but not blue/green: the
  two task definitions share one database, so a rollback across a migration is not automatic.
- A single task by default, so a zone failure is an outage until ECS places a replacement.
- The load balancer has no WAF and no rate limit of its own; the per-address limits are the
  app's, which is why `TRUSTED_PROXY_HOPS` being right matters.
