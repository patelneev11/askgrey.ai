"""Shared workspaces: who may see, save and administer work, and what a seat is worth.

The tests go through HTTP, because the point of the feature is what one account can reach in
another account's name. Where a test needs a state the API cannot produce — an expired invitation,
a stale active workspace — it arranges it on the same session the app is using.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.workspace import WorkspaceInvite
from app.services.workspaces import _now
from tests.protocols.test_checklist import fixture_protocol
from tests.test_library_api import budget

OWNER = {"email": "lead@askgrey.ai", "password": "obsidian-workspace-1"}
COLLEAGUE = {"email": "bench@askgrey.ai", "password": "obsidian-workspace-2"}
OUTSIDER = {"email": "nobody@askgrey.ai", "password": "obsidian-workspace-3"}


def register(client: TestClient, credentials: dict[str, str]) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=credentials).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def make_workspace(
    client: TestClient, headers: dict[str, str], *, name: str = "Tox screen", seats: int = 5
) -> dict[str, Any]:
    response = client.post(
        "/api/workspaces", json={"name": name, "seat_limit": seats}, headers=headers
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def invite(
    client: TestClient,
    headers: dict[str, str],
    workspace_id: str,
    *,
    email: str,
    role: str = "member",
) -> dict[str, Any]:
    response = client.post(
        f"/api/workspaces/{workspace_id}/invites",
        json={"email": email, "role": role},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def accept(client: TestClient, headers: dict[str, str], token: str) -> Any:
    return client.post("/api/workspaces/invites/accept", json={"token": token}, headers=headers)


def join(
    client: TestClient,
    owner_headers: dict[str, str],
    workspace_id: str,
    credentials: dict[str, str],
    *,
    role: str = "member",
) -> dict[str, str]:
    """Register an account and walk it through a real invitation into the workspace."""
    created = invite(client, owner_headers, workspace_id, email=credentials["email"], role=role)
    headers = register(client, credentials)
    response = accept(client, headers, created["token"])
    assert response.status_code == 200, response.text
    return headers


def save_budget(client: TestClient, headers: dict[str, str], *, title: str = "SBIR phase I") -> Any:
    return client.post(
        "/api/library",
        json={
            "kind": "grants_budget",
            "title": title,
            "subtitle": "",
            "payload": budget(client, headers),
        },
        headers=headers,
    )


def save_protocol(client: TestClient, headers: dict[str, str]) -> Any:
    return client.post(
        "/api/protocols",
        json={"protocol": fixture_protocol().model_dump(mode="json")},
        headers=headers,
    )


def library_ids(client: TestClient, headers: dict[str, str]) -> set[str]:
    response = client.get("/api/library", headers=headers)
    assert response.status_code == 200, response.text
    return {item["id"] for item in response.json()}


def test_every_workspace_route_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/workspaces").status_code == 401
    assert client.post("/api/workspaces", json={"name": "x"}).status_code == 401
    assert client.put("/api/workspaces/active", json={"workspace_id": None}).status_code == 401
    assert client.get("/api/workspaces/any-id").status_code == 401
    assert client.patch("/api/workspaces/any-id", json={"name": "x"}).status_code == 401
    assert client.delete("/api/workspaces/any-id").status_code == 401
    assert (
        client.post("/api/workspaces/any-id/invites", json={"email": "a@b.co"}).status_code == 401
    )
    assert client.delete("/api/workspaces/any-id/invites/any").status_code == 401
    assert (
        client.post("/api/workspaces/invites/accept", json={"token": "x" * 12}).status_code == 401
    )
    assert client.put("/api/workspaces/any/members/any", json={"role": "member"}).status_code == 401
    assert client.delete("/api/workspaces/any/members/any").status_code == 401
    assert client.post("/api/workspaces/any/owner/any").status_code == 401


def test_an_account_starts_with_no_workspaces_and_works_privately(client: TestClient) -> None:
    headers = register(client, OWNER)

    memberships = client.get("/api/workspaces", headers=headers).json()

    assert memberships == {"workspaces": [], "active_workspace_id": None}


def test_creating_a_workspace_makes_its_creator_the_owner_and_switches_into_it(
    client: TestClient,
) -> None:
    headers = register(client, OWNER)

    created = make_workspace(client, headers, name="Tox screen", seats=3)

    assert created["role"] == "owner"
    assert (created["seat_limit"], created["seats_used"], created["member_count"]) == (3, 1, 1)
    memberships = client.get("/api/workspaces", headers=headers).json()
    assert memberships["active_workspace_id"] == created["id"]
    assert [space["id"] for space in memberships["workspaces"]] == [created["id"]]


def test_a_workspace_is_invisible_to_an_account_that_was_never_invited(
    client: TestClient,
) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    outsider = register(client, OUTSIDER)

    assert client.get(f"/api/workspaces/{created['id']}", headers=outsider).status_code == 404
    assert client.get("/api/workspaces", headers=outsider).json()["workspaces"] == []
    # Naming a workspace does not join it: switching is refused as if it did not exist.
    switch = client.put(
        "/api/workspaces/active", json={"workspace_id": created["id"]}, headers=outsider
    )
    assert switch.status_code == 404


def test_work_saved_before_a_workspace_existed_stays_private(client: TestClient) -> None:
    owner = register(client, OWNER)
    private = save_budget(client, owner, title="Kept alone").json()
    created = make_workspace(client, owner)
    colleague = join(client, owner, created["id"], COLLEAGUE)

    assert private["workspace_id"] is None
    assert private["id"] in library_ids(client, owner)
    assert private["id"] not in library_ids(client, colleague)


def test_work_saved_inside_a_workspace_is_visible_to_its_members(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    colleague = join(client, owner, created["id"], COLLEAGUE)

    shared = save_budget(client, owner, title="Shared budget").json()

    assert shared["workspace_id"] == created["id"]
    assert shared["saved_by_user_id"] != ""
    assert shared["id"] in library_ids(client, colleague)
    reopened = client.get(f"/api/library/{shared['id']}", headers=colleague)
    assert reopened.status_code == 200
    assert reopened.json()["payload"] == shared["payload"]


def test_leaving_a_workspace_hides_its_shared_work_again(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    colleague = join(client, owner, created["id"], COLLEAGUE)
    shared = save_budget(client, owner, title="Shared budget").json()
    assert shared["id"] in library_ids(client, colleague)

    switched = client.put("/api/workspaces/active", json={"workspace_id": None}, headers=owner)

    assert switched.json()["active_workspace_id"] is None
    assert shared["id"] not in library_ids(client, owner)
    assert client.get(f"/api/library/{shared['id']}", headers=owner).status_code == 404


def test_a_viewer_may_read_shared_work_but_not_save_into_the_workspace(
    client: TestClient,
) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    viewer = join(client, owner, created["id"], COLLEAGUE, role="viewer")
    shared = save_budget(client, owner, title="Shared budget").json()

    assert shared["id"] in library_ids(client, viewer)
    refused = save_budget(client, viewer, title="Not allowed")
    assert refused.status_code == 403
    assert save_protocol(client, viewer).status_code == 403


def test_a_member_cannot_delete_a_colleagues_shared_work_but_an_admin_can(
    client: TestClient,
) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    member = join(client, owner, created["id"], COLLEAGUE)
    shared = save_budget(client, owner, title="Shared budget").json()

    assert client.delete(f"/api/library/{shared['id']}", headers=member).status_code == 403

    promote = client.put(
        f"/api/workspaces/{created['id']}/members/{shared['saved_by_user_id']}",
        json={"role": "admin"},
        headers=owner,
    )
    assert promote.status_code == 404  # the owner's own role cannot be changed
    theirs = save_budget(client, member, title="Their own").json()
    assert client.delete(f"/api/library/{theirs['id']}", headers=member).status_code == 204
    assert client.delete(f"/api/library/{shared['id']}", headers=owner).status_code == 204


def test_a_shared_protocol_takes_new_versions_from_any_member(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    member = join(client, owner, created["id"], COLLEAGUE)
    saved = save_protocol(client, owner).json()
    assert saved["workspace_id"] == created["id"]

    edited = fixture_protocol().model_dump(mode="json")
    edited["title"] = "Revised by a colleague"
    response = client.put(
        f"/api/protocols/{saved['id']}",
        json={"protocol": edited, "change_summary": "colleague edit"},
        headers=member,
    )

    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    history = client.get(f"/api/protocols/{saved['id']}/history", headers=owner).json()
    authors = {entry["author_user_id"] for entry in history["versions"]}
    assert len(authors) == 2  # each version keeps the account that wrote it
    first = client.get(f"/api/protocols/{saved['id']}/versions/1", headers=member).json()
    assert first["protocol"]["title"] == saved["protocol"]["title"]


def test_a_viewer_may_read_a_shared_protocol_but_not_revise_it(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    viewer = join(client, owner, created["id"], COLLEAGUE, role="viewer")
    saved = save_protocol(client, owner).json()

    assert client.get(f"/api/protocols/{saved['id']}", headers=viewer).status_code == 200
    refused = client.put(
        f"/api/protocols/{saved['id']}",
        json={"protocol": saved["protocol"]},
        headers=viewer,
    )
    assert refused.status_code == 403


def test_an_invitation_token_is_returned_once_and_never_again(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)

    issued = invite(client, owner, created["id"], email=COLLEAGUE["email"])

    assert issued["token"]
    detail = client.get(f"/api/workspaces/{created['id']}", headers=owner).json()
    assert [pending["email"] for pending in detail["invites"]] == [COLLEAGUE["email"]]
    assert "token" not in detail["invites"][0]
    assert issued["token"] not in client.get(f"/api/workspaces/{created['id']}", headers=owner).text


def test_an_invitation_is_bound_to_the_address_it_was_sent_to(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    issued = invite(client, owner, created["id"], email=COLLEAGUE["email"])
    outsider = register(client, OUTSIDER)

    response = accept(client, outsider, issued["token"])

    assert response.status_code == 400
    assert "different address" in response.json()["detail"]
    assert client.get("/api/workspaces", headers=outsider).json()["workspaces"] == []


def test_an_invitation_can_only_be_redeemed_once(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    issued = invite(client, owner, created["id"], email=COLLEAGUE["email"])
    colleague = register(client, COLLEAGUE)
    assert accept(client, colleague, issued["token"]).status_code == 200

    again = accept(client, colleague, issued["token"])

    assert again.status_code == 400
    assert "already been used" in again.json()["detail"]


def test_a_revoked_invitation_no_longer_opens_the_workspace(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    issued = invite(client, owner, created["id"], email=COLLEAGUE["email"])

    revoked = client.delete(
        f"/api/workspaces/{created['id']}/invites/{issued['invite']['id']}", headers=owner
    )

    assert revoked.status_code == 204
    colleague = register(client, COLLEAGUE)
    assert accept(client, colleague, issued["token"]).status_code == 400
    detail = client.get(f"/api/workspaces/{created['id']}", headers=owner).json()
    assert detail["invites"] == []
    assert detail["seats_used"] == 1  # the revoked invitation gave its seat back


def test_an_expired_invitation_is_refused(client: TestClient, db: Session) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    issued = invite(client, owner, created["id"], email=COLLEAGUE["email"])
    stored = db.get(WorkspaceInvite, issued["invite"]["id"])
    assert stored is not None
    stored.expires_at = _now() - timedelta(minutes=1)
    db.commit()

    colleague = register(client, COLLEAGUE)
    response = accept(client, colleague, issued["token"])

    assert response.status_code == 400
    assert "expired" in response.json()["detail"]


def test_a_pending_invitation_holds_a_seat(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner, seats=2)

    invite(client, owner, created["id"], email=COLLEAGUE["email"])

    detail = client.get(f"/api/workspaces/{created['id']}", headers=owner).json()
    assert (detail["seats_used"], detail["member_count"]) == (2, 1)
    refused = client.post(
        f"/api/workspaces/{created['id']}/invites",
        json={"email": OUTSIDER["email"]},
        headers=owner,
    )
    assert refused.status_code == 409
    assert "seats are taken" in refused.json()["detail"]


def test_the_seat_limit_cannot_be_lowered_below_the_seats_in_use(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner, seats=3)
    join(client, owner, created["id"], COLLEAGUE)

    refused = client.patch(
        f"/api/workspaces/{created['id']}", json={"seat_limit": 1}, headers=owner
    )

    assert refused.status_code == 409
    raised = client.patch(f"/api/workspaces/{created['id']}", json={"seat_limit": 4}, headers=owner)
    assert raised.status_code == 200
    assert raised.json()["seat_limit"] == 4


def test_only_an_admin_may_invite_or_see_who_was_invited(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    member = join(client, owner, created["id"], COLLEAGUE)

    refused = client.post(
        f"/api/workspaces/{created['id']}/invites",
        json={"email": OUTSIDER["email"]},
        headers=member,
    )

    assert refused.status_code == 404
    assert "admin role" in refused.json()["detail"]
    assert client.get(f"/api/workspaces/{created['id']}", headers=member).json()["invites"] == []


def test_an_admin_may_invite_and_change_roles_but_not_touch_the_owner(
    client: TestClient,
) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    admin = join(client, owner, created["id"], COLLEAGUE, role="admin")
    members = client.get(f"/api/workspaces/{created['id']}", headers=owner).json()["members"]
    owner_id = next(member["user_id"] for member in members if member["is_owner"])
    admin_id = next(member["user_id"] for member in members if not member["is_owner"])

    issued = invite(client, admin, created["id"], email=OUTSIDER["email"], role="viewer")
    assert issued["invite"]["role"] == "viewer"

    demote_owner = client.put(
        f"/api/workspaces/{created['id']}/members/{owner_id}",
        json={"role": "viewer"},
        headers=admin,
    )
    assert demote_owner.status_code == 404
    assert "owner's role cannot be changed" in demote_owner.json()["detail"]
    remove_owner = client.delete(
        f"/api/workspaces/{created['id']}/members/{owner_id}", headers=admin
    )
    assert remove_owner.status_code == 404
    changed = client.put(
        f"/api/workspaces/{created['id']}/members/{admin_id}",
        json={"role": "viewer"},
        headers=owner,
    )
    assert changed.status_code == 200
    assert changed.json()["role"] == "viewer"


def test_nobody_can_be_invited_or_promoted_into_a_second_owner(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    member = join(client, owner, created["id"], COLLEAGUE)
    members = client.get(f"/api/workspaces/{created['id']}", headers=owner).json()["members"]
    member_id = next(entry["user_id"] for entry in members if not entry["is_owner"])

    as_owner = client.post(
        f"/api/workspaces/{created['id']}/invites",
        json={"email": OUTSIDER["email"], "role": "owner"},
        headers=owner,
    )
    assert as_owner.status_code == 404

    promoted = client.put(
        f"/api/workspaces/{created['id']}/members/{member_id}",
        json={"role": "owner"},
        headers=owner,
    )
    assert promoted.status_code == 404
    assert "transferred" in promoted.json()["detail"]
    assert member is not None


def test_removing_a_member_keeps_their_shared_work_and_returns_them_to_private(
    client: TestClient,
) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    colleague = join(client, owner, created["id"], COLLEAGUE)
    contributed = save_budget(client, colleague, title="Their contribution").json()
    members = client.get(f"/api/workspaces/{created['id']}", headers=owner).json()["members"]
    colleague_id = next(entry["user_id"] for entry in members if not entry["is_owner"])

    removed = client.delete(
        f"/api/workspaces/{created['id']}/members/{colleague_id}", headers=owner
    )

    assert removed.status_code == 204
    assert contributed["id"] in library_ids(client, owner)
    assert client.get("/api/workspaces", headers=colleague).json() == {
        "workspaces": [],
        "active_workspace_id": None,
    }
    assert contributed["id"] not in library_ids(client, colleague)


def test_a_member_may_leave_but_the_owner_may_not(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    colleague = join(client, owner, created["id"], COLLEAGUE)
    members = client.get(f"/api/workspaces/{created['id']}", headers=owner).json()["members"]
    owner_id = next(entry["user_id"] for entry in members if entry["is_owner"])
    colleague_id = next(entry["user_id"] for entry in members if not entry["is_owner"])

    left = client.delete(
        f"/api/workspaces/{created['id']}/members/{colleague_id}", headers=colleague
    )

    assert left.status_code == 204
    assert client.get(f"/api/workspaces/{created['id']}", headers=colleague).status_code == 404
    stuck = client.delete(f"/api/workspaces/{created['id']}/members/{owner_id}", headers=owner)
    assert stuck.status_code == 404
    assert "transfer the workspace or delete it" in stuck.json()["detail"]


def test_transferring_ownership_hands_over_the_workspace_and_leaves_an_admin(
    client: TestClient,
) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    colleague = join(client, owner, created["id"], COLLEAGUE)
    members = client.get(f"/api/workspaces/{created['id']}", headers=owner).json()["members"]
    colleague_id = next(entry["user_id"] for entry in members if not entry["is_owner"])

    moved = client.post(f"/api/workspaces/{created['id']}/owner/{colleague_id}", headers=owner)

    assert moved.status_code == 200, moved.text
    roles = {entry["user_id"]: entry["role"] for entry in moved.json()["members"]}
    assert roles[colleague_id] == "owner"
    assert set(roles.values()) == {"owner", "admin"}
    # The new owner can now do what only an owner may.
    assert (
        client.patch(
            f"/api/workspaces/{created['id']}", json={"name": "Renamed"}, headers=colleague
        ).status_code
        == 200
    )
    assert client.delete(f"/api/workspaces/{created['id']}", headers=owner).status_code == 404


def test_deleting_a_workspace_removes_its_shared_work_and_keeps_private_work(
    client: TestClient,
) -> None:
    owner = register(client, OWNER)
    private = save_budget(client, owner, title="Kept alone").json()
    created = make_workspace(client, owner)
    colleague = join(client, owner, created["id"], COLLEAGUE)
    shared = save_budget(client, owner, title="Shared budget").json()
    shared_protocol = save_protocol(client, owner).json()

    deleted = client.delete(f"/api/workspaces/{created['id']}", headers=owner)

    assert deleted.status_code == 204
    assert library_ids(client, owner) == {private["id"]}
    assert client.get(f"/api/library/{shared['id']}", headers=owner).status_code == 404
    assert client.get(f"/api/protocols/{shared_protocol['id']}", headers=owner).status_code == 404
    for headers in (owner, colleague):
        assert client.get("/api/workspaces", headers=headers).json() == {
            "workspaces": [],
            "active_workspace_id": None,
        }


def test_an_active_workspace_that_no_longer_exists_reads_as_private(
    client: TestClient, db: Session
) -> None:
    owner = register(client, OWNER)
    private = save_budget(client, owner, title="Kept alone").json()
    account = db.scalar(User.__table__.select().where(User.email == OWNER["email"]))
    assert account is not None
    db.execute(
        User.__table__.update()
        .where(User.email == OWNER["email"])
        .values(active_workspace_id="a-workspace-that-was-deleted")
    )
    db.commit()

    assert library_ids(client, owner) == {private["id"]}
    assert client.get("/api/workspaces", headers=owner).json()["active_workspace_id"] is None


def test_membership_changes_are_recorded_in_the_audit_trail(client: TestClient) -> None:
    owner = register(client, OWNER)
    created = make_workspace(client, owner)
    issued = invite(client, owner, created["id"], email=COLLEAGUE["email"])
    colleague = register(client, COLLEAGUE)
    accept(client, colleague, issued["token"])

    events = client.get("/api/audit/events", headers=owner).json()
    names = [event["event"] for event in events["events"]]

    assert "workspace.created" in names
    assert "workspace.invited" in names
    # Neither the token nor the invited address may appear anywhere in the trail.
    body = client.get("/api/audit/events", headers=owner).text
    assert issued["token"] not in body
    assert COLLEAGUE["email"] not in body
    accepted = client.get("/api/audit/events", headers=colleague).json()["events"]
    assert "workspace.invite_accepted" in [event["event"] for event in accepted]
