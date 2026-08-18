# On-call runbook

Where to look first, in order. Everything below assumes shell access to the host's logs and a
signed-in session against the affected environment.

## 0. Ninety-second triage

```bash
curl -s https://<host>/api/health                      # process alive?
curl -s -H "Authorization: Bearer $TOKEN" \
     https://<host>/api/status/dependencies | jq        # whose fault is it?
curl -s -H "Authorization: Bearer $TOKEN" \
     https://<host>/api/status/llm-cost | jq            # is spend the story?
```

| Symptom | Look at |
| --- | --- |
| `/api/health` does not answer | host/platform: is the container up, did the last deploy fail, did it fail to boot (see §1) |
| Health OK, one feature broken | `/api/status/dependencies` — a `degraded`/`unhealthy` provider is upstream, not us |
| Health OK, everything broken | Sentry, newest issue; then the deploy that preceded it |
| "It was slow" | `duration_ms` on the request lines; `p95_latency_ms` per provider |
| Unexpected Anthropic bill | `/api/status/llm-cost`, then the `askgrey.cost` log lines by `purpose` |

## 1. The app will not start

Startup refuses rather than running insecurely. Read the first lines of the container log:

- `JWT_SECRET` missing, placeholder, or under 32 characters in a non-development environment.
- `CORS_ORIGINS` containing `*` outside development.
- Neither `DOCUMENT_KMS_KEY_ID` nor `DOCUMENT_ENCRYPTION_KEY` set outside development. Set the
  KMS key id (or a base64 32-byte key); do not work around it by rotating `JWT_SECRET` into
  service as the document key, which is exactly what this check exists to prevent.

All three are configuration, fixed on the host and redeployed. Never "fix" them by setting
`ENVIRONMENT=development` in a deployed environment — that also disables HSTS.

## 2. A user reports a specific failure

Ask for the time and, if the browser console is open, the `request_id` (every failed API call
is logged with it; it is also the `X-Request-ID` response header).

```bash
# everything that happened during that one request, across services
grep '"request_id":"<id>"' app.log | jq
# or, without an id: what failed in that minute
grep '"level":"ERROR"' app.log | jq 'select(.timestamp | startswith("2026-08-13T14:32"))'
```

The request line gives path, status and duration. Audit events for the same request id show
what the user was doing. A traceback arrives as the `exception` field on the same line.

If the user only says "it broke": Sentry, filtered by their user id.

## 3. A dependency is failing

`/api/status/dependencies` gives error rate, p95 latency and the last error per provider.

- Only one provider unhealthy → upstream. Check their status page; the feature that uses it
  degrades but the rest of the app is fine. PubMed and PubChem rate-limit per IP, so a burst
  from one host shows as 429s counted as failures.
- SBIR.gov returning 403 from a given host is a WAF block on that egress IP, not an outage —
  known, and documented with the grants service.
- Every provider unhealthy at once → our egress (DNS, network policy, proxy), not seven
  simultaneous outages.
- `unused` means nobody has called it recently; it is not a failure.

Counters are per process and reset on restart, so a redeploy erases the evidence — capture the
snapshot before restarting anything.

### Stored papers return 503

`stored documents are temporarily unavailable` with `the document key service is unavailable` in
the log means KMS refused or could not be reached. Nothing is lost — that status exists so a key
outage cannot be mistaken for corruption and delete the rows. Check, in order: the KMS key's state
(`Enabled`, not `Disabled` or `PendingDeletion`), the task role's `kms:Decrypt` on it, `AWS_REGION`,
and KMS throttling in CloudWatch. Uploads fail the same way and for the same reason: a document is
not stored under a weaker key when KMS is unavailable.

A 404 on a paper that existed is the opposite case: the row failed authentication and was deleted
(`discarding an undecryptable stored document`). That is a changed key or a tampered row, and the
user can add the paper again.

## 4. Spend spike

1. `/api/status/llm-cost` → `by_model` and today's total; the WARNING line
   `llm daily spend threshold crossed` marks when it crossed.
2. Attribute it: `grep '"logger":"askgrey.cost"' app.log | jq -r .purpose | sort | uniq -c` —
   extraction on large PDFs dominates by orders of magnitude over query translation.
3. Contain it: lower `LLM_DAILY_CALL_BUDGET` (hard per-account ceiling) and redeploy; unset
   `ANTHROPIC_API_KEY` to fall back to the rule-based paths where they exist, which degrades
   PubMed translation and grants matching rather than breaking them.
4. Reconcile with the Anthropic console. The in-app figure is an estimate from token counts and
   prices hard-coded in this repo.

## 5. Suspected credential leak

1. Disable the key at the provider first — removing it from a file or a repo is not
   remediation.
2. Rotate the host variable and redeploy.
3. For `JWT_SECRET`, rotation invalidates every access token immediately and every refresh
   session at next use. That is the intended blast radius; users sign in again.
4. Check the audit log (`"logger":"askgrey.audit"`) for what the credential was used for.

## 6. Rollback

Redeploy the previous commit — there is no automatic rollback. Reverting code is enough only
when the release ran no migration: `alembic upgrade head` runs before the server starts, and an
older image does not undo it. If the bad release migrated, downgrade explicitly
(`alembic downgrade -1` against `DATABASE_URL`) before or after redeploying the older commit,
depending on whether the old code can read the new schema. After a rollback, note that the
dependency and cost counters restart from zero.

## Known blind spots when nothing here explains it

Nothing polls `/api/health` between deploys, nothing pages anyone, counters are process-local
and there is no retained time series. If an incident left no trace, that is why —
[monitoring.md](./monitoring.md) lists the gaps in full.
