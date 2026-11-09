import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock
from uuid import uuid7

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from mirage import Workspace
from mirage.vfs import RAMVFS
from openlet.errors import AppError
from openlet.rpc import Actor
from openlet_api.workspace.v1 import workspace_pb2 as pb
from pydantic import Field
from temporalio.client import Client
from test_engine_compatibility import ScriptedModel
from test_store_integration import active_box, active_root, message

from leta.domain import AgentConfiguration
from leta.runtime.runner import AgentRunner
from leta.temporal.types import RunInput

pytestmark = pytest.mark.integration


class RecordingModel(ScriptedModel):
    calls: list = Field(default_factory=list)
    tools_seen: list[str] = Field(default_factory=list)
    selections: list = Field(default_factory=list)
    summary_calls: list = Field(default_factory=list)
    on_summary: Any = None
    on_call: Any = None

    def bind_tools(self, tools, **kwargs):
        self.tools_seen = [item.name for item in tools]
        return self

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if (
            messages
            and isinstance(messages[0].content, str)
            and messages[0].content.startswith("Summarize the public working history")
        ):
            self.summary_calls.append(list(messages))
            output = (
                await self.on_summary(messages)
                if self.on_summary
                else AIMessage(content="Continuation summary")
            )
            return ChatResult(generations=[ChatGeneration(message=output)])
        self.calls.append(list(messages))
        if self.on_call:
            await self.on_call(messages, len(self.calls))
        return await super()._agenerate(messages, stop, run_manager, **kwargs)


class TestScopes:
    __test__ = False

    def __init__(self, root):
        self.root = root

    async def get_workspace(self, workspace_id, *, actor):
        assert workspace_id == str(self.root.workspace_id)
        assert actor == Actor("leta", self.root.id)
        return pb.Workspace(id=workspace_id, name="Workspace", status="active")

    async def list_members(self, workspace_id, *, actor, limit, cursor):
        assert workspace_id == str(self.root.workspace_id)
        assert actor == Actor("leta", self.root.id)
        return pb.ListMembersResponse(workspace_id=workspace_id)


class TestWorkspaces:
    __test__ = False

    def __init__(self, root):
        self.scopes = TestScopes(root)
        self.opened = self.closed = self.refreshed = 0
        self.root = root

    @asynccontextmanager
    async def open(self, leta_id, agent_id, invocation_id):
        assert leta_id == self.root.id
        self.opened += 1
        workspace = Workspace({"/home": RAMVFS()}, network=False, env={"HOME": "/home"})

        async def refresh():
            self.refreshed += 1

        try:
            session = await workspace.session(invocation_id)
            await session.shell("cd /home")
            yield SimpleNamespace(
                session=session,
                refresh=refresh,
                guidance=lambda: "HOME=/home",
                actor=Actor("leta", leta_id),
                policy=SimpleNamespace(backends={}),
            )
        finally:
            await workspace.close()
            self.closed += 1


async def harness(store, postgres_dsn, model, *, root=None, target=None, client=None):
    root = root or await active_root(store)
    target = target or root.id
    workspaces = TestWorkspaces(root)

    @asynccontextmanager
    async def provider():
        def select(selection):
            model.selections.append(selection)
            return model

        yield select

    runner = AgentRunner(
        store, workspaces, postgres_dsn, provider, client or Mock(spec=Client)
    )
    request = RunInput(leta_id=root.id, agent_id=target, run_id=uuid7())
    await store.start_run(**request.model_dump())
    return runner, request, root, workspaces


async def saved_state(postgres_dsn, agent_id):
    async with AsyncPostgresSaver.from_conn_string(postgres_dsn) as saver:
        return (await saver.aget({"configurable": {"thread_id": str(agent_id)}}))[
            "channel_values"
        ]


def call(name, /, identity="call-1", **args):
    return AIMessage(
        content="", tool_calls=[{"id": identity, "name": name, "args": args}]
    )


