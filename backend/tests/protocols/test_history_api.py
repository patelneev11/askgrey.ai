from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.protocols.test_checklist import fixture_protocol

OWNER = {"email": "owner@askgrey.ai", "password": "obsidian-workspace-1"}
OTHER = {"email": "other@askgrey.ai", "password": "obsidian-workspace-2"}


def auth_header(client: TestClient, credentials: dict[str, str]) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=credentials).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def save(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    body = {"protocol": fixture_protocol().model_dump(mode="json")}
    response = client.post("/api/protocols", json=body, headers=headers)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_every_protocol_route_requires_authentication(client: TestClient) -> None:
    body = {"protocol": fixture_protocol().model_dump(mode="json")}
    assert client.post("/api/protocols", json=body).status_code == 401
    assert client.get("/api/protocols").status_code == 401
    assert client.get("/api/protocols/any-id").status_code == 401
    assert client.get("/api/protocols/any-id/history").status_code == 401
    assert client.put("/api/protocols/any-id", json=body).status_code == 401
    assert (
        client.post("/api/protocols/export/eln", json={**body, "folder_id": "lib_1"}).status_code
        == 401
    )


def test_saving_then_editing_records_a_second_version_with_a_changelog(client: TestClient) -> None:
    headers = auth_header(client, OWNER)
    saved = save(client, headers)
    assert saved["version"] == 1
    assert saved["protocol"]["origin"] == "agent_drafted"

    protocol = saved["protocol"]
    protocol["steps"][0]["instruction"] = "Wash wells three times with ice-cold PBS."
    updated = client.put(
        f"/api/protocols/{saved['id']}",
        json={"protocol": protocol, "change_summary": "tightened the wash"},
        headers=headers,
    )

    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    # An edited protocol is researcher-edited, and still carries the review disclaimer.
    assert updated.json()["protocol"]["origin"] == "researcher_edited"
    assert updated.json()["protocol"]["disclaimer"].startswith("Agent-drafted content.")

    history = client.get(f"/api/protocols/{saved['id']}/history", headers=headers).json()
    assert history["current_version"] == 2
    assert [entry["version"] for entry in history["versions"]] == [2, 1]
    latest = history["versions"][0]
    assert latest["change_summary"] == "tightened the wash"
    assert latest["changes"][0]["field"] == "steps.step-1.instruction"
    assert "three times" in latest["changes"][0]["after"]


def test_an_earlier_version_is_still_readable_after_an_edit(client: TestClient) -> None:
    headers = auth_header(client, OWNER)
    saved = save(client, headers)
    protocol = saved["protocol"]
    protocol["title"] = "Renamed protocol"
    client.put(f"/api/protocols/{saved['id']}", json={"protocol": protocol}, headers=headers)

    first = client.get(f"/api/protocols/{saved['id']}/versions/1", headers=headers)
    current = client.get(f"/api/protocols/{saved['id']}", headers=headers)

    assert first.json()["protocol"]["title"] == fixture_protocol().title
    assert current.json()["protocol"]["title"] == "Renamed protocol"
    assert current.json()["version"] == 2


def test_a_save_that_changes_nothing_does_not_create_a_version(client: TestClient) -> None:
    headers = auth_header(client, OWNER)
    saved = save(client, headers)

    again = client.put(
        f"/api/protocols/{saved['id']}", json={"protocol": saved["protocol"]}, headers=headers
    )

    assert again.json()["version"] == 1
    history = client.get(f"/api/protocols/{saved['id']}/history", headers=headers).json()
    assert len(history["versions"]) == 1


def test_another_account_cannot_read_or_edit_the_protocol(client: TestClient) -> None:
    saved = save(client, auth_header(client, OWNER))
    intruder = auth_header(client, OTHER)

    assert client.get(f"/api/protocols/{saved['id']}", headers=intruder).status_code == 404
    assert client.get(f"/api/protocols/{saved['id']}/history", headers=intruder).status_code == 404
    assert (
        client.put(
            f"/api/protocols/{saved['id']}",
            json={"protocol": saved["protocol"]},
            headers=intruder,
        ).status_code
        == 404
    )


def test_saved_protocols_are_listed_newest_edit_first(client: TestClient) -> None:
    """The list is what makes a save reachable again after a reload."""
    headers = auth_header(client, OWNER)
    first = save(client, headers)
    second = save(client, headers)
    protocol = first["protocol"]
    protocol["title"] = "Edited most recently"
    client.put(f"/api/protocols/{first['id']}", json={"protocol": protocol}, headers=headers)

    listed = client.get("/api/protocols", headers=headers)

    assert listed.status_code == 200
    body = listed.json()
    assert [entry["id"] for entry in body] == [first["id"], second["id"]]
    assert body[0]["title"] == "Edited most recently"
    assert body[0]["current_version"] == 2
    assert body[0]["goal"] == fixture_protocol().goal


def test_the_list_shows_only_the_callers_own_protocols(client: TestClient) -> None:
    save(client, auth_header(client, OWNER))
    intruder = auth_header(client, OTHER)

    assert client.get("/api/protocols", headers=intruder).json() == []


def test_eln_export_returns_an_untested_benchling_payload(client: TestClient) -> None:
    headers = auth_header(client, OWNER)

    response = client.post(
        "/api/protocols/export/eln",
        json={
            "protocol": fixture_protocol().model_dump(mode="json"),
            "folder_id": "lib_A1b2C3",
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["integration_status"] == "schema_ready_untested"
    assert body["entry"]["folderId"] == "lib_A1b2C3"
    assert body["notes"][0]["text"].startswith("Agent-drafted content.")


def test_an_invalid_folder_id_is_a_422(client: TestClient) -> None:
    headers = auth_header(client, OWNER)

    response = client.post(
        "/api/protocols/export/eln",
        json={
            "protocol": fixture_protocol().model_dump(mode="json"),
            "folder_id": "lib/../secrets",
        },
        headers=headers,
    )

    assert response.status_code == 422
