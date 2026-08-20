# Document storage security design (T7 / issue #24)

This is the design persistence has to satisfy. The first persistence layer has now shipped, so the
sections below say which requirements it meets and which are still prospective.

## What is true today — encrypted bytes, in a bucket when one is configured

- An uploaded PDF is stored against the uploading account (`literature_documents`) so a reload can
  still render a cited page. The stored bytes are AES-256-GCM ciphertext produced by
  `backend/app/core/crypto.py`; the plaintext never reaches the database or the bucket.
- Where that ciphertext lives is `DOCUMENT_S3_BUCKET`'s answer (`backend/app/core/blobs.py`).
  Set, and the object goes to `s3://<bucket>/[<prefix>/]documents/<user_id>/<document_id>` while
  the row keeps the metadata and a pointer to that key. Unset, the row holds the ciphertext, which
  is right for a clone and wrong for a deployment: every database backup would carry the PDFs.
- The row records which of the two it is, so adopting a bucket is a configuration change and not a
  migration — rows written before it keep opening from the column.
- The ciphertext is bound to `user_id:document_id` as GCM associated data, so a row moved to
  another account, relabelled with another document id, or edited in place fails authentication and
  is dropped rather than served.
- Reads, deletes and extraction re-runs go through `backend/app/services/literature.py`, which
  filters on the caller's own `user_id`. Somebody else's document is a 404, indistinguishable from
  one that was never stored.
- Retention is `DOCUMENT_RETENTION_DAYS` (default 90). Expired rows are deleted when read and
  purged on the next write; `DELETE /api/literature/documents/{id}` and clearing the workspace
  delete immediately.
- Extraction results and review-table state still live in the browser tab, not the database.
- The key comes from one of two places, recorded per row rather than inferred from the current
  configuration (see "Keys" below): a KMS-minted per-document data key, or one local key.

What is **not** yet true: there is no per-workspace key and no scheduled purge job — retention is
enforced opportunistically on access. Files also transit Anthropic during extraction; see
`docs/llm-data-flow.md`.

## Keys

`DOCUMENT_KMS_KEY_ID` set (the deployed configuration):

- Storing a document calls `kms:GenerateDataKey` for a one-off 256-bit key, encrypts with it,
  discards it, and stores only KMS's wrapped copy in the same column as the ciphertext.
- Reading calls `kms:Decrypt` to unwrap that copy. The master key never enters the process, so a
  stolen database dump is inert without the task role's KMS permissions.
- `{app, user_id, document_id}` travels as the KMS encryption context, so the owner is
  authenticated twice: by KMS at the unwrap and by AES-GCM at the decrypt. A wrapped key lifted
  onto another account's row is refused at the first step.
- Every read is a CloudTrail record, which is the point: access to stored papers becomes auditable
  outside this app's own log. The master key rotates without re-encrypting a single row.
- Cost and latency: one KMS call per store and per read.
- The task role needs `kms:GenerateDataKey` and `kms:Decrypt` on that key, and nothing else.

`DOCUMENT_ENCRYPTION_KEY` set instead: one local base64 32-byte key for every document. Simpler,
and appropriate outside AWS, but rotating it makes existing rows unreadable and the key sits in the
process's environment.

Neither set: the key is derived from `JWT_SECRET` via HKDF. Development only — `Settings` refuses
to boot any other environment that way, because rotating `JWT_SECRET` (the first thing rotated
after a suspected token leak) would otherwise destroy every stored paper.

A key service that cannot be reached is reported as `DocumentKeyUnavailableError` → HTTP 503, and
is deliberately *not* a decryption failure: unreadable rows are deleted, so a KMS outage or a
revoked credential must not be able to masquerade as corruption and empty the library.

## The bucket

`BlobStoreUnavailableError` → HTTP 503 draws the same line for S3, for the same reason. An object
the bucket says is not there (`NoSuchKey`) is an orphan and the row is dropped; a bucket that does
not answer — a timeout, throttling, an `AccessDenied` from a policy tightened by mistake — keeps
the row and fails the request. Deletion goes object first, row second, so an interruption leaves a
row pointing at nothing (cleaned up on the next read) rather than an object nothing points at, and
a delete the bucket refuses does not report success.

What the bucket must be, none of which this app can assert about it:

- **Block Public Access** on, at the account level as well as the bucket. The objects are
  ciphertext, so a leak is not a disclosure of papers — it is still a disclosure of who stores how
  many, and of the account ids in the key names.
- **Bucket owner enforced** object ownership (ACLs disabled), and a bucket policy denying anything
  that is not the task role, plus `aws:SecureTransport: false`.
- **Default encryption** with the same KMS key. Redundant with the app's own sealing, and what an
  auditor looks for; `S3Blobs` also asks for `aws:kms` per object when `DOCUMENT_KMS_KEY_ID` is set.
