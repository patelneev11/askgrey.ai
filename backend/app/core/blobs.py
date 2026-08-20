"""Where a stored paper's ciphertext lives: this database, or an S3 bucket.

The database column works, and is what a clone or a test runs on with nothing configured. It is
the wrong home for a growing pile of PDFs: every backup carries them, a dump is gigabytes of
paper bytes, and the row limit is the only thing standing between one account and the disk. Set
`DOCUMENT_S3_BUCKET` and the ciphertext moves to object storage — priced per byte, versionable,
lifecycle-expirable, replicated by the platform — while the row keeps the metadata and the
wrapped key it was sealed under.

What does *not* change is the encryption. Bytes are already sealed by `app.core.crypto` before
they arrive here, under a per-document data key that S3 never sees, so this module moves
ciphertext and nothing else: a bucket left readable is an exposure of blobs no reader can open
without the app's KMS permissions. Server-side encryption is still requested on write, because
defence in depth costs nothing here and it is what an auditor looks for.

The row says where its bytes are, so the answer is a property of the row rather than of today's
configuration: rows written before the bucket existed keep working, and turning the bucket off
does not orphan the rows written after it (they say so, and say which key).

    content column == b"AGS3\\x01documents/<user>/<document>"   -> the bucket
    content column == anything else                            -> the ciphertext itself

Failures are split the same way the key service's are, and for the same reason: callers delete
rows they cannot read, so "the bucket did not answer" must never be confused with "there are no
bytes there". The first keeps the row and becomes a 503; only the second deletes it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from botocore.exceptions import ClientError

from app.core.config import Settings

# Versioned, and deliberately not valid ciphertext under the crypto envelope: a pointer can
# never be mistaken for the bytes it points at.
POINTER_MAGIC = b"AGS3"
POINTER_VERSION = 1
_POINTER_PREFIX = POINTER_MAGIC + bytes([POINTER_VERSION])
MAX_KEY_CHARS = 1024

# S3 error codes that mean the object is not there. Anything else — throttling, a missing
# credential, a network fault, a permission the task lost — says nothing about the object.
_MISSING_CODES = frozenset({"NoSuchKey", "NoSuchBucket", "404", "NotFound"})


class BlobStoreUnavailableError(Exception):
    """The object store could not be reached, or refused a call for a reason that may pass.

    Not a missing object: a read that raises this keeps the row, so an S3 outage or a revoked
    policy cannot be mistaken for a deleted paper and delete the library it could not reach.
    """


class BlobMissingError(Exception):
    """The object store answered, and there is nothing at that key.

    The row is then a pointer to nothing — an orphan from an interrupted delete or a lifecycle
    rule — and the caller may drop it.
    """


def object_key(user_id: str, document_id: str, *, prefix: str = "") -> str:
    """One object per (account, document), so deletion is a key and not a search.

    The document id is a digest of the paper's bytes, and the account owns the path, which
    means a key reveals nothing about the paper — no filename, no title.
    """
    path = f"documents/{user_id}/{document_id}"
    prefix = prefix.strip().strip("/")
    return f"{prefix}/{path}" if prefix else path


def pointer_to(key: str) -> bytes:
    """What goes in the row when the bytes went to the bucket."""
    return _POINTER_PREFIX + key.encode("utf-8")


def pointed_key(stored: bytes) -> str | None:
    """The key this row's bytes live at, or None when the row *is* the bytes."""
    if not stored.startswith(_POINTER_PREFIX):
        return None
    key = stored[len(_POINTER_PREFIX) :].decode("utf-8", "replace")
    if not key or len(key) > MAX_KEY_CHARS:
        # A pointer to nothing usable is a corrupt row, not an outage: let the caller drop it.
        raise BlobMissingError("the stored row carries an unusable object key")
    return key


class S3Blobs:
    """Ciphertext in an S3 bucket, one object per stored document."""

    def __init__(
        self,
        bucket: str,
        *,
        region: str = "",
        prefix: str = "",
        kms_key_id: str = "",
        client: Any | None = None,
    ) -> None:
        self._bucket = bucket
        self._region = region
        self._prefix = prefix
        self._kms_key_id = kms_key_id
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _build_client(self._region)
        return self._client

    def key_for(self, user_id: str, document_id: str) -> str:
        return object_key(user_id, document_id, prefix=self._prefix)

    def put(self, key: str, data: bytes) -> None:
        """Write the ciphertext, asking the bucket to encrypt it again on its own account."""
        extra: dict[str, str] = {}
        if self._kms_key_id:
            extra = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self._kms_key_id}
        try:
            self.client.put_object(Bucket=self._bucket, Key=key, Body=data, **extra)
        except Exception as exc:
            # A failed write must not leave a row claiming bytes that are not there, so this
            # is raised rather than swallowed, and the store call fails with it.
            raise BlobStoreUnavailableError(_reason(exc)) from exc

    def get(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self._bucket, Key=key)
            body = response["Body"].read()
        except Exception as exc:
            raise _translate(exc) from exc
        if not isinstance(body, bytes):
            raise BlobStoreUnavailableError("the object store returned something that is not bytes")
        return body

    def delete(self, key: str) -> None:
        """Remove the object. A key that is already gone is a success, not a failure."""
        try:
            self.client.delete_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            translated = _translate(exc)
            if isinstance(translated, BlobMissingError):
                return
            raise translated from exc


def _reason(exc: Exception) -> str:
    if isinstance(exc, ClientError):
        return f"the document object store is unavailable ({_code(exc)})"
    return f"the document object store is unavailable: {type(exc).__name__}"


def _code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


def _translate(exc: Exception) -> Exception:
    if isinstance(exc, ClientError) and _code(exc) in _MISSING_CODES:
        return BlobMissingError(f"the object store has nothing at that key ({_code(exc)})")
    return BlobStoreUnavailableError(_reason(exc))


def _build_client(region: str) -> Any:
    """Imported here, not at module scope, so a deployment without a bucket builds no client."""
    import boto3

    return boto3.client("s3", **({"region_name": region} if region else {}))


@lru_cache(maxsize=4)
def _store_for(bucket: str, region: str, prefix: str, kms_key_id: str) -> S3Blobs:
    """One store (and one boto3 client, which is not cheap to build) per configuration."""
    return S3Blobs(bucket, region=region, prefix=prefix, kms_key_id=kms_key_id)


def store_for(settings: Settings) -> S3Blobs | None:
    """The configured object store, or None when the database holds the ciphertext."""
    bucket = settings.document_s3_bucket.strip()
    if not bucket:
        return None
    return _store_for(
        bucket,
        settings.aws_region.strip(),
        settings.document_s3_prefix.strip(),
        settings.document_kms_key_id.strip(),
    )


__all__ = [
    "POINTER_MAGIC",
    "BlobMissingError",
    "BlobStoreUnavailableError",
    "S3Blobs",
    "object_key",
    "pointed_key",
    "pointer_to",
    "store_for",
]
