"""Encryption of the document bytes this app stores, applied before they reach the database.

AES-256-GCM with a fresh random nonce per blob. The owning user id and the document id are
bound in as additional authenticated data, so a row moved to another account — or relabelled
with another document id — fails to decrypt instead of decrypting into the wrong library.

What this protects against: a database dump, a managed provider's backup, a stray read replica
or a stolen disk. What it does not protect against: a compromise of the running process, which
can obtain the key. Column-level encryption is not a substitute for the database's own
encryption at rest; it means the two have to be broken separately.

Two ways to get the key the bytes are sealed under, chosen by configuration:

* KMS envelope encryption, when `DOCUMENT_KMS_KEY_ID` is set. Every document gets its own data
  key, minted by KMS and stored only in wrapped form; the master key never enters this process,
  is rotatable without re-encrypting anything, and every read leaves a CloudTrail record.
* one local key, from `DOCUMENT_ENCRYPTION_KEY`, or — in development only, where config allows
  it to be unset — derived from `JWT_SECRET` so a fresh clone runs with nothing to configure.

Both schemes write a self-describing envelope, so which one produced a stored row is a property
of the row and not of the current configuration: turning KMS on does not orphan the rows written
before it, and a KMS-sealed row is never mistaken for a locally sealed one.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import Settings, get_settings
from app.core.kms import KeyUnavailableError, WrappedKeyRejectedError, wrapper_for

KEY_BYTES = 32
NONCE_BYTES = 12
# Versioned so a future scheme can be told apart from this one without guessing.
DERIVATION_INFO = b"askgrey.document-encryption.v1"

# Envelope: MAGIC | scheme | wrapped key length (2 bytes, big-endian) | wrapped key | nonce |
# ciphertext. Bytes without the magic prefix are read as the original unframed layout — nonce
# followed by ciphertext, under the local key.
ENVELOPE_MAGIC = b"AGD1"
SCHEME_LOCAL = 1
SCHEME_KMS = 2
_HEADER_BYTES = len(ENVELOPE_MAGIC) + 1 + 2
MAX_WRAPPED_KEY_BYTES = 4096


class DocumentKeyError(Exception):
    """The configured key is unusable, so nothing should be stored under it."""


class DecryptionError(Exception):
    """The stored bytes did not authenticate under this key, owner and document id."""


class DocumentKeyUnavailableError(Exception):
    """The key service could not be consulted, so whether the bytes are valid is unknown.

    Deliberately not a `DecryptionError`: callers delete rows that fail to decrypt, and a KMS
    outage, a revoked credential or a key left in `PendingDeletion` would otherwise turn an
    operational fault into the deletion of every stored paper.
    """


def document_key(settings: Settings | None = None) -> bytes:
    """The 32-byte local key stored documents are encrypted under.

    An explicit `DOCUMENT_ENCRYPTION_KEY` (base64, 32 bytes decoded) is used as given. With
    none set the key is derived from `JWT_SECRET` via HKDF: it keeps a clone runnable, and it
    is a real key rather than a constant, but it ties the two secrets together — rotating
    `JWT_SECRET` makes already-stored papers unreadable. That is why config refuses to boot a
    deployed environment without a key of its own (see `Settings`); it is survivable in
    development, because every row is a copy of a paper the user can add again, and unreadable
    rows are deleted rather than served (see `app.services.literature`).
    """
    settings = settings or get_settings()
    configured = settings.document_encryption_key.strip()
    if configured:
        return _decode_key(configured)
    return HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=None,
        info=DERIVATION_INFO,
    ).derive(settings.jwt_secret.encode("utf-8"))


def _decode_key(configured: str) -> bytes:
    try:
        key = base64.b64decode(configured, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DocumentKeyError(
            "DOCUMENT_ENCRYPTION_KEY must be base64; generate one with "
            '`python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"`'
        ) from exc
    if len(key) != KEY_BYTES:
        raise DocumentKeyError(
            f"DOCUMENT_ENCRYPTION_KEY must decode to {KEY_BYTES} bytes, got {len(key)}"
        )
    return key


def _associated_data(user_id: str, document_id: str) -> bytes:
    return f"{user_id}:{document_id}".encode()


def _frame(scheme: int, wrapped: bytes, nonce: bytes, sealed: bytes) -> bytes:
    header = ENVELOPE_MAGIC + bytes([scheme]) + len(wrapped).to_bytes(2, "big")
    return header + wrapped + nonce + sealed


def encrypt_document(
    plaintext: bytes, *, user_id: str, document_id: str, settings: Settings | None = None
) -> bytes:
    """One self-describing value to store in one column: header, wrapped key, nonce, ciphertext.

    Raises `DocumentKeyUnavailableError` when KMS is configured but cannot mint a key — better
    to refuse the upload than to fall back to a weaker key the reader would not expect.
    """
    settings = settings or get_settings()
    wrapper = wrapper_for(settings)
    if wrapper is None:
        key, scheme, wrapped = document_key(settings), SCHEME_LOCAL, b""
    else:
        try:
            data_key = wrapper.generate_data_key(user_id=user_id, document_id=document_id)
        except KeyUnavailableError as exc:
            raise DocumentKeyUnavailableError(str(exc)) from exc
        key, scheme, wrapped = data_key.plaintext, SCHEME_KMS, data_key.wrapped
        if not wrapped or len(wrapped) > MAX_WRAPPED_KEY_BYTES:
            # The length is a two-byte field, and a blob this size is not a wrapped key.
            raise DocumentKeyUnavailableError("KMS returned an unusable wrapped key")

    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(key).encrypt(nonce, plaintext, _associated_data(user_id, document_id))
    return _frame(scheme, wrapped, nonce, sealed)


def decrypt_document(
    stored: bytes, *, user_id: str, document_id: str, settings: Settings | None = None
) -> bytes:
    settings = settings or get_settings()
    scheme, wrapped, nonce, sealed = _split(stored)
    if scheme == SCHEME_KMS:
        wrapper = wrapper_for(settings)
        if wrapper is None:
            # The row was written under KMS and the deployment has since dropped the key id.
            # That is a configuration regression, not a bad row: say so instead of deleting it.
            raise DocumentKeyUnavailableError(
                "this document was sealed with KMS but DOCUMENT_KMS_KEY_ID is not set"
            )
        try:
            key = wrapper.unwrap_data_key(wrapped, user_id=user_id, document_id=document_id)
        except WrappedKeyRejectedError as exc:
            raise DecryptionError(
                f"the wrapped key does not belong to this document: {exc}"
            ) from exc
        except KeyUnavailableError as exc:
            raise DocumentKeyUnavailableError(str(exc)) from exc
    else:
        key = document_key(settings)

    try:
        return AESGCM(key).decrypt(nonce, sealed, _associated_data(user_id, document_id))
    except InvalidTag as exc:
        raise DecryptionError(
            "stored document failed authentication under this key, owner and document id"
        ) from exc


def _split(stored: bytes) -> tuple[int, bytes, bytes, bytes]:
    """Envelope fields, tolerating the unframed layout earlier rows were written in."""
    if not stored.startswith(ENVELOPE_MAGIC):
        if len(stored) <= NONCE_BYTES:
            raise DecryptionError("stored document is too short to be a nonce and a ciphertext")
        return SCHEME_LOCAL, b"", stored[:NONCE_BYTES], stored[NONCE_BYTES:]

    if len(stored) < _HEADER_BYTES:
        raise DecryptionError("stored document is truncated inside its header")
    scheme = stored[len(ENVELOPE_MAGIC)]
    if scheme not in (SCHEME_LOCAL, SCHEME_KMS):
        raise DecryptionError(f"stored document declares an unknown scheme {scheme}")
    wrapped_length = int.from_bytes(stored[_HEADER_BYTES - 2 : _HEADER_BYTES], "big")
    if (scheme == SCHEME_LOCAL) != (wrapped_length == 0):
        # A local row carrying a wrapped key, or a KMS row carrying none, is a row rewritten by
        # somebody: refuse it rather than reason about which half to believe.
        raise DecryptionError("stored document's header disagrees with its wrapped key")
    body = stored[_HEADER_BYTES:]
    if len(body) <= wrapped_length + NONCE_BYTES:
        raise DecryptionError("stored document is truncated after its header")
    wrapped, rest = body[:wrapped_length], body[wrapped_length:]
    return scheme, wrapped, rest[:NONCE_BYTES], rest[NONCE_BYTES:]


__all__ = [
    "ENVELOPE_MAGIC",
    "SCHEME_KMS",
    "SCHEME_LOCAL",
    "DecryptionError",
    "DocumentKeyError",
    "DocumentKeyUnavailableError",
    "decrypt_document",
    "document_key",
    "encrypt_document",
]
