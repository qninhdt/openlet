import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from authzed.api.v1 import RelationshipUpdate
from openlet.errors import AppError
from openlet.rpc import Actor
from openlet_api.workspace.v1 import workspace_pb2 as pb
from temporalio import activity
from test_domain import box_input, root_input
from test_store_integration import active_box, active_root

from leta.domain import AgentConfiguration
from leta.temporal.bridges import change_box, change_leta
from leta.temporal.lifecycle_activities import LifecycleActivities
from leta.temporal.lifecycle_types import BoxChange, LetaChange, ResourceRef
from leta.temporal.types import RunInput, RunResult
from leta.worker import agent_workers

pytestmark = pytest.mark.integration


class RemoteServices:
    """External RPC fakes; SQL, lifecycle and Agent Workflows remain real."""

    def __init__(self, root):
        self.root = root
        self.filesystem_id, self.root_id, self.leti_id = (
            str(uuid7()) for _ in range(3)
        )
        self.nodes, self.trash = {}, []
        self.created, self.trashed = 0, 0
        self.graph = SimpleNamespace(WriteRelationships=AsyncMock())
        self.scopes = SimpleNamespace(
            ensure_leta_home_access=AsyncMock(),
            cleanup_leta_access=AsyncMock(),
            get_cleanup_workspace=AsyncMock(),
            list_accessible_scopes=self.list_accessible_scopes,
        )
        self.native = SimpleNamespace(
            create_directories=self.create_directories,
            create_directory=self.create_directory,
            stat=self.stat,
            trash_node=self.trash_node,
            list_trash=self.list_trash,
        )

    async def list_accessible_scopes(self, workspace_id, *, actor, **kwargs):
        assert workspace_id == str(self.root.workspace_id)
        assert actor == Actor("leta", self.root.id)
        result = pb.ListAccessibleScopesResponse(filesystem_id=self.filesystem_id)
        result.items.add(
            id=str(self.root.home_scope_id),
            root_id=self.root_id,
            kind="home",
            rights=pb.ScopeRights(read_metadata=True, write=True),
        )
        return result

    async def create_directories(
        self, filesystem_id, scope_id, parent, components, **kwargs
    ):
        assert parent.node_id == self.root_id and components == [".leti"]
        return SimpleNamespace(id=self.leti_id)

    async def stat(self, filesystem_id, scope_id, locator, **kwargs):
        if locator.node_id not in self.nodes:
            raise AppError(
                "missing", reason="NOT_FOUND", kind="missing", retryable=False
            )
        return SimpleNamespace(node=self.nodes[locator.node_id])

    async def create_directory(
        self, filesystem_id, scope_id, parent, name, key, *, node_id, **kwargs
    ):
        assert parent.node_id == self.leti_id and key == node_id
        from uuid import UUID

        assert UUID(node_id).version == 7
        self.created += 1
        node = SimpleNamespace(
            id=node_id, name=name, parent_id=self.leti_id, kind="directory", revision=1
        )
        self.nodes[node_id] = node
        return node

    async def trash_node(self, filesystem_id, scope_id, locator, *, revision, **kwargs):
        self.trashed += 1
        if locator.node_id not in self.nodes:
            raise AppError(
                "missing", reason="NOT_FOUND", kind="missing", retryable=False
            )
        assert revision == self.nodes[locator.node_id].revision
        del self.nodes[locator.node_id]
        self.trash.append(SimpleNamespace(node_id=locator.node_id))

    async def list_trash(self, *args, **kwargs):
        return self.trash, None


@activity.defn
async def unused_runtime(value: RunInput) -> RunResult:
    raise AssertionError("creating an idle agent must not invoke the model")