- **Versioning** on, with a lifecycle rule expiring noncurrent versions after a short window.
  Versioning without that rule quietly keeps deleted papers, which contradicts the retention
  promise; a few days of it is what recovers from a bad deploy.
- **A lifecycle expiry** at least as long as `DOCUMENT_RETENTION_DAYS`, as a backstop for objects
  the app failed to delete. The app is the primary enforcement; the bucket is the safety net.
- **CloudTrail data events** on the bucket if reads of stored papers need to be auditable outside
  the app's own log. This is billable per event — turn it on deliberately.
- **No cross-region replication** unless data residency has been decided; replication copies the
  ciphertext into another jurisdiction.

The task role needs exactly this, and no `s3:List*`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::<bucket>/documents/*"
    },
    {
      "Effect": "Allow",
      "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
      "Resource": "<document key ARN>"
    }
  ]
}
```

Credentials come from the task role or instance profile — the app never takes an access key of its
own, and there is no S3 setting it reads besides the bucket, the optional prefix and the region.

## Requirements for the persistence layer

### Tenancy and object keys

- Every stored object belongs to exactly one account. Shipped: the account id is part of the key
  (`documents/{user_id}/{document_id}`), so a cross-tenant read is a key that cannot be
  constructed by accident, and an object listing names neither the paper nor its filename.
- Prospective: `document_id` as a random token rather than today's digest of the bytes. The digest
  is guessable by anyone holding the same paper, which is why the read is scoped by `user_id` —
  unguessability is defence in depth, never the control.
- The database row is the source of truth for ownership; the key layout only makes mistakes visible.

### Authorization on every access

- Authorization is checked on every read, write and delete against the caller's workspace
  membership — not once at upload time, and not by trusting a client-supplied workspace id.
- The check belongs in a single accessor (e.g. `DocumentStore.get(user, document_id)`) that raises
  when the document's workspace is not one the user belongs to. No route reads storage directly.
- A document the caller may not read returns 404, not 403: a 403 confirms the id exists.
- If pre-signed URLs are used for download, they are short-lived (minutes), single-object,
  and minted only after the same authorization check. They are never handed out at list time.

### Encryption

- Shipped: application-level AES-256-GCM before the bytes reach the database, keyed either by a
  per-document KMS data key or by `DOCUMENT_ENCRYPTION_KEY`. This protects lost media and database
  backups, not a compromised application, which holds the decrypt path either way.
- Shipped: per-document keys under KMS, which is the rotatable, revocable, CloudTrail-audited
  arrangement PHI-adjacent data needs. Encryption alone is not sufficient for PHI: that also
  requires HIPAA-eligible AWS services with a BAA, and a zero-retention/BAA arrangement with
  Anthropic before document text is sent for extraction.
- Shipped: server-side encryption requested per object under the same KMS key, on top of the app's
  own sealing. Set default encryption on the bucket too, so an object written by anything else is
  covered.
- At rest: server-side encryption on the bucket/volume with a managed KMS key, plus TLS in transit
  everywhere. This is the baseline, and it protects against lost media and misconfigured backups —
  not against a compromised application, which holds the decrypt path either way.
- Per-workspace keys are the upgrade if a customer requires it. Worth the operational cost only
  when contractually needed; state honestly which of the two is deployed.
- Encrypt derived artefacts too — extraction results quote the document verbatim, so an unencrypted
  results table leaks the document.

### Retention and deletion

- Default retention: uploads and their derived extraction results are deleted 30 days after last
  access, configurable per workspace. A document nobody has opened in a month is liability, not an
  asset.
- Shipped for papers: deletion, workspace clearing, retention expiry and quota eviction all delete
  the object as well as the row, and a bucket that refuses the delete fails the request rather than
  reporting a deletion that did not happen.
- Deletion is a real delete of the object and every derived row (extraction cells, citations,
  export artefacts), not a `deleted_at` flag that leaves the bytes readable. Soft-delete is
  acceptable only as a short grace window (≤7 days) that a hard-delete job then honours.
- Workspace deletion deletes all of its objects. This is the request an enterprise customer will
  make, and it must not require engineering.
- Deletions are recorded in the security audit log (`backend/app/core/audit.py`) with actor,
  document id and time — the audit entry outlives the document deliberately.
- Backups have a stated, bounded lifetime, and a deletion is not complete until backups age out.
  Say the number to customers rather than implying instant erasure.

### Uploads

The ingest-side controls already shipped (streaming 25 MB cap, `%PDF` signature check, parse
concurrency limit — see PR #25) apply before anything is stored. Storage does not relax them, and
the stored content type is recorded server-side rather than trusted from the upload.

## Out of scope here

Client-side/end-to-end encryption, customer-managed keys and data residency are real enterprise
asks, but they change the product architecture (the server cannot extract from a document it
cannot read). They need a product decision first, not a storage ticket.
