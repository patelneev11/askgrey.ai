from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import deps
from app.core.crypto import DocumentKeyUnavailableError
from app.models.user import User
from app.services import literature
from app.services.literature import MAX_TABLE_JSON_BYTES

CREDENTIALS = {"email": "librarian@askgrey.ai", "password": "obsidian-workspace-1"}
OTHER = {"email": "stranger@askgrey.ai", "password": "obsidian-workspace-2"}
DOCUMENT_ID = "a" * 64


def auth_header(client: TestClient, credentials: dict[str, str]) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=credentials).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def table(value: str = "73 patients") -> dict[str, Any]:
    return {
        "goal": "sample size",
        "columns": [{"key": "sample_size", "label": "sample size", "description": ""}],
        "rows": [
            {
                "document_id": DOCUMENT_ID,
                "title": "A trial",
                "source_url": "",
                "filename": "trial.pdf",
                "page_count": 8,
                "status": "extracted",
                "cells": {
                    "sample_size": {"value": value, "citation": None, "status": "ungrounded"}
                },
                "warnings": [],
            }
        ],
    }


def workspace_payload() -> dict[str, Any]:
    return {
        "goal": "sample size",
        "sources": [
            {
                "id": "trial.pdf:1",
                "label": "trial.pdf",
                "kind": "upload",
                "document_id": DOCUMENT_ID,
            }
        ],
        "table": table(),
    }


def test_workspace_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/literature/workspace").status_code == 401
    assert client.put("/api/literature/workspace", json=workspace_payload()).status_code == 401


def test_a_new_user_starts_with_an_empty_workspace(client: TestClient) -> None:
    response = client.get("/api/literature/workspace", headers=auth_header(client, CREDENTIALS))

    assert response.status_code == 200
    assert response.json() == {
        "goal": "",
        "sources": [],
        "table": None,
        "updated_at": None,
        "stored_document_ids": [],
    }


def test_a_saved_workspace_is_read_back(client: TestClient) -> None:
    headers = auth_header(client, CREDENTIALS)

    saved = client.put("/api/literature/workspace", json=workspace_payload(), headers=headers)
    assert saved.status_code == 200

    body = client.get("/api/literature/workspace", headers=headers).json()
    assert body["goal"] == "sample size"
    assert body["sources"][0]["document_id"] == DOCUMENT_ID
    assert body["table"]["rows"][0]["cells"]["sample_size"]["value"] == "73 patients"
    assert body["updated_at"] is not None


def test_saving_twice_replaces_the_previous_state(client: TestClient) -> None:
    headers = auth_header(client, CREDENTIALS)
    client.put("/api/literature/workspace", json=workspace_payload(), headers=headers)

    client.put(
        "/api/literature/workspace",
        json={"goal": "dosing", "sources": [], "table": table("40 mg")},
        headers=headers,
    )

    body = client.get("/api/literature/workspace", headers=headers).json()
    assert body["goal"] == "dosing"
    assert body["sources"] == []
    assert body["table"]["rows"][0]["cells"]["sample_size"]["value"] == "40 mg"


def test_one_users_workspace_is_invisible_to_another(client: TestClient) -> None:
    owner = auth_header(client, CREDENTIALS)
    client.put("/api/literature/workspace", json=workspace_payload(), headers=owner)

    body = client.get("/api/literature/workspace", headers=auth_header(client, OTHER)).json()

    assert body["goal"] == ""
    assert body["table"] is None


def test_clearing_the_workspace_empties_it(client: TestClient) -> None:
    headers = auth_header(client, CREDENTIALS)
    client.put("/api/literature/workspace", json=workspace_payload(), headers=headers)

    assert client.delete("/api/literature/workspace", headers=headers).status_code == 204

    assert client.get("/api/literature/workspace", headers=headers).json()["table"] is None


def test_an_oversized_table_is_rejected_rather_than_stored(client: TestClient) -> None:
    headers = auth_header(client, CREDENTIALS)
    huge = table("x" * (MAX_TABLE_JSON_BYTES + 1))

    response = client.put(
        "/api/literature/workspace",
        json={"goal": "sample size", "sources": [], "table": huge},
        headers=headers,
    )

    assert response.status_code == 413
    assert client.get("/api/literature/workspace", headers=headers).json()["table"] is None


def test_too_many_sources_are_rejected(client: TestClient) -> None:
    headers = auth_header(client, CREDENTIALS)
    sources = [
        {"id": f"s{index}", "label": f"s{index}", "kind": "url", "url": "https://example.org/x.pdf"}
        for index in range(51)
    ]

    response = client.put(
        "/api/literature/workspace",
        json={"goal": "sample size", "sources": sources, "table": None},
        headers=headers,
    )

    assert response.status_code == 422


def test_an_unknown_document_is_404_not_a_fetch(client: TestClient) -> None:
    headers = auth_header(client, CREDENTIALS)

    response = client.get(f"/api/literature/documents/{DOCUMENT_ID}/pdf", headers=headers)

    assert response.status_code == 404


def test_a_document_id_that_is_not_a_digest_is_rejected(client: TestClient) -> None:
    headers = auth_header(client, CREDENTIALS)

    response = client.get(
        "/api/literature/documents/https:%2F%2F169.254.169.254%2Flatest/pdf", headers=headers
    )

    assert response.status_code in {404, 422}