async def test_root_lifecycle_create_profile_pause_and_archive(
    store, temporal_environment
):
    root = root_input()
    services = RemoteServices(root)
    client = temporal_environment.client
    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, client
    )
    async with (
        agent_workers(client, store, unused_runtime, lifecycle),
        asyncio.timeout(30),
    ):
        value = LetaChange(leta_id=root.id, action="create", creation=root)
        assert (await change_leta(client, value)).status == "active"
        assert (await change_leta(client, value)).status == "active"
        services.scopes.ensure_leta_home_access.assert_awaited()
        request = services.graph.WriteRelationships.call_args.args[0]
        assert {
            (item.relationship.relation, item.relationship.subject.object.object_type)
            for item in request.updates
        } == {("workspace", "workspace"), ("creator", "user")}
        assert all(
            item.operation == RelationshipUpdate.OPERATION_TOUCH
            for item in request.updates
        )
        await change_leta(
            client,
            LetaChange(
                leta_id=root.id,
                action="configure",
                configuration=AgentConfiguration(name="Renamed"),
            ),
        )
        assert (await store.get_agent(root.id, root.id))["name"] == "Renamed"
        assert (
            await change_leta(client, LetaChange(leta_id=root.id, action="pause"))
        ).agent_ids == [root.id]
        assert (await store.bootstrap_agent(root.id, root.id))["paused"]
        await change_leta(client, LetaChange(leta_id=root.id, action="resume"))
        assert not (await store.bootstrap_agent(root.id, root.id))["paused"]
        assert (
            await change_leta(client, LetaChange(leta_id=root.id, action="deleting"))
        ).status == "archived"
        await client.get_workflow_handle(f"leta-lifecycle/{root.id}").result()
        services.scopes.cleanup_leta_access.assert_awaited_once_with(
            str(root.workspace_id),
            str(root.id),
            str(root.home_scope_id),
            actor=Actor("user", root.created_by_user_id),
        )
        assert (
            services.graph.WriteRelationships.await_count == 2
        )  # Archive retains resource tuples.


async def test_box_lifecycle_retry_identity_delete_and_retention(
    store, temporal_environment
):
    root = await active_root(store)
    box = box_input(root.id)
    services = RemoteServices(root)
    client = temporal_environment.client
    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, client
    )
    async with (
        agent_workers(client, store, unused_runtime, lifecycle),
        asyncio.timeout(30),
    ):
        create = BoxChange(
            leta_id=root.id, box_id=box.id, action="create", creation=box
        )
        assert (await change_box(client, create)).status == "active"
        assert services.created == 1
        assert (await change_box(client, create)).status == "active"
        assert services.created == 1
        snapshot = await change_box(
            client, BoxChange(leta_id=root.id, box_id=box.id, action="deleting")
        )
        assert snapshot.status == "archived"
        await client.get_workflow_handle(f"box-lifecycle/{box.id}").result()
        graph = await store.get_box_graph(root.id, box.id)
        assert all(agent["status"] == "archived" for agent in graph["letis"])
        assert services.trashed == 1
        # An Activity retry discovers the exact known home in trash.
        await lifecycle.trash_box_home(ResourceRef(leta_id=root.id, box_id=box.id))
        assert len(services.trash) == 1
        services.scopes.cleanup_leta_access.assert_not_awaited()
        # Reusing the name creates a new box/home, retaining the original tombstone.
        replacement = box_input(root.id)
        await change_box(
            client,
            BoxChange(
                leta_id=root.id,
                box_id=replacement.id,
                action="create",
                creation=replacement,
            ),
        )
        assert services.created == 2


async def test_box_home_rejects_wrong_reserved_identity(store, temporal_environment):
    root = await active_root(store)
    box = box_input(root.id)
    await store.create_box(box)
    services = RemoteServices(root)
    lifecycle = LifecycleActivities(
        store,
        services.scopes,
        services.native,
        services.graph,
        temporal_environment.client,
    )
    ref = ResourceRef(leta_id=root.id, box_id=box.id)
    await lifecycle.ensure_box_home(ref)
    services.nodes[str(box.home_node_id)].parent_id = str(uuid7())
    from temporalio.exceptions import ApplicationError

    with pytest.raises(ApplicationError, match="identity differs"):
        await lifecycle.ensure_box_home(ref)
    assert services.created == 1


async def test_delete_gate_prevents_late_activation_and_restart(
    store, temporal_environment
):
    root = await active_root(store)
    box = box_input(root.id)
    services = RemoteServices(root)
    entered, release = asyncio.Event(), asyncio.Event()
    original = services.native.create_directory

    async def delayed(*args, **kwargs):
        node = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return node

    services.native.create_directory = delayed
    client = temporal_environment.client
    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, client
    )
    async with (
        agent_workers(client, store, unused_runtime, lifecycle),
        asyncio.timeout(30),
    ):
        pending = asyncio.create_task(
            change_box(
                client,
                BoxChange(
                    leta_id=root.id, box_id=box.id, action="create", creation=box
                ),
            )
        )
        await entered.wait()
        await store.begin_delete(root.id)
        release.set()
        with pytest.raises(AppError, match="not active"):
            await pending
        assert (await store.get_box(root.id, box.id))["status"] == "initializing"
        assert (await store.get_agent(root.id, box.letis[0].id))[
            "status"
        ] == "initializing"


