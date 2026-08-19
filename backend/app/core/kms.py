"""AWS KMS as the source of the keys stored documents are encrypted under.

Envelope encryption: KMS mints a one-off 256-bit data key per document and hands back both the
plaintext key and a copy wrapped under a customer master key that never leaves KMS. The app
encrypts with the plaintext key, discards it, and stores the wrapped copy beside the ciphertext.
Reading a document means asking KMS to unwrap that copy.

What this buys over one app-held key: the master key is rotatable and revocable without touching
the database, a stolen database dump is useless without the caller's KMS permissions, and every
unwrap is a `kms:Decrypt` entry in CloudTrail — so reads of stored papers become auditable
outside the app's own log. What it costs: one KMS call on each store and each read.

The owning account and document id travel as the KMS encryption context, so they are
authenticated twice over — by KMS when unwrapping and by AES-GCM when decrypting. A wrapped key
lifted onto another user's row fails at the first step.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

from botocore.exceptions import ClientError

from app.core.config import Settings

DATA_KEY_SPEC = "AES_256"
DATA_KEY_BYTES = 32


class KeyUnavailableError(Exception):
    """The key service could not be reached, or refused the call for a reason that may pass.

    Distinct from a decryption failure on purpose: a disabled key, an expired credential or a
    network fault says nothing about whether the ciphertext is genuine, so callers must not
    treat it as a corrupt row and delete it.
    """


class WrappedKeyRejectedError(Exception):
    """KMS refused this wrapped key for this owner and document: it is not what it claims."""


@dataclass(frozen=True)
class DataKey:
    """A freshly minted key: `plaintext` to encrypt with now, `wrapped` to store."""

    plaintext: bytes
    wrapped: bytes


class KeyWrapper(Protocol):
    """The two operations the document store needs from a key service."""

    def generate_data_key(self, *, user_id: str, document_id: str) -> DataKey: ...

    def unwrap_data_key(self, wrapped: bytes, *, user_id: str, document_id: str) -> bytes: ...


def encryption_context(user_id: str, document_id: str) -> dict[str, str]:
    """The context KMS authenticates. Must match exactly between wrap and unwrap."""
    return {"app": "askgrey", "user_id": user_id, "document_id": document_id}


class KmsKeyWrapper:
    """A `KeyWrapper` backed by a KMS customer master key."""

    def __init__(self, key_id: str, *, region: str = "", client: Any | None = None) -> None:
        self._key_id = key_id
        self._region = region
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _build_client(self._region)
        return self._client

    def generate_data_key(self, *, user_id: str, document_id: str) -> DataKey:
        try:
            response = self.client.generate_data_key(
                KeyId=self._key_id,
                KeySpec=DATA_KEY_SPEC,
                EncryptionContext=encryption_context(user_id, document_id),
            )
        except Exception as exc:  # boto3 raises ClientError and friends
            # A failure to mint a key is always operational: there is no ciphertext yet to
            # be wrong about.
            raise KeyUnavailableError(f"the KMS key is unavailable: {type(exc).__name__}") from exc
        return DataKey(
            plaintext=_a_data_key(response["Plaintext"]), wrapped=response["CiphertextBlob"]
        )

    def unwrap_data_key(self, wrapped: bytes, *, user_id: str, document_id: str) -> bytes:
        try:
            response = self.client.decrypt(
                CiphertextBlob=wrapped,
                # Named explicitly rather than relying on the blob's own metadata, so a blob
                # wrapped under some other key is refused instead of quietly decrypted.
                KeyId=self._key_id,
                EncryptionContext=encryption_context(user_id, document_id),
            )
        except Exception as exc:
            raise _translate(exc) from exc
        return _a_data_key(response["Plaintext"])


# KMS error codes that mean "this ciphertext is not valid under this key and context". Anything
# else — throttling, a disabled or pending-deletion key, a missing credential, a network fault —
# is transient or operational, and must not be read as a corrupt document.
_REJECTION_CODES = frozenset({"InvalidCiphertextException", "IncorrectKeyException"})


def _a_data_key(plaintext: object) -> bytes:
    """Refuse anything that is not a 256-bit key rather than let AES-GCM decide what it is."""
    if not isinstance(plaintext, bytes) or len(plaintext) != DATA_KEY_BYTES:
        raise KeyUnavailableError("KMS returned something that is not a 256-bit data key")
    return plaintext


def _translate(exc: Exception) -> Exception:
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code in _REJECTION_CODES:
            return WrappedKeyRejectedError(f"KMS refused the wrapped key ({code})")
        return KeyUnavailableError(f"the KMS key is unavailable ({code})")
    # A timeout, a DNS failure, a missing credential: no verdict on the ciphertext at all.
    return KeyUnavailableError(f"the KMS key is unavailable: {type(exc).__name__}")


def _build_client(region: str) -> Any:
    """Imported here, not at module scope, so a deployment without KMS never builds a client."""
    import boto3

    return boto3.client("kms", **({"region_name": region} if region else {}))


@lru_cache(maxsize=4)
def _wrapper_for(key_id: str, region: str) -> KmsKeyWrapper:
    """One wrapper (and one boto3 client, which is not cheap to build) per configured key."""
    return KmsKeyWrapper(key_id, region=region)


def wrapper_for(settings: Settings) -> KeyWrapper | None:
    """The configured key service, or None when documents are sealed under a local key."""
    key_id = settings.document_kms_key_id.strip()
    if not key_id:
        return None
    return _wrapper_for(key_id, settings.aws_region.strip())


__all__ = [
    "DataKey",
    "KeyUnavailableError",
    "KeyWrapper",
    "KmsKeyWrapper",
    "WrappedKeyRejectedError",
    "encryption_context",
    "wrapper_for",
]
