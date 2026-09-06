---
name: testing-release-container
description: How to end-to-end test the askgrey.ai release/deployment shape (repo-root Dockerfile image + Postgres + S3 document storage on a single origin), rather than the Vite/uvicorn dev servers — including migration-gated boot, restart/rollback, S3 pointer proofs and the console checks that only the built bundle can fail.
---

# Testing the askgrey.ai release container (deployment shape)

Use this when the task is about the deployment/release path (Dockerfile, `deploy/docker-entrypoint.sh`,
`infra/aws/*`) rather than a feature. The point is to test the **built** artifact: things dev mode
hides — CSP, hashed asset paths, SPA fallback, cookie refresh on one origin, SSE through the app
server.

## Bring it up

```bash
cd <repo root>
docker build -t askgrey:local .                 # multi-stage: Vite build -> FastAPI serving FRONTEND_DIST_DIR
docker network create askgrey-rel
docker run -d --name askgrey-db --network askgrey-rel \
  -e POSTGRES_PASSWORD=askgrey-local -e POSTGRES_DB=askgrey postgres:16-alpine
# env file: ENVIRONMENT=production, DATABASE_URL=postgresql://postgres:askgrey-local@askgrey-db:5432/askgrey,
# JWT_SECRET, DOCUMENT_ENCRYPTION_KEY (base64 32B), ANTHROPIC_API_KEY, AWS_REGION, DOCUMENT_S3_BUCKET,
# AWS keys, CORS_ORIGINS empty (single origin)
docker run -d --name askgrey-app --network askgrey-rel --env-file /tmp/askgrey_release.env -p 8080:8000 askgrey:local
```

Everything is then at `http://localhost:8080` — SPA **and** `/api` on one origin. Do not test
`:5173`/`:8000` in this mode. Wait for `docker inspect -f '{{.State.Health.Status}}' askgrey-app` to
read `healthy` (HEALTHCHECK curls `/api/health`). `/api/health/ready` is **not** a route — a 404 for
it in the log is expected and is not what the ALB/ECS probes use (both use `/api/health`).

## Checks that only the built bundle can fail

- Cold load, then read the console. Expect **zero** errors: no `Refused to … Content Security Policy`,
  no 404 for `/assets/index-*.js|css`. A quick oracle for asset status:
  `performance.getEntriesByType('resource').filter(r=>r.initiatorType!=='fetch').map(r=>[r.name,r.responseStatus])`.
- Deep link by typing `http://localhost:8080/assistant` in the address bar, then F5. Must render the
  real page and stay signed in (SPA fallback + refresh cookie over plain http).
- `/api/*` must NOT be swallowed by the fallback: loading an API path in the browser returns JSON
  (401/403/200), never the app shell.
- The citation viewer (PDF raster + highlight) is the CSP-sensitive path — always click a cited cell.
- Assistant streaming proves SSE survives the single origin: screenshot a growing partial answer.

## Storage: pointer in the DB, ciphertext in the bucket

There is no `sqlite3` here — use psql inside the DB container:

```bash
docker exec askgrey-db psql -U postgres askgrey -c \
 "select user_id, document_id, byte_size, left(encode(content,'escape'),70) from literature_documents;"
```

A stored paper's `content` must read `AGS3\x01documents/<user_id>/<document_id>` (~50 bytes) while
`byte_size` is the real plaintext size. Then `aws s3api head-object --bucket <bucket> --key
documents/<user_id>/<document_id>`.

**Pitfall:** the app's AWS user has no `s3:ListBucket`, so a *missing* key answers **403 / AccessDenied
(ListBucket)** rather than 404. So prove deletion by shape: get-object succeeds *before* the UI delete
and fails *after*, not by listing a prefix.

Delete through the UI: the source chip's `aria-label="Remove <filename>"` button. Pass = chip stays
gone (no "is still stored" rollback), the `literature_documents` row is gone, the S3 key is no longer
readable, Workspace flips to `Stored papers · 0 MB / Nothing stored`, and Audit logs
`Deleted a stored paper`.

## Migrations own the schema (the ECS-safety property)

`deploy/docker-entrypoint.sh` is `set -eu`: `alembic upgrade head` then `exec uvicorn`. Verify:

- `docker logs askgrey-app | head` — the alembic lines come **before** `Uvicorn running`.
- `select version_num from alembic_version;` equals `docker exec askgrey-app alembic heads`.
- A container pointed at an unreachable DB must **exit non-zero and never bind**:

```bash
docker run -d --name askgrey-badmig --network askgrey-rel --env-file <env> \
  -e DATABASE_URL=postgresql://postgres:x@nope:5432/askgrey askgrey:local
docker wait askgrey-badmig                      # expect 1
docker logs askgrey-badmig | grep -c "Uvicorn running"   # expect 0
docker rm askgrey-badmig
```

If this ever serves anyway, that is a real defect: ECS would replace a healthy task with a broken one.

## Restart / rollback shape

`docker restart askgrey-app`, poll health back to `healthy`, then reload the browser: the session
should still be valid and saved protocols / audit rows / stored papers intact (migrations re-run as a
no-op).

## What this shape cannot cover (say so in the report)

No ALB and no TLS (HSTS only observable as a header), no RDS (a Postgres container stands in), no KMS
envelope unless the KMS ARN is available — the boot log prints `"scheme": "local-key"` when the local
document key is used, no `terraform apply` (init/validate/fmt only without a domain), no live
Benchling tenant, and SBIR.gov may be WAF-blocked from the box (`403`), which is an external
condition rather than an app defect.

## Devin Secrets Needed

- `ANTHROPIC_API_KEY` — extraction, drafting, assistant turns.
- AWS credentials for the document bucket (`DOCUMENT_S3_BUCKET`, `AWS_REGION`) if the S3 storage
  variant is under test. Prefer a scratch bucket; if the real prod bucket is used, delete what you
  upload through the UI at the end.