async def test_box_delete_waits_for_busy_runtime_cleanup(store, temporal_environment):
    from leta.domain import NewMessage, Source
    from leta.temporal.bridges import deliver_agent_input
    from leta.temporal.types import AgentInput

    root = await active_root(store)
    box = box_input(root.id)
    services = RemoteServices(root)
    client = temporal_environment.client
    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, client
    )
    entered, cleaned = asyncio.Event(), asyncio.Event()

    @activity.defn(name="run_agent")
    async def busy_runtime(value: RunInput) -> RunResult:
        entered.set()
        try:
            while True:
                activity.heartbeat()
                await asyncio.sleep(0.02)
        finally:
            await asyncio.sleep(0.05)
            cleaned.set()

    original = services.native.trash_node

    async def trash_after_cleanup(*args, **kwargs):
        assert cleaned.is_set()
        return await original(*args, **kwargs)

    services.native.trash_node = trash_after_cleanup
    async with (
        agent_workers(client, store, busy_runtime, lifecycle),
        asyncio.timeout(30),
    ):
        await change_box(
            client,
            BoxChange(leta_id=root.id, box_id=box.id, action="create", creation=box),
        )
        await deliver_agent_input(
            client,
            AgentInput(
                message=NewMessage(
                    id=uuid7(),
                    leta_id=root.id,
                    recipient_agent_id=box.letis[0].id,
                    source=Source(type="fixture", id="source", label="Source"),
                    content="work",
                )
            ),
        )
        await entered.wait()
        assert (
            await change_box(
                client, BoxChange(leta_id=root.id, box_id=box.id, action="deleting")
            )
        ).status == "archived"
        assert cleaned.is_set() and services.trashed == 1
        boot = await store.bootstrap_agent(root.id, box.letis[0].id)
        assert boot["run_id"] is None


async def test_paused_root_new_box_and_archive_keep_home(store, temporal_environment):
    from temporalio.client import WorkflowExecutionStatus
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.worker import Replayer
    from test_agent_workflow import retain_history

    from leta.temporal.lifecycle import LetaLifecycleWorkflow

    root = await active_root(store)
    box = box_input(root.id)
    services = RemoteServices(root)
    client = temporal_environment.client
    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, client
    )
    async with (
        agent_workers(client, store, unused_runtime, lifecycle),
        asyncio.timeout(30),
    ):
        await change_leta(client, LetaChange(leta_id=root.id, action="pause"))
        await change_box(
            client,
            BoxChange(leta_id=root.id, box_id=box.id, action="create", creation=box),
        )
        assert (await store.bootstrap_agent(root.id, box.letis[0].id))["paused"]
        await change_leta(client, LetaChange(leta_id=root.id, action="resume"))
        assert not (await store.bootstrap_agent(root.id, box.letis[0].id))["paused"]
        await change_leta(client, LetaChange(leta_id=root.id, action="deleting"))
        graph = await store.get_box_graph(root.id, box.id)
        assert graph["status"] == "archived" and services.trashed == 0
        assert str(box.home_node_id) in services.nodes
        box_handle = client.get_workflow_handle(f"box-lifecycle/{box.id}")
        async with asyncio.timeout(3):
            while (
                await box_handle.describe()
            ).status == WorkflowExecutionStatus.RUNNING:
                await asyncio.sleep(0.01)
        assert (await box_handle.describe()).status == WorkflowExecutionStatus.CANCELED
        root_handle = client.get_workflow_handle(f"leta-lifecycle/{root.id}")
        await root_handle.result()
        await retain_history(root_handle, "leta-archive-boxes")
        await Replayer(
            workflows=[LetaLifecycleWorkflow], data_converter=pydantic_data_converter
        ).replay_workflow(await root_handle.fetch_history())


@pytest.mark.parametrize("started", [False, True])
async def test_root_archive_accepts_absent_or_closed_box_coordinator(
    store, persistent_temporal, started
):
    # The time-skipping test server leaves failed external cancellation unresolved.
    root = await active_root(store)
    services = RemoteServices(root)
    client = persistent_temporal
    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, client
    )
    async with (
        agent_workers(client, store, unused_runtime, lifecycle),
        asyncio.timeout(30),
    ):
        if started:
            box = box_input(root.id)
            await change_box(
                client,
                BoxChange(
                    leta_id=root.id, box_id=box.id, action="create", creation=box
                ),
            )
            await change_box(
                client, BoxChange(leta_id=root.id, box_id=box.id, action="deleting")
            )
            await client.get_workflow_handle(f"box-lifecycle/{box.id}").result()
        else:
            await active_box(store, root)
        assert (
            await change_leta(client, LetaChange(leta_id=root.id, action="deleting"))
        ).status == "archived"


