# Document storage security design (T7 / issue #24)

This is the design that persistence has to satisfy **before** it ships. It exists because the
security review flagged storage as prospective: there is no persistence layer yet, so there is
nothing to harden today, and the risk is that one gets added later without any of this.

## What is true today — no persistent storage exists

Be precise about this, because "uploaded files" sounds like storage:

- An uploaded PDF is read into memory in the request, parsed, and discarded when the response is
  returned. No copy is written to disk, to object storage, or to the database.
- Extraction tables and review-table state live in the browser tab. A reload clears the workspace.
- The database holds users and refresh sessions only (`backend/app/models/`) — no documents, no
  extraction results, no compound data.

So today there is **no encryption at rest for uploaded documents, no retention policy and no
deletion control** — not because they were skipped, but because there is nothing persisted to
apply them to. Files do transit Anthropic during extraction; that flow is documented separately in
`docs/llm-data-flow.md`. Nobody should tell a customer their documents are encrypted at rest.

## Requirements for the first persistence layer

### Tenancy and object keys

- Every stored object belongs to exactly one workspace. The workspace id is part of the storage
  key (`workspaces/{workspace_id}/documents/{document_id}`), so a cross-tenant read is a key that
  cannot be constructed by accident.
- `document_id` is a random UUIDv4 (or 128-bit token), never a sequence, hash of the filename, or
  anything derived from user input. Unguessability is defence in depth, not the control.
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
