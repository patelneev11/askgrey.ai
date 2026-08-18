"""The saved library: what a researcher explicitly keeps must come back exactly as produced.

The payloads here are taken from the real deterministic endpoints rather than hand-written, so a
model change that would make a stored artifact unreadable fails these tests too.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from tests.grants.test_budget_api import payload as budget_payload

OWNER = {"email": "keeper@askgrey.ai", "password": "obsidian-workspace-1"}
OTHER = {"email": "stranger@askgrey.ai", "password": "obsidian-workspace-2"}
ASPIRIN = "CC(=O)OC1=CC=CC=C1C(=O)O"


def auth_header(client: TestClient, credentials: dict[str, str]) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=credentials).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def budget(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post("/api/grants/budget", json=budget_payload(), headers=headers)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def admet(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post("/api/screening/admet", json={"smiles": ASPIRIN}, headers=headers)
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def descriptors(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post(
        "/api/screening/sar/descriptors", json={"smiles": ASPIRIN}, headers=headers
    )
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()
    return result


def save(
    client: TestClient,
    headers: dict[str, str],
    *,
    kind: str,
    payload: dict[str, Any],
    title: str = "Kept result",
    subtitle: str = "",
) -> dict[str, Any]:
    response = client.post(
        "/api/library",
        json={"kind": kind, "title": title, "subtitle": subtitle, "payload": payload},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_every_library_route_requires_authentication(client: TestClient) -> None:
    body = {"kind": "grants_budget", "title": "x", "payload": {}}
    assert client.post("/api/library", json=body).status_code == 401
    assert client.get("/api/library").status_code == 401
    assert client.get("/api/library/any-id").status_code == 401
    assert client.delete("/api/library/any-id").status_code == 401


def test_a_saved_budget_comes_back_byte_for_byte(client: TestClient) -> None:
    headers = auth_header(client, OWNER)
    produced = budget(client, headers)

    saved = save(client, headers, kind="grants_budget", payload=produced, title="SBIR phase I")
    reopened = client.get(f"/api/library/{saved['id']}", headers=headers)

    assert reopened.status_code == 200
    assert reopened.json()["payload"] == produced
    assert reopened.json()["title"] == "SBIR phase I"


def test_a_reopened_artifact_still_carries_its_own_caveats(client: TestClient) -> None:
    """The caveat travels with the payload, so it cannot be lost between save and reopen."""
    headers = auth_header(client, OWNER)
    produced = admet(client, headers)
    assert produced["caveat"] and produced["alert_caveat"]

    saved = save(client, headers, kind="screening_admet", payload=produced)

    reopened = client.get(f"/api/library/{saved['id']}", headers=headers).json()["payload"]
    assert reopened["caveat"] == produced["caveat"]
    assert reopened["alert_caveat"] == produced["alert_caveat"]


def test_saving_rejects_a_payload_that_is_not_that_kind_of_result(client: TestClient) -> None:
    headers = auth_header(client, OWNER)
    produced = admet(client, headers)

    response = client.post(
        "/api/library",
        json={"kind": "grants_budget", "title": "mislabelled", "payload": produced},
        headers=headers,
    )

    assert response.status_code == 422


def test_saving_rejects_an_unknown_kind(client: TestClient) -> None:
    headers = auth_header(client, OWNER)

    response = client.post(
        "/api/library",
        json={"kind": "made_up_kind", "title": "x", "payload": {}},
        headers=headers,
    )

    assert response.status_code == 422


def test_the_list_is_newest_first_and_can_be_narrowed_to_one_kind(client: TestClient) -> None:
    headers = auth_header(client, OWNER)
    first = save(client, headers, kind="grants_budget", payload=budget(client, headers))
    second = save(
        client,
        headers,
        kind="screening_descriptors",
        payload=descriptors(client, headers),
        title="Aspirin descriptors",
    )

    listed = client.get("/api/library", headers=headers)
    narrowed = client.get("/api/library", params={"kind": "grants_budget"}, headers=headers)

    assert listed.status_code == 200
    assert [entry["id"] for entry in listed.json()] == [second["id"], first["id"]]
    # A summary is enough to reopen an item and never ships the payload.
    assert "payload" not in listed.json()[0]
    assert [entry["id"] for entry in narrowed.json()] == [first["id"]]


def test_another_account_can_neither_see_nor_read_nor_delete_an_artifact(
    client: TestClient,
) -> None:
    headers = auth_header(client, OWNER)
    saved = save(client, headers, kind="grants_budget", payload=budget(client, headers))
    intruder = auth_header(client, OTHER)

    assert client.get("/api/library", headers=intruder).json() == []
    # Missing rather than forbidden: a 403 would confirm the id exists.
    assert client.get(f"/api/library/{saved['id']}", headers=intruder).status_code == 404
    assert client.delete(f"/api/library/{saved['id']}", headers=intruder).status_code == 404
    assert client.get(f"/api/library/{saved['id']}", headers=headers).status_code == 200


def test_deleting_removes_it_from_the_list(client: TestClient) -> None:
    headers = auth_header(client, OWNER)
    saved = save(client, headers, kind="grants_budget", payload=budget(client, headers))

    assert client.delete(f"/api/library/{saved['id']}", headers=headers).status_code == 204

    assert client.get("/api/library", headers=headers).json() == []
    assert client.get(f"/api/library/{saved['id']}", headers=headers).status_code == 404


def test_nothing_is_saved_unless_the_caller_asks(client: TestClient) -> None:
    """Producing a result must not persist it: saving is the researcher's decision."""
    headers = auth_header(client, OWNER)

    budget(client, headers)
    descriptors(client, headers)

    assert client.get("/api/library", headers=headers).json() == []
