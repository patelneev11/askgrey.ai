"""Envelope encryption of stored documents under a KMS key.

There is no AWS account here, so KMS is stood in for by `FakeKms` — an in-process double that
behaves like `kms:GenerateDataKey` and `kms:Decrypt` in the ways this app depends on: it mints
random data keys, seals them under a master key it never hands out, and refuses to unwrap one
whose encryption context does not match the wrap exactly. What the real service does beyond
that (durability, rotation, CloudTrail) is not something a test can assert.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any

import pytest
from botocore.exceptions import ClientError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core import kms
from app.core.config import Settings
from app.core.crypto import (
    ENVELOPE_MAGIC,
    SCHEME_KMS,
    DecryptionError,
    DocumentKeyUnavailableError,
    decrypt_document,
    encrypt_document,
)

PDF = b"%PDF-1.4 confidential compound series"
KEY_ID = "alias/askgrey-documents"


def kms_error(code: str) -> ClientError:
    """The real botocore exception, so the error-code handling under test is the real one."""
    return ClientError({"Error": {"Code": code, "Message": code}}, "Decrypt")


class FakeKms:
    """The two KMS calls the document store makes, backed by a local master key."""

    def __init__(self, master: bytes | None = None) -> None:
        self._master = master or os.urandom(32)
        self.decrypt_calls: list[dict[str, str]] = []

    def generate_data_key(
        self, *, KeyId: str, KeySpec: str, EncryptionContext: dict[str, str]
    ) -> dict[str, Any]:
        assert KeySpec == "AES_256"
        plaintext = os.urandom(32)
        nonce = os.urandom(12)
        # The context is authenticated, exactly as KMS authenticates it.
        sealed = AESGCM(self._master).encrypt(
            nonce, plaintext, json.dumps(EncryptionContext, sort_keys=True).encode()
        )
        return {"Plaintext": plaintext, "CiphertextBlob": KeyId.encode() + b"|" + nonce + sealed}

    def decrypt(
        self, *, CiphertextBlob: bytes, KeyId: str, EncryptionContext: dict[str, str]
    ) -> dict[str, Any]:
        self.decrypt_calls.append(EncryptionContext)
        prefix, _, body = CiphertextBlob.partition(b"|")
        if prefix.decode() != KeyId:
            raise kms_error("IncorrectKeyException")
        try:
            plaintext = AESGCM(self._master).decrypt(
                body[:12], body[12:], json.dumps(EncryptionContext, sort_keys=True).encode()
            )
        except Exception as exc:
            raise kms_error("InvalidCiphertextException") from exc
        return {"Plaintext": plaintext}


class UnreachableKms:
    """A KMS that is simply not answering: no code, no verdict on the ciphertext."""

    def generate_data_key(self, **_: Any) -> dict[str, Any]:
        raise ConnectionError("kms.us-east-1.amazonaws.com: connection timed out")

    def decrypt(self, **_: Any) -> dict[str, Any]:
        raise ConnectionError("kms.us-east-1.amazonaws.com: connection timed out")


@pytest.fixture
def fake_kms() -> FakeKms:
    return FakeKms()


def kms_settings(client: Any, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings whose KMS wrapper talks to `client` instead of AWS."""
    settings = Settings(document_kms_key_id=KEY_ID, jwt_secret="x" * 40)
    wrapper = kms.KmsKeyWrapper(KEY_ID, client=client)
    monkeypatch.setattr(kms, "wrapper_for", lambda _settings: wrapper)
    monkeypatch.setattr("app.core.crypto.wrapper_for", lambda _settings: wrapper)
    return settings


def local_settings() -> Settings:
    return Settings(
        document_encryption_key=base64.b64encode(os.urandom(32)).decode(), jwt_secret="x" * 40
    )