async def test_digest_safe_steering_and_config_change(store, postgres_dsn):
    model = RecordingModel(
        responses=[call("list_workspace_members"), AIMessage(content="Note")]
    )
    runner, request, root, workspaces = await harness(store, postgres_dsn, model)
    first = message(root, content="First task", conversation_key="owner")
    await store.receive(first)
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(messages, number):
        if number == 1:
            entered.set()
            await release.wait()

    model.on_call = hold
    task = asyncio.create_task(runner.execute(request))
    waiting = asyncio.create_task(entered.wait())
    try:
        async with asyncio.timeout(15):
            await asyncio.wait({task, waiting}, return_when=asyncio.FIRST_COMPLETED)
            if task.done():
                await task
            await store.receive(
                message(
                    root,
                    content="New reminder",
                    conversation_key="schedule",
                    source={
                        "type": "future.plugin",
                        "id": "timer",
                        "label": "Reminder",
                    },
                )
            )
            await store.configure_agent(
                root.id,
                root.id,
                AgentConfiguration(
                    system_prompt="Changed prompt", reasoning_effort="high"
                ),
            )
            release.set()
            result = await task
    finally:
        task.cancel()
        waiting.cancel()
        await asyncio.gather(task, waiting, return_exceptions=True)
    assert result.cursor == 2 and result.outcome == "completed"
    assert "Changed prompt" not in model.calls[0][0].content
    assert "Changed prompt" in model.calls[1][0].content
    assert model.selections[0].reasoning_effort is None
    assert model.selections[-1].reasoning_effort == "high"
    state = await saved_state(postgres_dsn, root.id)
    messages = state["messages"]
    assert [type(m) for m in messages] == [
        HumanMessage,
        AIMessage,
        ToolMessage,
        HumanMessage,
        AIMessage,
    ]
    first_batch = messages[0].additional_kwargs["openlet"]["payload"]
    assert first_batch["mode"] == "digest" and "items" not in first_batch
    assert first_batch["groups"][0]["message_ids"] == [str(first.id)]
    assert (
        messages[3].additional_kwargs["openlet"]["payload"]["groups"][0]["source"][
            "type"
        ]
        == "future.plugin"
    )
    assert messages[1].id and messages[1].tool_calls[0]["id"] == "call-1"
    assert await runner.execute(request) == result
    assert len(model.calls) == 2 and workspaces.opened == workspaces.closed == 1


async def test_leti_collects_all_pages_without_inbox_tools(store, postgres_dsn):
    root = await active_root(store)
    box = await active_box(store, root)
    target = box.letis[0].id
    for index in range(205):
        await store.receive(
            message(root, target=target, content=f"Item {index}", conversation_key=None)
        )
    model = RecordingModel(responses=[AIMessage(content="Note")])
    # Use a large context to test paging independently of the context-limit gate.
    store.models = store.models.model_copy(
        update={
            "models": [
                store.models.models[0].model_copy(
                    update={"context_window_tokens": 1000000}
                )
            ]
        }
    )
    runner, request, _, _ = await harness(
        store, postgres_dsn, model, root=root, target=target
    )
    result = await runner.execute(request)
    assert result.cursor == 205
    batch = model.calls[0][-1].additional_kwargs["openlet"]["payload"]
    assert batch["mode"] == "full" and "groups" not in batch
    assert [item["content"] for item in batch["items"]] == [
        f"Item {i}" for i in range(205)
    ]
    assert "run_shell" in model.tools_seen
    assert not {"read_inbox", "list_inbox"} & set(model.tools_seen)


async def test_oversize_batch_does_not_advance_cursor(store, postgres_dsn):
    root = await active_root(store)
    box = await active_box(store, root)
    target = box.letis[0].id
    model = RecordingModel(responses=[AIMessage(content="Never called")])
    runner, request, _, workspaces = await harness(
        store, postgres_dsn, model, root=root, target=target
    )
    await store.receive(message(root, target=target, content="x" * 50000))
    with pytest.raises(AppError, match="context budget"):
        await runner.execute(request)
    state = await saved_state(postgres_dsn, target)
    assert state["inbox_cursor"] == 0 and state["messages"] == []
    assert model.calls == [] and workspaces.opened == workspaces.closed


async def test_completed_checkpoint_finalizes_without_new_model(
    store, postgres_dsn, monkeypatch
):
    model = RecordingModel(responses=[AIMessage(content="Note")])
    runner, request, root, _ = await harness(store, postgres_dsn, model)
    await store.receive(message(root))
    original = store.save_run

    async def crash(**kwargs):
        raise RuntimeError("SQL finalization unavailable")

    monkeypatch.setattr(store, "save_run", crash)
    with pytest.raises(RuntimeError, match="finalization"):
        await runner.execute(request)
    monkeypatch.setattr(store, "save_run", original)
    assert (await runner.execute(request)).outcome == "completed"
    assert len(model.calls) == 1


async def test_inbox_checkpoint_resumes_pending_model_once(store, postgres_dsn):
    async def crash(messages, number):
        if number == 1:
            raise RuntimeError("process lost before model response")

    model = RecordingModel(responses=[AIMessage(content="Note")], on_call=crash)
    runner, request, root, _ = await harness(store, postgres_dsn, model)
    await store.receive(message(root))
    with pytest.raises(RuntimeError, match="process lost"):
        await runner.execute(request)
    state = await saved_state(postgres_dsn, root.id)
    assert state["inbox_cursor"] == 1 and len(state["messages"]) == 1
    assert (await runner.execute(request)).cursor == 1
    state = await saved_state(postgres_dsn, root.id)
    assert len([m for m in state["messages"] if isinstance(m, HumanMessage)]) == 1


