"""Gateway JWT verification, actor header stripping, validation, and internal RPC hiding."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .conftest import AccountFixture, new_uuid

if TYPE_CHECKING:
    import httpx


def test_gateway_verifies_jwt_strips_headers_and_hides_internal_rpcs(
    raw_client: httpx.Client,
    account: AccountFixture,
) -> None:
    assert raw_client.get("/v1/workspaces").status_code == 401
    assert (
        raw_client.get(
            "/v1/workspaces", headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 401
    )

    me = account.api.get(
        "/v1/me",
        headers={
            "x-openlet-user-id": new_uuid(),
            "x-openlet-agent-id": new_uuid(),
            "x-openlet-clerk-subject": "spoofed",
        },
    )
    assert me.is_success, me.text
    assert me.json()["id"] == account.id

    invalid = account.api.get("/v1/workspaces/not-a-uuid")
    assert invalid.status_code == 400
    assert invalid.json().get("code") == 3

    internal = account.api.post(
        "/openlet.platform.v1.PlatformInternalService/CheckWorkspaceActive",
        json={"workspaceId": account.workspace_id},
    )
    assert internal.status_code >= 400
