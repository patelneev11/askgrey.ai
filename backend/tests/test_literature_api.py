from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.api import deps
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
