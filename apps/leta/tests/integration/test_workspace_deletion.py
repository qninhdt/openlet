"""Launched by Go: real native callbacks while WorkspaceChanges holds deletion."""

import asyncio
import json
import os
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid7

import httpx
import pytest
from openlet.authz import AuthorizationClient, Resource, check
from openlet.clients.workspace import WorkspaceClient
from openlet.rpc import Actor, RpcClient
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.contrib.pydantic import pydantic_data_converter
from test_domain import root_input
from test_human_requests_integration import ask, response
from test_human_workflow import handle, opening
from test_schedules_integration import change
from test_store_integration import active_box, message

from leta.domain import NewHumanRequest
from leta.runtime.human import PersonalResource, request_access
from leta.temporal.bridges import (
    change_schedule,
    deliver_agent_input,
    open_human_request,
    resolve_human_request,
)
from leta.temporal.human_activities import HumanActivities
from leta.temporal.lifecycle_activities import LifecycleActivities
from leta.temporal.lifecycle_types import ResourceRef
from leta.temporal.schedule_activities import ScheduleActivities
from leta.temporal.types import AgentInput, RunInput, RunResult
from leta.transport.grpc import serve
from leta.worker import agent_workers

pytestmark = pytest.mark.integration


async def test_native_delete_settles_humans_schedules_and_running_agents(
    store, settings
):
    raw = os.getenv("OPENLET_TEST_WORKSPACE_DELETION")
    if not raw:
        pytest.skip("run TestIntegrationWorkspaceDeletionWaitsForNativeLetaCleanup")
    fixture = json.loads(raw)
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
    client = await Client.connect(
        fixture["temporal_address"],
        namespace="openlet",
        data_converter=pydantic_data_converter,
    )
    grant_started, grant_release = asyncio.Event(), asyncio.Event()
    entered = {id: asyncio.Event() for id in (root.id, box.letis[0].id)}
    cleaned = set()

    class HeldGrant(WorkspaceClient):
        async def change_scope_access(self, request, *, actor):
            grant_started.set()
            await grant_release.wait()
            return await super().change_scope_access(request, actor=actor)

    @activity.defn(name="run_agent")
    async def busy(value: RunInput) -> RunResult:
        entered[value.agent_id].set()
        try:
            while True:
                activity.heartbeat()
                await asyncio.sleep(0.02)
        finally:
            cleaned.add(value.agent_id)

    async with (
        RpcClient(fixture["address"], fixture["token"], allow_plaintext=True) as rpc,
        httpx.AsyncClient(base_url=fixture["control"], timeout=70) as control,
        asyncio.timeout(80),
    ):
        scopes = HeldGrant(rpc)
        graph = AuthorizationClient(
            fixture["graph_address"], fixture["graph_key"], allow_plaintext=True
        )
        try:
            lifecycle = LifecycleActivities(store, scopes, None, graph, client)
            await lifecycle.publish_leta_resource(ResourceRef(leta_id=root.id))
            human = HumanActivities(store, scopes, client)
            schedules = ScheduleActivities(store, client)
            async with (
                serve(
                    replace(settings, rpc_listen_addr="127.0.0.1:0"),
                    store,
                    store.database.check,
                    temporal=client,
                    scopes=scopes,
                ) as port,
                agent_workers(client, store, busy, lifecycle, human, schedules),
            ):
                assert (
                    await control.post("/bind", json={"address": f"127.0.0.1:{port}"})
                ).status_code == 204
                for id in entered:
                    await deliver_agent_input(
                        client, AgentInput(message=message(root, recipient_agent_id=id))
                    )
                    await entered[id].wait()
                pending = ask(root).model_copy(
                    update={"requester_agent_id": box.letis[0].id}
                )
                await open_human_request(client, store, opening(pending))
                context = SimpleNamespace(
                    root=await store.get_agent(root.id, root.id),
                    agent=await store.get_agent(root.id, box.letis[0].id),
                    request=RunInput(
                        leta_id=root.id, agent_id=box.letis[0].id, run_id=uuid7()
                    ),
                    workspace=SimpleNamespace(actor=Actor("leta", root.id)),
                    store=store,
                    scopes=scopes,
                    temporal=client,
                )
                opened = await request_access(
                    context,
                    uuid7(),
                    PersonalResource(
                        type="personal_scope", user_id=fixture["owner_id"]
                    ),
                )
                row = await store.get_request(root.id, UUID(opened["request_id"]))
                approval = NewHumanRequest(
                    **{key: row[key] for key in NewHumanRequest.model_fields}
                )
                await resolve_human_request(
                    client,
                    store,
                    response(
                        approval,
                        action="accept",
                        actor_user_id=approval.approver_user_id,
                    ),
                )
                await grant_started.wait()
                schedule = await change_schedule(
                    client,
                    change(root, spec={"type": "interval", "every_seconds": 3600}),
                    command_id="create",
                )
                deletion = asyncio.create_task(control.post("/delete"))
                try:
                    async with asyncio.timeout(15):
                        while (await control.get("/state")).json()[
                            "status"
                        ] != "deleting":
                            await asyncio.sleep(0.02)
                    assert (await control.get("/state")).json()["storage_calls"] == 0
                    assert not deletion.done()
                    grant_release.set()
                    assert (await deletion).status_code == 204
                    assert cleaned == set(entered)
                    assert (
                        await handle(client, pending).result()
                    ).status == "cancelled"
                    result = await handle(client, approval).result()
                    assert (
                        result.status == "resolved"
                        and result.outcome["granted"] is False
                    )
                    assert (await store.get_schedule(root.id, schedule.id))[
                        "deleted_at"
                    ] is not None
                    for id in entered:
                        assert (
                            await client.get_workflow_handle(f"agent/{id}").describe()
                        ).status == WorkflowExecutionStatus.COMPLETED
                    assert (await store.get_agent(root.id, root.id))[
                        "status"
                    ] == "archived"
                    assert not await check(
                        graph,
                        Actor("leta", root.id),
                        "read_content",
                        Resource("scope", fixture["personal_scope_id"]),
                    )
                finally:
                    grant_release.set()
                    deletion.cancel()
                    await asyncio.gather(deletion, return_exceptions=True)
        finally:
            await graph.close()