async def test_coordinator_rotation_and_replay(store, temporal_environment):
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.worker import Replayer

    from leta.temporal.box import BoxLifecycleWorkflow
    from leta.temporal.lifecycle import LetaLifecycleWorkflow
    from leta.temporal.lifecycle_types import LifecycleStart
    from leta.temporal.types import ORCHESTRATION_QUEUE

    root = await active_root(store)
    services = RemoteServices(root)
    client = temporal_environment.client
    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, client
    )
    async with (
        agent_workers(client, store, unused_runtime, lifecycle),
        asyncio.timeout(30),
    ):
        handle = await client.start_workflow(
            LetaLifecycleWorkflow.run,
            LifecycleStart(leta_id=root.id, history_events=15),
            id=f"leta-lifecycle/{root.id}",
            task_queue=ORCHESTRATION_QUEUE,
        )
        original_run_id = handle.first_execution_run_id
        for _ in range(3):
            await change_leta(client, LetaChange(leta_id=root.id, action="pause"))
            await change_leta(client, LetaChange(leta_id=root.id, action="resume"))
        async with asyncio.timeout(5):
            while (
                await client.get_workflow_handle(handle.id).describe()
            ).run_id == original_run_id:
                await asyncio.sleep(0.01)
        history = await client.get_workflow_handle(
            handle.id, run_id=original_run_id
        ).fetch_history()
        from test_agent_workflow import retain_history

        await retain_history(
            client.get_workflow_handle(handle.id, run_id=original_run_id),
            "leta-lifecycle",
        )
        await Replayer(
            workflows=[LetaLifecycleWorkflow], data_converter=pydantic_data_converter
        ).replay_workflow(history)
        await change_leta(client, LetaChange(leta_id=root.id, action="deleting"))
        # Replay a terminal box history across both Activity boundaries.
        other = await active_root(store)
        other_services = RemoteServices(other)
        # Rebind this worker's remote fake to the other root.
        services.root = other
        services.root_id, services.leti_id = (
            other_services.root_id,
            other_services.leti_id,
        )
        box = box_input(other.id)
        await change_box(
            client,
            BoxChange(leta_id=other.id, box_id=box.id, action="create", creation=box),
        )
        await change_box(
            client, BoxChange(leta_id=other.id, box_id=box.id, action="deleting")
        )
        box_handle = client.get_workflow_handle(f"box-lifecycle/{box.id}")
        await box_handle.result()
        await retain_history(box_handle, "box-lifecycle")
        await Replayer(
            workflows=[BoxLifecycleWorkflow], data_converter=pydantic_data_converter
        ).replay_workflow(await box_handle.fetch_history())


async def test_box_tools_run_through_checkpointed_agent(
    store, postgres_dsn, temporal_environment
):
    from types import SimpleNamespace

    from langchain_core.messages import AIMessage
    from test_runtime import RecordingModel, call, harness
    from test_store_integration import message

    from leta.runtime.boxes import get_box, list_boxes

    root = await active_root(store)
    services = RemoteServices(root)
    client = temporal_environment.client
    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, client
    )
    model = RecordingModel(
        responses=[
            call(
                "create_box",
                name="Team",
                description="Test",
                letis=[
                    {
                        "name": "Solo",
                        "description": "Research",
                        "system_prompt": "Research",
                    }
                ],
                edges=[],
                representative="Solo",
            ),
            call("get_box", identity="inspect", box="Team"),
            call("delete_box", identity="delete", box="Team"),
            AIMessage(content="Box archived"),
        ]
    )
    runner, request, _, _ = await harness(
        store, postgres_dsn, model, root=root, client=client
    )
    await store.receive(message(root, content="Create and delete a team"))
    async with (
        agent_workers(client, store, unused_runtime, lifecycle),
        asyncio.timeout(30),
    ):
        assert (await runner.execute(request)).outcome == "completed"
    boxes = await store.list_boxes(root.id)
    assert len(boxes) == 1 and boxes[0]["status"] == "archived"
    assert services.created == services.trashed == 1
    own = SimpleNamespace(agent={"kind": "leta"}, request=request, store=store)
    page = await list_boxes(own, limit=1)
    assert page["items"][0]["agent_count"] == 1
    detail = await get_box(own, str(boxes[0]["id"]))
    assert detail["home"] == "~/.leti/team"
    assert detail["letis"][0]["system_prompt"] == "Research"
    assert detail["requests"] == detail["schedules"] == []


