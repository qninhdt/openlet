"""Private cleanup admission and existing lifecycle completion over real gRPC."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from authzed.api.v1 import RelationshipUpdate
from openlet.errors import AppError
from openlet.rpc import Actor, RpcClient
from openlet_api.leta.v1 import leta_pb2 as pb
from openlet_api.leta.v1 import leta_pb2_grpc as rpc
from test_domain import box_input, root_input
from test_lifecycle_integration import RemoteServices, unused_runtime
from test_store_integration import active_root

from leta.temporal.bridges import change_box, change_leta
from leta.temporal.lifecycle_activities import LifecycleActivities
from leta.temporal.lifecycle_types import BoxChange, LetaChange
from leta.transport.grpc import serve
from leta.worker import agent_workers

pytestmark = pytest.mark.integration


async def test_workspace_inventory_pages_every_root_state_and_rejects_delegation(
    store, settings
):
    workspace = uuid7()
    roots = []
    for status in ("initializing", "active", "deleting", "archived"):
        root = root_input(workspace_id=workspace)
        await store.create_leta(root)
        if status != "initializing":
            await store.activate_leta(root.id)
        if status in {"deleting", "archived"}:
            await store.begin_delete(root.id)
        if status == "archived":
            await store.archive(root.id)
        roots.append(root.id)
    await active_root(store)
    async with serve(
        replace(settings, rpc_listen_addr="127.0.0.1:0"), store, AsyncMock()
    ) as port:
        async with RpcClient(
            f"127.0.0.1:{port}", settings.workspace_service_token, allow_plaintext=True
        ) as client:
            stub = rpc.LetaServiceStub(client.channel)
            request = pb.ListWorkspaceLetaRequest(workspace_id=str(workspace), limit=2)
            first = await client.invoke(stub.ListWorkspaceLeta, request)
            second = await client.invoke(
                stub.ListWorkspaceLeta,
                pb.ListWorkspaceLetaRequest(
                    workspace_id=str(workspace), cursor=first.next_cursor, limit=2
                ),
            )
            assert [*first.leta_ids, *second.leta_ids] == [
                str(v) for v in sorted(roots)
            ]
            assert not second.HasField("next_cursor")
            with pytest.raises(AppError) as caught:
                await client.invoke(
                    stub.ListWorkspaceLeta, request, actor=Actor("user", uuid7())
                )
            assert caught.value.kind == "forbidden"
            with pytest.raises(AppError) as caught:
                await client.invoke(
                    stub.ListWorkspaceLeta,
                    pb.ListWorkspaceLetaRequest(workspace_id=str(workspace), limit=101),
                )
            assert caught.value.kind == "invalid"


@pytest.mark.parametrize("archived_first", [False, True])
async def test_workspace_stop_waits_for_cleanup_and_recleans_archived_root(
    store, settings, persistent_temporal, archived_first
):
    root = root_input()
    services = RemoteServices(root)
    temporal = persistent_temporal
    deleting = False

    async def cleanup_status(workspace_id, leta_id):
        assert workspace_id == str(root.workspace_id) and leta_id == str(root.id)
        if not deleting:
            raise AppError(
                "workspace active",
                reason="FORBIDDEN",
                kind="forbidden",
                retryable=False,
            )
        return SimpleNamespace(status="deleting")

    services.scopes.get_cleanup_workspace.side_effect = cleanup_status
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(*args, **kwargs):
        entered.set()
        await release.wait()

    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, temporal
    )
    async with agent_workers(temporal, store, unused_runtime, lifecycle):
        await change_leta(
            temporal, LetaChange(leta_id=root.id, action="create", creation=root)
        )
        box = box_input(root.id)
        await change_box(
            temporal,
            BoxChange(leta_id=root.id, box_id=box.id, action="create", creation=box),
        )
        if archived_first:
            await change_leta(temporal, LetaChange(leta_id=root.id, action="deleting"))
            await temporal.get_workflow_handle(f"leta-lifecycle/{root.id}").result()
        services.scopes.cleanup_leta_access.side_effect = hold
        async with serve(
            replace(settings, rpc_listen_addr="127.0.0.1:0"),
            store,
            AsyncMock(),
            temporal=temporal,
            scopes=services.scopes,
        ) as port:
            async with RpcClient(
                f"127.0.0.1:{port}",
                settings.workspace_service_token,
                allow_plaintext=True,
            ) as client:
                stub = rpc.LetaServiceStub(client.channel)
                command = pb.StopLetaForWorkspaceDeletionRequest(
                    workspace_id=str(root.workspace_id), leta_id=str(root.id)
                )
                with pytest.raises(AppError) as caught:
                    await client.invoke(stub.StopLetaForWorkspaceDeletion, command)
                assert caught.value.kind == "forbidden"
                deleting = True
                pending = asyncio.create_task(
                    client.invoke(
                        stub.StopLetaForWorkspaceDeletion, command, timeout=20
                    )
                )
                try:
                    async with asyncio.timeout(10):
                        await entered.wait()
                    assert not pending.done()
                    assert (await store.get_agent(root.id, root.id))["status"] == (
                        "archived" if archived_first else "deleting"
                    )
                    from temporalio.client import WorkflowExecutionStatus

                    for agent_id in [root.id, *(agent.id for agent in box.letis)]:
                        assert (
                            await temporal.get_workflow_handle(
                                f"agent/{agent_id}"
                            ).describe()
                        ).status == WorkflowExecutionStatus.COMPLETED
                    release.set()
                    result = await pending
                    assert result.status == "archived"
                    assert (await store.get_agent(root.id, box.letis[0].id))[
                        "status"
                    ] == "archived"
                    services.scopes.cleanup_leta_access.assert_awaited_with(
                        str(root.workspace_id),
                        str(root.id),
                        str(root.home_scope_id),
                        actor=None,
                    )
                    assert all(
                        item.operation == RelationshipUpdate.OPERATION_DELETE
                        for item in services.graph.WriteRelationships.call_args.args[
                            0
                        ].updates
                    )
                    # Retry remains acknowledged and never revives a producer.
                    assert (
                        await client.invoke(
                            stub.StopLetaForWorkspaceDeletion, command, timeout=20
                        )
                    ).status == "archived"
                    foreign = pb.StopLetaForWorkspaceDeletionRequest(
                        workspace_id=str(uuid7()), leta_id=str(root.id)
                    )
                    with pytest.raises(AppError) as caught:
                        await client.invoke(stub.StopLetaForWorkspaceDeletion, foreign)
                    assert caught.value.kind == "missing"
                finally:
                    release.set()
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
