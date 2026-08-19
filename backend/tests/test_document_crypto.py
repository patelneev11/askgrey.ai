from __future__ import annotations

import base64
import os

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings
from app.core.crypto import (
    ENVELOPE_MAGIC,
    DecryptionError,
    DocumentKeyError,
    decrypt_document,
    document_key,
    encrypt_document,
)

PDF = b"%PDF-1.4 confidential compound series"


def settings(key: str = "") -> Settings:
    return Settings(document_encryption_key=key, jwt_secret="x" * 40)


def a_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


def test_a_round_trip_returns_the_original_bytes() -> None:
    configured = settings(a_key())

    sealed = encrypt_document(PDF, user_id="u1", document_id="d1", settings=configured)
    assert decrypt_document(sealed, user_id="u1", document_id="d1", settings=configured) == PDF


def test_the_stored_bytes_are_not_the_document() -> None:
    sealed = encrypt_document(PDF, user_id="u1", document_id="d1", settings=settings(a_key()))

    # What a database dump, a backup or a leaked replica would contain.
    assert PDF not in sealed
    assert not sealed.startswith(b"%PDF")


def test_the_same_document_seals_differently_every_time() -> None:
    configured = settings(a_key())

    first = encrypt_document(PDF, user_id="u1", document_id="d1", settings=configured)
    second = encrypt_document(PDF, user_id="u1", document_id="d1", settings=configured)

    # A deterministic ciphertext would let an observer of the column tell who holds which paper.
    assert first != second


def test_another_account_cannot_read_the_ciphertext() -> None:
    configured = settings(a_key())
    sealed = encrypt_document(PDF, user_id="owner", document_id="d1", settings=configured)

    with pytest.raises(DecryptionError):
        decrypt_document(sealed, user_id="intruder", document_id="d1", settings=configured)


def test_ciphertext_is_bound_to_its_document_id() -> None:
    configured = settings(a_key())
    sealed = encrypt_document(PDF, user_id="u1", document_id="d1", settings=configured)

    with pytest.raises(DecryptionError):
        decrypt_document(sealed, user_id="u1", document_id="d2", settings=configured)


def test_tampered_ciphertext_is_refused_rather_than_returned() -> None:
    configured = settings(a_key())
    sealed = bytearray(encrypt_document(PDF, user_id="u1", document_id="d1", settings=configured))
    sealed[-1] ^= 0x01

    with pytest.raises(DecryptionError):
        decrypt_document(bytes(sealed), user_id="u1", document_id="d1", settings=configured)


def test_truncated_ciphertext_is_refused() -> None:
    configured = settings(a_key())

    with pytest.raises(DecryptionError):
        decrypt_document(b"short", user_id="u1", document_id="d1", settings=configured)


def test_a_different_key_cannot_read_it() -> None:
    sealed = encrypt_document(PDF, user_id="u1", document_id="d1", settings=settings(a_key()))

    with pytest.raises(DecryptionError):
        decrypt_document(sealed, user_id="u1", document_id="d1", settings=settings(a_key()))


def test_the_key_is_derived_from_the_jwt_secret_when_none_is_configured() -> None:
    derived = document_key(settings())

    assert len(derived) == 32
    assert derived == document_key(settings())


def test_a_configured_key_must_decode_to_32_bytes() -> None:
    with pytest.raises(DocumentKeyError):
        document_key(settings(base64.b64encode(os.urandom(16)).decode()))


def test_a_configured_key_must_be_base64() -> None:
    with pytest.raises(DocumentKeyError):
        document_key(settings("not-base64-at-all-!!"))


def test_rows_written_before_the_envelope_existed_still_decrypt() -> None:
    """The first version of this store wrote a bare nonce followed by the ciphertext.

    Those rows predate the header that now says which key sealed them, so they are read as what
    they are: locally sealed. Without this they would fail to authenticate and be deleted.
    """
    configured = settings(a_key())
    nonce = os.urandom(12)
    unframed = nonce + AESGCM(document_key(configured)).encrypt(nonce, PDF, b"u1:d1")

    assert decrypt_document(unframed, user_id="u1", document_id="d1", settings=configured) == PDF


def test_an_envelope_declaring_an_unknown_scheme_is_refused() -> None:
    # A row written by a future version this build cannot read; guessing at it would be worse.
    configured = settings(a_key())
    forged = ENVELOPE_MAGIC + bytes([99]) + (0).to_bytes(2, "big") + os.urandom(40)

    with pytest.raises(DecryptionError):
        decrypt_document(forged, user_id="u1", document_id="d1", settings=configured)


def test_an_envelope_truncated_inside_its_header_is_refused() -> None:
    configured = settings(a_key())

    with pytest.raises(DecryptionError):
        decrypt_document(
            ENVELOPE_MAGIC + b"\x01", user_id="u1", document_id="d1", settings=configured
        )