async def test_pause_yield_and_resume_without_new_input(
    store, postgres_dsn, monkeypatch
):
    root = await active_root(store)
    async with store.transaction() as cursor:
        await cursor.execute("UPDATE agents SET paused=true WHERE id=%s", (root.id,))
    model = RecordingModel(responses=[AIMessage(content="Note")])
    runner, request, _, _ = await harness(store, postgres_dsn, model, root=root)
    await store.receive(message(root))
    result = await runner.execute(request)
    assert result.outcome == "paused" and result.cursor == 0 and not model.calls
    # A retry while still paused must not consume the continuation.
    assert await runner.execute(request) == result
    async with store.transaction() as cursor:
        await cursor.execute("UPDATE agents SET paused=false WHERE id=%s", (root.id,))
    await store.request_run_yield(**request.model_dump())
    result = await runner.execute(request)
    assert result.outcome == "yielded" and result.cursor == 0 and not model.calls
    original = store.get_agent
    reads = 0

    async def late_pause(leta_id, agent_id):
        nonlocal reads
        reads += 1
        # After runner's early pause check, just before boundary refresh.
        if reads == 2:
            async with store.transaction() as cursor:
                await cursor.execute(
                    "UPDATE agents SET paused=true WHERE id=%s", (root.id,)
                )
        return await original(leta_id, agent_id)

    monkeypatch.setattr(store, "get_agent", late_pause)
    assert (await runner.execute(request)).outcome == "paused"
    assert not model.calls
    monkeypatch.setattr(store, "get_agent", original)
    async with store.transaction() as cursor:
        await cursor.execute("UPDATE agents SET paused=false WHERE id=%s", (root.id,))
    result = await runner.execute(request)
    assert (
        result.outcome == "completed" and result.cursor == 1 and len(model.calls) == 1
    )


async def test_child_workspace_view_has_only_graph_neighbors(store, postgres_dsn):
    root = await active_root(store)
    box = await active_box(store, root)
    target = box.letis[0].id
    model = RecordingModel(responses=[call("get_workspace"), AIMessage(content="Note")])
    runner, request, _, _ = await harness(
        store, postgres_dsn, model, root=root, target=target
    )
    await store.receive(message(root, target=target))
    assert (await runner.execute(request)).outcome == "completed"
    state = await saved_state(postgres_dsn, target)
    result = json.loads(
        next(m.content for m in state["messages"] if isinstance(m, ToolMessage))
    )
    assert result["leta_id"] == str(root.id) and result["agent_id"] == str(target)
    assert result["messaging_roster"] == [
        {"type": "agent", "id": str(box.letis[1].id), "name": box.letis[1].name},
        {"type": "box", "id": str(box.id), "name": "parent"},
    ]
    assert not any(item["type"] == "user" for item in result["messaging_roster"])


async def test_independent_model_and_reasoning_inheritance(store):
    root = await active_root(store)
    box = await active_box(store, root)
    child = box.letis[0].id
    result = await store.configure_agent(
        root.id, child, AgentConfiguration(reasoning_effort="high")
    )
    assert result["model_id"] is None and result["reasoning_effort"] == "high"
    with pytest.raises(AppError, match="effective model"):
        await store.configure_agent(
            root.id, child, AgentConfiguration(model_id="unknown")
        )
    result = await store.configure_agent(
        root.id, child, AgentConfiguration(reasoning_effort=None)
    )
    assert result["reasoning_effort"] is None
    with pytest.raises(AppError):
        await store.configure_agent(
            uuid7(), child, AgentConfiguration(reasoning_effort="low")
        )


async def test_root_profile_configuration_keeps_child_graph_immutable(store):
    root = await active_root(store)
    box = await active_box(store, root)
    child = box.letis[0].id
    changed = await store.configure_agent(
        root.id,
        root.id,
        AgentConfiguration(
            name="New Leta name", description="Updated profile", system_prompt="Assist"
        ),
    )
    assert changed["name"] == "New Leta name"
    assert changed["description"] == "Updated profile"
    assert changed["system_prompt"] == "Assist"
    for patch in (
        AgentConfiguration(name="New child"),
        AgentConfiguration(description="Different role"),
        AgentConfiguration(system_prompt="Change child prompt"),
    ):
        with pytest.raises(AppError, match="immutable"):
            await store.configure_agent(root.id, child, patch)
    saved = await store.get_agent(root.id, child)
    assert saved["name"] == box.letis[0].name
    assert saved["system_prompt"] == box.letis[0].system_prompt


async def test_worker_shutdown_yields_durable_context_before_next_model(
    store, postgres_dsn
):
    from temporalio.testing import ActivityEnvironment

    root = await active_root(store)
    model = RecordingModel(responses=[AIMessage(content="Continued")])
    runner, request, _, _ = await harness(store, postgres_dsn, model, root=root)
    await store.receive(message(root))
    environment = ActivityEnvironment()
    environment.worker_shutdown()
    result = await environment.run(runner.run_agent, request)
    assert result.outcome == "yielded" and result.cursor == 0
    assert not model.calls
    # A new worker consumes the saved continuation and original inbox exactly once.
    result = await runner.execute(request)
    assert result.outcome == "completed" and result.cursor == 1
    assert len(model.calls) == 1
