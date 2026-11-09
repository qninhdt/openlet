"""Launched by the native Workspace fixture with real PostgreSQL and SpiceDB."""

import asyncio
import json
import os
from types import SimpleNamespace
from uuid import UUID, uuid7

import pytest
from openlet.authz import AuthorizationClient, Resource, check
from openlet.clients.workspace import WorkspaceClient
from openlet.errors import AppError
from openlet.rpc import Actor, RpcClient
from openlet_api.workspace.v1 import workspace_pb2 as pb
from psycopg import AsyncConnection
from test_domain import root_input
from test_human_requests_integration import response
from test_human_workflow import handle
from test_lifecycle_integration import unused_runtime
from test_store_integration import active_box

from leta.domain import NewHumanRequest
from leta.runtime.human import PersonalResource, request_access
from leta.temporal.bridges import resolve_human_request, settle_hitl
from leta.temporal.human_activities import HumanActivities
from leta.temporal.human_types import SettleHumanRequest
from leta.temporal.types import RunInput
from leta.worker import agent_workers

pytestmark = pytest.mark.integration


@pytest.fixture
def native_fixture():
    raw = os.getenv("OPENLET_TEST_HITL_WORKSPACE_FIXTURE")
    if not raw:
        pytest.skip(
            "run TestIntegrationWorkspaceNativeReadsGrantsAndCleanup with "
            "OPENLET_LETA_HITL_INTEGRATION=1"
        )
    return json.loads(raw)


async def initialize(store, fixture, scopes, temporal):
    root = root_input().model_copy(
        update={
            "id": UUID(fixture["leta_id"]),
            "workspace_id": UUID(fixture["workspace_id"]),
            "home_scope_id": UUID(fixture["home_scope_id"]),
            "created_by_user_id": UUID(fixture["creator_id"]),
        }
    )
    await store.create_leta(root)
    await store.activate_leta(root.id)
    box = await active_box(store, root)
    await store.set_paused(root.id, True)
    context = SimpleNamespace(
        root=await store.get_agent(root.id, root.id),
        agent=await store.get_agent(root.id, box.letis[0].id),
        request=RunInput(leta_id=root.id, agent_id=box.letis[0].id, run_id=uuid7()),
        workspace=SimpleNamespace(actor=Actor("leta", root.id)),
        store=store,
        scopes=scopes,
        temporal=temporal,
    )
    return root, context


async def test_native_resource_owner_grants_root_and_revoke_changes_current_access(
    store,
    temporal_environment,
    native_fixture,
):
    fixture = native_fixture
    client = temporal_environment.client
    async with RpcClient(
        fixture["address"], fixture["token"], allow_plaintext=True
    ) as rpc:
        scopes = WorkspaceClient(rpc)
        root, context = await initialize(store, fixture, scopes, client)
        human = HumanActivities(store, scopes, client)
        resource = PersonalResource(type="personal_scope", user_id=fixture["owner_id"])
        async with (
            agent_workers(client, store, unused_runtime, human=human),
            asyncio.timeout(30),
        ):
            opened = await request_access(context, uuid7(), resource, reason="Research")
            row = await store.get_request(root.id, UUID(opened["request_id"]))
            request = NewHumanRequest(
                **{key: row[key] for key in NewHumanRequest.model_fields}
            )
            assert request.approver_user_id != root.created_by_user_id
            assert request.grantee_leta_id == root.id
            with pytest.raises(AppError, match="another actor"):
                await resolve_human_request(
                    client,
                    store,
                    response(
                        request,
                        action="accept",
                        actor_user_id=root.created_by_user_id,
                    ),
                )
            # A forged delegated creator is also rejected at the actual Go boundary.
            with pytest.raises(AppError):
                await scopes.change_scope_access(
                    pb.ChangeScopeAccessRequest(
                        workspace_id=str(root.workspace_id),
                        scope_id=fixture["personal_scope_id"],
                        grantee_kind="leta",
                        grantee_id=str(root.id),
                        role="viewer",
                        idempotency_key=str(uuid7()),
                        personal_owner_user_id=str(root.created_by_user_id),
                    ),
                    actor=Actor("user", root.created_by_user_id),
                )
            await resolve_human_request(
                client,
                store,
                response(
                    request,
                    action="accept",
                    actor_user_id=request.approver_user_id,
                ),
            )
            completed = await handle(client, request).result()
            assert completed.outcome["granted"] is True
            assert completed.outcome["scope_id"] == fixture["personal_scope_id"]
            graph = AuthorizationClient(
                fixture["graph_address"], fixture["graph_key"], allow_plaintext=True
            )
            try:
                scope = Resource("scope", fixture["personal_scope_id"])
                assert await check(graph, Actor("leta", root.id), "read_content", scope)
                assert not await check(
                    graph, Actor("user", root.created_by_user_id), "read_content", scope
                )
            finally:
                await graph.close()
            assert (await request_access(context, uuid7(), resource))[
                "status"
            ] == "already_granted"
            assert len(await store.list_requests(root.id)) == 1
            await scopes.change_scope_access(
                pb.ChangeScopeAccessRequest(
                    workspace_id=str(root.workspace_id),
                    scope_id=fixture["personal_scope_id"],
                    grantee_kind="leta",
                    grantee_id=str(root.id),
                    role="viewer",
                    revoke=True,
                    idempotency_key=str(uuid7()),
                ),
                actor=Actor("user", request.approver_user_id),
            )
            from leta.rebuild import rebuild

            graph = AuthorizationClient(
                fixture["graph_address"], fixture["graph_key"], allow_plaintext=True
            )
            try:
                await rebuild(
                    store,
                    graph,
                    [
                        json.dumps(
                            {"workspace_id": str(root.workspace_id), "status": "active"}
                        )
                    ],
                )
                assert not await check(
                    graph, Actor("leta", root.id), "read_content", scope
                )
                assert await check(
                    graph,
                    Actor("user", root.created_by_user_id),
                    "read",
                    Resource("leta", str(root.id)),
                )
            finally:
                await graph.close()
            again = await request_access(context, uuid7(), resource)
            assert again["status"] == "pending"
            await settle_hitl(
                client,
                SettleHumanRequest(
                    leta_id=root.id,
                    request_id=UUID(again["request_id"]),
                    reason="test_complete",
                ),
            )