async def test_box_tool_retry_joins_creation_before_home_identity_is_saved(
    store, temporal_environment, monkeypatch
):
    from leta.runtime import boxes

    root = await active_root(store)
    services = RemoteServices(root)
    client = temporal_environment.client
    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, client
    )
    entered, release, retried = asyncio.Event(), asyncio.Event(), asyncio.Event()
    save = store.create_box

    async def held(value):
        entered.set()
        await release.wait()
        return await save(value)

    change = boxes.change_box
    calls = 0

    async def submit(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            retried.set()
        return await change(*args, **kwargs)

    monkeypatch.setattr(store, "create_box", held)
    monkeypatch.setattr(boxes, "change_box", submit)
    context = SimpleNamespace(
        agent={"kind": "leta"},
        request=SimpleNamespace(leta_id=root.id),
        store=store,
        temporal=client,
    )
    box_id = uuid7()
    args = (
        context,
        box_id,
        "Pending team",
        "",
        [boxes.LetiDefinition(name="Solo", system_prompt="Research")],
        [],
        "Solo",
    )
    tasks = []
    async with (
        agent_workers(client, store, unused_runtime, lifecycle),
        asyncio.timeout(20),
    ):
        try:
            tasks.append(asyncio.create_task(boxes.create_box(*args)))
            await entered.wait()
            tasks.append(asyncio.create_task(boxes.create_box(*args)))
            await retried.wait()
            release.set()
            first, second = await asyncio.gather(*tasks)
            assert first == second
            assert services.created == 1
            assert (await store.get_box(root.id, box_id))["status"] == "active"
        finally:
            release.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def test_initializing_root_rejected_by_workspace_deletion_cleans_owned_tuples(
    store, temporal_environment
):
    root = root_input()
    services = RemoteServices(root)
    services.scopes.ensure_leta_home_access.side_effect = AppError(
        "workspace not active",
        reason="STATE_CONFLICT",
        kind="conflict",
        retryable=False,
    )
    client = temporal_environment.client
    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, client
    )
    async with (
        agent_workers(client, store, unused_runtime, lifecycle),
        asyncio.timeout(30),
    ):
        with pytest.raises(AppError, match="workspace is deleting"):
            await change_leta(
                client, LetaChange(leta_id=root.id, action="create", creation=root)
            )
        await client.get_workflow_handle(f"leta-lifecycle/{root.id}").result()
    assert (await store.get_agent(root.id, root.id))["status"] == "archived"
    assert services.graph.WriteRelationships.await_count == 2
    removal = services.graph.WriteRelationships.call_args.args[0]
    assert all(
        item.operation == RelationshipUpdate.OPERATION_DELETE
        for item in removal.updates
    )
    assert {item.relationship.resource.object_type for item in removal.updates} == {
        "leta"
    }
    services.scopes.cleanup_leta_access.assert_not_awaited()


async def test_delete_by_name_recovery_keeps_original_box_after_name_reuse(
    store, postgres_dsn, temporal_environment, monkeypatch
):
    from langchain_core.messages import AIMessage, ToolMessage
    from test_runtime import RecordingModel, call, harness, saved_state
    from test_store_integration import message

    from leta.domain import ActivityKind

    root = await active_root(store)
    box = box_input(root.id)
    services = RemoteServices(root)
    client = temporal_environment.client
    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, client
    )
    model = RecordingModel(
        responses=[
            call("delete_box", box=box.name),
            AIMessage(content="Archived original box"),
        ]
    )
    runner, request, _, _ = await harness(
        store, postgres_dsn, model, root=root, client=client
    )
    await store.receive(message(root))
    append = store.append_activity
    failed = False

    async def fail_result(value, **kwargs):
        nonlocal failed
        if value.kind == ActivityKind.TOOL_RESULT and not failed:
            failed = True
            raise RuntimeError("lost result after deletion")
        return await append(value, **kwargs)

    monkeypatch.setattr(store, "append_activity", fail_result)
    async with (
        agent_workers(client, store, unused_runtime, lifecycle),
        asyncio.timeout(30),
    ):
        await change_box(
            client,
            BoxChange(leta_id=root.id, box_id=box.id, action="create", creation=box),
        )
        with pytest.raises(RuntimeError, match="lost result"):
            await runner.execute(request)
        assert (await store.get_box(root.id, box.id))["status"] == "archived"
        replacement = box_input(root.id)
        await change_box(
            client,
            BoxChange(
                leta_id=root.id,
                box_id=replacement.id,
                action="create",
                creation=replacement,
            ),
        )
        assert (await runner.execute(request)).outcome == "completed"
    assert (await store.get_box(root.id, replacement.id))["status"] == "active"
    assert services.trashed == 1
    state = await saved_state(postgres_dsn, root.id)
    result = next(item for item in state["messages"] if isinstance(item, ToolMessage))
    assert result.status == "success" and str(box.id) in result.content
