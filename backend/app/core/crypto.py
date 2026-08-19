"""Encryption of the document bytes this app stores, applied before they reach the database.

AES-256-GCM with a fresh random nonce per blob. The owning user id and the document id are
bound in as additional authenticated data, so a row moved to another account — or relabelled
with another document id — fails to decrypt instead of decrypting into the wrong library.

What this protects against: a database dump, a managed provider's backup, a stray read replica
or a stolen disk. What it does not protect against: a compromise of the running process, which
holds the key. Column-level encryption is not a substitute for the database's own encryption
at rest; it means the two have to be broken separately.

The key comes from `DOCUMENT_ENCRYPTION_KEY` when it is set. When it is not, it is derived from
`JWT_SECRET` so a fresh clone runs with nothing to configure — see `document_key`.
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

KEY_BYTES = 32
NONCE_BYTES = 12
# Versioned so a future scheme can be told apart from this one without guessing.
DERIVATION_INFO = b"askgrey.document-encryption.v1"


class DocumentKeyError(Exception):
    """The configured key is unusable, so nothing should be stored under it."""


class DecryptionError(Exception):
    """The stored bytes did not authenticate under this key, owner and document id."""


def document_key(settings: Settings | None = None) -> bytes:
    """The 32-byte key stored documents are encrypted under.

    An explicit `DOCUMENT_ENCRYPTION_KEY` (base64, 32 bytes decoded) is used as given. With
    none set the key is derived from `JWT_SECRET` via HKDF: it keeps a clone runnable, and it
    is a real key rather than a constant, but it ties the two secrets together — rotating
    `JWT_SECRET` makes already-stored papers unreadable. That is survivable for this store,
    because every row is a copy of a paper the user can add again, and unreadable rows are
    deleted rather than served (see `app.services.literature`). A deployment that would rather
    not lose them on a JWT rotation should set the key explicitly.
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


def encrypt_document(
    plaintext: bytes, *, user_id: str, document_id: str, settings: Settings | None = None
) -> bytes:
    """Nonce followed by ciphertext, as the single value to store in one column."""
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(document_key(settings)).encrypt(
        nonce, plaintext, _associated_data(user_id, document_id)
    )
    return nonce + sealed


def decrypt_document(
    stored: bytes, *, user_id: str, document_id: str, settings: Settings | None = None
) -> bytes:
    if len(stored) <= NONCE_BYTES:
        raise DecryptionError("stored document is too short to be a nonce and a ciphertext")
    nonce, sealed = stored[:NONCE_BYTES], stored[NONCE_BYTES:]
    try:
        return AESGCM(document_key(settings)).decrypt(
            nonce, sealed, _associated_data(user_id, document_id)
        )
    except InvalidTag as exc:
        raise DecryptionError(
            "stored document failed authentication under this key, owner and document id"
        ) from exc


__all__ = [
    "DecryptionError",
    "DocumentKeyError",
    "decrypt_document",
    "document_key",
    "encrypt_document",
]