async def test_native_applied_grant_survives_lost_ack_and_workspace_deletion(
    store,
    temporal_environment,
    native_fixture,
):
    fixture = native_fixture
    client = temporal_environment.client
    attempts = []

    class LoseGrantReply(WorkspaceClient):
        async def change_scope_access(self, request, *, actor):
            result = await super().change_scope_access(request, actor=actor)
            attempts.append(request.idempotency_key)
            if len(attempts) == 1:
                # Test setup closes the real Workspace after its real graph write.
                async with await AsyncConnection.connect(
                    fixture["database_url"], autocommit=True
                ) as connection:
                    await connection.execute(
                        "UPDATE workspaces SET status='deleting' WHERE id=%s",
                        (UUID(fixture["workspace_id"]),),
                    )
                await store.begin_delete(UUID(fixture["leta_id"]))
                raise AppError(
                    "lost grant acknowledgement",
                    reason="DEPENDENCY_UNAVAILABLE",
                    kind="unavailable",
                )
            return result

    async with RpcClient(
        fixture["address"], fixture["token"], allow_plaintext=True
    ) as rpc:
        scopes = LoseGrantReply(rpc)
        root, context = await initialize(store, fixture, scopes, client)
        human = HumanActivities(store, scopes, client)
        resource = PersonalResource(type="personal_scope", user_id=fixture["owner_id"])
        async with (
            agent_workers(client, store, unused_runtime, human=human),
            asyncio.timeout(35),
        ):
            opened = await request_access(context, uuid7(), resource, role="editor")
            row = await store.get_request(root.id, UUID(opened["request_id"]))
            request = NewHumanRequest(
                **{key: row[key] for key in NewHumanRequest.model_fields}
            )
            await resolve_human_request(
                client,
                store,
                response(
                    request,
                    action="accept",
                    actor_user_id=request.approver_user_id,
                ),
            )
            result = await handle(client, request).result()
            assert (
                result.outcome["granted"] is True and result.outcome["role"] == "editor"
            )
            assert len(attempts) == 2 and attempts[0] == attempts[1] == str(
                row["grant_key"]
            )
            with pytest.raises(AppError, match="resource not found"):
                await store.get_message(root.id, request.outcome_message_id)
            # A grant to another currently unreadable scope is rejected during deletion.
            with pytest.raises(AppError):
                await scopes.change_scope_access(
                    pb.ChangeScopeAccessRequest(
                        workspace_id=str(root.workspace_id),
                        scope_id=fixture["creator_personal_scope_id"],
                        grantee_kind="leta",
                        grantee_id=str(root.id),
                        role="viewer",
                        idempotency_key=str(uuid7()),
                        personal_owner_user_id=str(root.created_by_user_id),
                    ),
                    actor=Actor("user", root.created_by_user_id),
                )
