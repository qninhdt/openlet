"""Workspace invitations, member caps, storage grants/revokes, idempotency, and deletion."""

from __future__ import annotations

from .conftest import AccountFactory, AccountFixture, new_uuid, poll


def test_invitation_storage_grant_revoke_and_workspace_deletion(
    account: AccountFixture,
    accounts: AccountFactory,
) -> None:
    guest = accounts.create()
    workspace = f"/v1/workspaces/{account.workspace_id}"
    storage = f"{workspace}/storages/{account.storage_id}"

    assert guest.api.get(storage).status_code == 403

    invite = account.api.post(
        f"{workspace}/invitations",
        json={"email": guest.email, "requestId": new_uuid()},
    )
    assert invite.is_success, invite.text
    token = invite.json()["token"]

    accepted = guest.api.post("/v1/invitations:accept", json={"token": token})
    assert accepted.is_success, accepted.text
    assert accepted.json()["workspaceId"] == account.workspace_id
    poll(
        lambda: guest.api.get(workspace).status_code == 200,
        desc="guest workspace access",
    )

    third = accounts.create()
    overflow = account.api.post(
        f"{workspace}/invitations",
        json={"email": third.email, "requestId": new_uuid()},
    )
    assert overflow.is_success, overflow.text
    overflow_token = overflow.json()["token"]
    over_limit = third.api.post(
        "/v1/invitations:accept", json={"token": overflow_token}
    )
    assert over_limit.status_code == 429, over_limit.text

    def guest_has_storage() -> bool:
        resp = guest.api.get(f"{workspace}/storages?owned_only=true")
        assert resp.is_success, resp.text
        return len(resp.json().get("storages", [])) > 0

    poll(guest_has_storage, desc="guest private storage")
    assert guest.api.get(storage).status_code == 403

    granted = account.api.post(
        f"{storage}:setAccess",
        json={"actor": {"userId": guest.id}, "role": "STORAGE_ROLE_VIEWER"},
    )
    assert granted.is_success, granted.text
    poll(lambda: guest.api.get(storage).status_code == 200, desc="granted storage view")

    forbidden = guest.api.post(
        f"{storage}/nodes",
        json={
            "parent": {"nodeId": account.root_id},
            "name": "denied",
            "directory": {},
            "requestId": new_uuid(),
        },
    )
    assert forbidden.status_code == 403

    revoked = account.api.post(
        f"{storage}:revokeAccess",
        json={"actor": {"userId": guest.id}},
    )
    assert revoked.is_success, revoked.text
    poll(lambda: guest.api.get(storage).status_code == 403, desc="revoked storage view")

    removed = account.api.delete(f"{workspace}/members/{guest.id}")
    assert removed.is_success, removed.text
    poll(lambda: guest.api.get(workspace).status_code == 403, desc="removed member")
    poll(
        lambda: (
            guest.api.post("/v1/invitations:accept", json={"token": token}).status_code
            == 400
        ),
        desc="consumed invitation replay rejected",
    )
    poll(
        lambda: guest.api.get(workspace).status_code == 403, desc="member still removed"
    )

    admitted = third.api.post("/v1/invitations:accept", json={"token": overflow_token})
    assert admitted.is_success, admitted.text

    deleted = account.api.delete(workspace)
    assert deleted.is_success, deleted.text
    poll(
        lambda: account.api.get(workspace).status_code == 403,
        timeout=30.0,
        desc="deleted workspace inaccessible",
    )


def test_workspace_creation_validation_and_receipt_replay(
    account: AccountFixture,
    accounts: AccountFactory,
) -> None:
    payload = {"name": "Second workspace", "requestId": new_uuid()}
    created = account.api.post("/v1/workspaces", json=payload)
    assert created.is_success, created.text
    workspace = created.json()
    assert workspace["name"] == payload["name"]

    replay = account.api.post("/v1/workspaces", json=payload)
    assert replay.is_success, replay.text
    assert replay.json()["id"] == workspace["id"]

    headers = {"x-openlet-zed-token": created.headers["x-openlet-zed-token"]}
    members = account.api.get(
        f"/v1/workspaces/{workspace['id']}/members", headers=headers
    )
    assert members.is_success, members.text
    first = members.json()["members"][0]
    assert first["user"]["id"] == account.id
    assert first["role"] == "WORKSPACE_ROLE_OWNER"

    guest = accounts.create()
    assert guest.api.get(f"/v1/workspaces/{workspace['id']}").status_code == 403

    invalid = account.api.post(
        "/v1/workspaces",
        json={**payload, "name": "", "requestId": new_uuid()},
    )
    assert invalid.status_code == 400

    assert account.api.delete(
        f"/v1/workspaces/{workspace['id']}", headers=headers
    ).is_success