def test_a_kms_sealed_document_round_trips(
    fake_kms: FakeKms, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = kms_settings(fake_kms, monkeypatch)

    sealed = encrypt_document(PDF, user_id="u1", document_id="d1", settings=settings)

    assert decrypt_document(sealed, user_id="u1", document_id="d1", settings=settings) == PDF


def test_the_stored_value_holds_a_wrapped_key_and_not_the_document(
    fake_kms: FakeKms, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = kms_settings(fake_kms, monkeypatch)

    sealed = encrypt_document(PDF, user_id="u1", document_id="d1", settings=settings)

    assert sealed.startswith(ENVELOPE_MAGIC)
    assert sealed[len(ENVELOPE_MAGIC)] == SCHEME_KMS
    # What a database dump would contain: ciphertext plus a key only KMS can open.
    assert PDF not in sealed


def test_every_document_gets_its_own_data_key(
    fake_kms: FakeKms, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = kms_settings(fake_kms, monkeypatch)

    first = encrypt_document(PDF, user_id="u1", document_id="d1", settings=settings)
    second = encrypt_document(PDF, user_id="u1", document_id="d2", settings=settings)

    # A shared data key would make one compromised unwrap enough for the whole library.
    assert first != second


def test_the_owner_and_document_travel_as_the_encryption_context(
    fake_kms: FakeKms, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = kms_settings(fake_kms, monkeypatch)
    sealed = encrypt_document(PDF, user_id="u1", document_id="d1", settings=settings)

    decrypt_document(sealed, user_id="u1", document_id="d1", settings=settings)

    # This is what makes the unwrap itself account-scoped, and what a CloudTrail record shows.
    assert fake_kms.decrypt_calls == [{"app": "askgrey", "user_id": "u1", "document_id": "d1"}]


@pytest.mark.parametrize(
    ("user_id", "document_id"),
    [("intruder", "d1"), ("u1", "d2")],
)
def test_kms_refuses_to_unwrap_a_key_relabelled_onto_another_row(
    fake_kms: FakeKms, monkeypatch: pytest.MonkeyPatch, user_id: str, document_id: str
) -> None:
    settings = kms_settings(fake_kms, monkeypatch)
    sealed = encrypt_document(PDF, user_id="u1", document_id="d1", settings=settings)

    # Refused at the unwrap, before AES-GCM gets a say: the row is bound to its owner twice.
    with pytest.raises(DecryptionError):
        decrypt_document(sealed, user_id=user_id, document_id=document_id, settings=settings)


def test_a_wrapped_key_from_another_master_key_is_refused(
    fake_kms: FakeKms, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = kms_settings(fake_kms, monkeypatch)
    sealed = encrypt_document(PDF, user_id="u1", document_id="d1", settings=settings)

    # The same row, now read by a deployment whose KMS holds a different master key.
    other = kms_settings(FakeKms(), monkeypatch)

    with pytest.raises(DecryptionError):
        decrypt_document(sealed, user_id="u1", document_id="d1", settings=other)


def test_tampering_with_the_ciphertext_is_still_caught(
    fake_kms: FakeKms, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = kms_settings(fake_kms, monkeypatch)
    sealed = bytearray(encrypt_document(PDF, user_id="u1", document_id="d1", settings=settings))
    sealed[-1] ^= 0x01

    with pytest.raises(DecryptionError):
        decrypt_document(bytes(sealed), user_id="u1", document_id="d1", settings=settings)


def test_an_unreachable_kms_is_not_reported_as_a_bad_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The distinction the whole library depends on.

    A read that fails to decrypt deletes the row (see `app.services.literature`). If a KMS
    outage or a revoked credential looked like that, the first blip would delete every stored
    paper, so it must raise something else entirely.
    """
    working = FakeKms()
    settings = kms_settings(working, monkeypatch)
    sealed = encrypt_document(PDF, user_id="u1", document_id="d1", settings=settings)
    down = kms_settings(UnreachableKms(), monkeypatch)

    with pytest.raises(DocumentKeyUnavailableError):
        decrypt_document(sealed, user_id="u1", document_id="d1", settings=down)


@pytest.mark.parametrize("code", ["KMSInvalidStateException", "AccessDeniedException"])
def test_an_operational_kms_refusal_is_not_a_bad_document(
    monkeypatch: pytest.MonkeyPatch, code: str
) -> None:
    """A disabled key, a key pending deletion or a lost permission are all recoverable.

    Only `InvalidCiphertextException` and `IncorrectKeyException` say the ciphertext itself is
    wrong; treating the rest as corruption would delete data an operator could still recover.
    """
    working = FakeKms()
    settings = kms_settings(working, monkeypatch)
    sealed = encrypt_document(PDF, user_id="u1", document_id="d1", settings=settings)

    class Refusing:
        def decrypt(self, **_: Any) -> dict[str, Any]:
            raise kms_error(code)

    refusing = kms_settings(Refusing(), monkeypatch)

    with pytest.raises(DocumentKeyUnavailableError):
        decrypt_document(sealed, user_id="u1", document_id="d1", settings=refusing)


def test_an_upload_is_refused_rather_than_sealed_under_a_weaker_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = kms_settings(UnreachableKms(), monkeypatch)

    # Silently falling back to the local key would store a document the configured key
    # cannot open, and would quietly leave the KMS audit trail behind.
    with pytest.raises(DocumentKeyUnavailableError):
        encrypt_document(PDF, user_id="u1", document_id="d1", settings=settings)


def test_dropping_the_kms_key_id_does_not_condemn_rows_written_under_it(
    fake_kms: FakeKms, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = kms_settings(fake_kms, monkeypatch)
    sealed = encrypt_document(PDF, user_id="u1", document_id="d1", settings=settings)

    monkeypatch.setattr("app.core.crypto.wrapper_for", lambda _settings: None)

    # A configuration regression, recoverable by putting the key id back — so it must not
    # look like corruption, which would delete the rows on sight.
    with pytest.raises(DocumentKeyUnavailableError):
        decrypt_document(sealed, user_id="u1", document_id="d1", settings=local_settings())


def test_locally_sealed_documents_still_round_trip_with_kms_configured(
    fake_kms: FakeKms, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turning KMS on must not orphan what was stored before it.

    The scheme is recorded in the envelope, so a row written under the local key keeps being
    read under the local key even though new writes now go to KMS.
    """
    local = local_settings()
    sealed = encrypt_document(PDF, user_id="u1", document_id="d1", settings=local)

    migrating = Settings(
        document_kms_key_id=KEY_ID,
        document_encryption_key=local.document_encryption_key,
        jwt_secret="x" * 40,
    )
    wrapper = kms.KmsKeyWrapper(KEY_ID, client=fake_kms)
    monkeypatch.setattr("app.core.crypto.wrapper_for", lambda _settings: wrapper)

    assert decrypt_document(sealed, user_id="u1", document_id="d1", settings=migrating) == PDF


def test_the_kms_wrapper_is_only_built_when_a_key_is_configured() -> None:
    assert kms.wrapper_for(Settings(jwt_secret="x" * 40)) is None
    assert kms.wrapper_for(Settings(document_kms_key_id=KEY_ID, jwt_secret="x" * 40)) is not None