def test_the_workspace_endpoints_are_rate_limited(client: TestClient) -> None:
    headers = auth_header(client, CREDENTIALS)
    deps.api_limiter.limit = 3
    try:
        statuses = [
            client.get("/api/literature/workspace", headers=headers).status_code for _ in range(5)
        ]
    finally:
        deps.api_limiter.limit = deps._settings.api_rate_limit_per_minute

    assert statuses.count(429) >= 1


def store(db: Session, email: str, content: bytes = b"%PDF-1.4 body") -> str:
    """Put a paper in a registered account's library, as an extraction run would."""
    user_id = db.execute(select(User.id).where(User.email == email)).scalar_one()
    literature.store_document(db, str(user_id), document_id=DOCUMENT_ID, content=content)
    return str(user_id)


def test_the_owner_gets_their_paper_back(client: TestClient, db: Session) -> None:
    headers = auth_header(client, CREDENTIALS)
    store(db, CREDENTIALS["email"], b"%PDF-1.4 owner copy")

    response = client.get(f"/api/literature/documents/{DOCUMENT_ID}/pdf", headers=headers)

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 owner copy"


def test_another_account_cannot_read_a_paper_by_its_id(client: TestClient, db: Session) -> None:
    auth_header(client, CREDENTIALS)
    stranger = auth_header(client, OTHER)
    store(db, CREDENTIALS["email"])

    guessed = client.get(f"/api/literature/documents/{DOCUMENT_ID}/pdf", headers=stranger)

    # Indistinguishable from a paper nobody has stored, so the 404 does not confirm it exists.
    assert guessed.status_code == 404
    unknown = client.get(f"/api/literature/documents/{'b' * 64}/pdf", headers=stranger)
    assert unknown.status_code == 404
    assert guessed.json() == unknown.json()


def test_deleting_a_paper_removes_it(client: TestClient, db: Session) -> None:
    headers = auth_header(client, CREDENTIALS)
    store(db, CREDENTIALS["email"])

    assert (
        client.delete(f"/api/literature/documents/{DOCUMENT_ID}", headers=headers).status_code
        == 204
    )

    assert (
        client.get(f"/api/literature/documents/{DOCUMENT_ID}/pdf", headers=headers).status_code
        == 404
    )
    assert (
        client.get("/api/literature/workspace", headers=headers).json()["stored_document_ids"] == []
    )


def test_another_account_cannot_delete_a_paper(client: TestClient, db: Session) -> None:
    owner = auth_header(client, CREDENTIALS)
    stranger = auth_header(client, OTHER)
    store(db, CREDENTIALS["email"])

    response = client.delete(f"/api/literature/documents/{DOCUMENT_ID}", headers=stranger)

    assert response.status_code == 404
    assert (
        client.get(f"/api/literature/documents/{DOCUMENT_ID}/pdf", headers=owner).status_code == 200
    )


def test_clearing_the_workspace_deletes_the_stored_papers(client: TestClient, db: Session) -> None:
    headers = auth_header(client, CREDENTIALS)
    client.put("/api/literature/workspace", json=workspace_payload(), headers=headers)
    store(db, CREDENTIALS["email"])

    assert client.delete("/api/literature/workspace", headers=headers).status_code == 204

    assert (
        client.get(f"/api/literature/documents/{DOCUMENT_ID}/pdf", headers=headers).status_code
        == 404
    )


def test_reading_and_deleting_a_paper_are_on_the_audit_feed(
    client: TestClient, db: Session
) -> None:
    headers = auth_header(client, CREDENTIALS)
    store(db, CREDENTIALS["email"])

    client.get(f"/api/literature/documents/{DOCUMENT_ID}/pdf", headers=headers)
    client.delete(f"/api/literature/documents/{DOCUMENT_ID}", headers=headers)

    listed = client.get("/api/audit/events", headers=headers).json()["events"]
    names = [event["event"] for event in listed]
    assert "literature.document_deleted" in names
    assert "literature.document_read" in names
    # Provenance only: the audit feed never carries the paper.
    assert "%PDF" not in str(listed)


def test_a_key_service_outage_is_a_503_and_the_paper_survives_it(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """503, not 404 and not 500: the paper is fine, the key service is not.

    A 404 would tell the user their upload is gone (and the delete-on-unreadable path would make
    that true); a 500 reads as a bug in this app. 503 is the one that says retry.
    """
    headers = auth_header(client, CREDENTIALS)
    store(db, CREDENTIALS["email"])

    def unavailable(*_args: object, **_kwargs: object) -> bytes:
        raise DocumentKeyUnavailableError("kms is not answering")

    monkeypatch.setattr(literature, "decrypt_document", unavailable)

    response = client.get(f"/api/literature/documents/{DOCUMENT_ID}/pdf", headers=headers)

    assert response.status_code == 503
    # No key detail, key id or ARN reaches the caller.
    assert response.json() == {
        "detail": "stored documents are temporarily unavailable; retry shortly"
    }
    monkeypatch.undo()
    recovered = client.get(f"/api/literature/documents/{DOCUMENT_ID}/pdf", headers=headers)
    assert recovered.status_code == 200
