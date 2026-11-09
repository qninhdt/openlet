import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from uuid import uuid7

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import OperationalError
from test_agent_workflow import wait_for_state
from test_runtime import RecordingModel, call, harness, saved_state
from test_store_integration import active_root, message

from leta.domain import ActivityKind
from leta.runtime import runner as runner_module
from leta.temporal.bridges import control_agent, deliver_agent_input, start_agent
from leta.temporal.types import AgentControl, AgentInput, AgentStart, RunInput
from leta.worker import agent_workers

pytestmark = pytest.mark.integration


async def test_real_temporal_worker_kill_recovers_saved_tool_result(
    store, postgres_dsn, persistent_temporal, catalog_data, monkeypatch
):
    root = await active_root(store)
    client = persistent_temporal
    async with store.transaction() as cursor:
        await cursor.execute(
            "CREATE TABLE fixture_shell_effects "
            "(id bigint GENERATED ALWAYS AS IDENTITY)"
        )

    @tool
    async def run_shell(command: str) -> str:
        """Represent an opaque command effect using committed SQL."""
        async with store.transaction() as cursor:
            await cursor.execute("INSERT INTO fixture_shell_effects DEFAULT VALUES")
        return "command finished"

    monkeypatch.setattr(runner_module, "build_tools", lambda context: [run_shell])
    model = RecordingModel(responses=[AIMessage(content="Recovery note")])
    runner, _, _, workspaces = await harness(store, postgres_dsn, model, root=root)
    # AgentWorkflow, rather than the helper, must reserve this journey's run.
    async with store.transaction() as cursor:
        await cursor.execute("DELETE FROM runs WHERE agent_id=%s", (root.id,))
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("runtime_crash_worker.py")),
        env={
            **os.environ,
            "OPENLET_OWNED_RUNTIME_CRASH": json.dumps(
                {
                    "address": client.service_client.config.target_host,
                    "database_url": postgres_dsn,
                    "models": catalog_data,
                    "root": root.model_dump(mode="json"),
                }
            ),
        },
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    delivery = None
    try:
        handle = await start_agent(
            client, AgentStart(leta_id=root.id, agent_id=root.id)
        )
        delivery = asyncio.create_task(
            deliver_agent_input(client, AgentInput(message=message(root)))
        )
        async with asyncio.timeout(20):
            _, errors = await process.communicate()
            assert process.returncode == -signal.SIGKILL, errors.decode(
                errors="replace"
            )
        async with agent_workers(client, store, runner.run_agent), asyncio.timeout(45):
            assert (await delivery).seq == 1
            await wait_for_state(
                handle, lambda state: state.cursor == 1 and state.run_id is None
            )
            await control_agent(client, root.id, AgentControl(action="stop"))
            await handle.result()
        async with store.transaction() as cursor:
            effects = await (
                await cursor.execute(
                    "SELECT count(*) AS total FROM fixture_shell_effects"
                )
            ).fetchone()
        assert effects["total"] == 1
        assert len(model.calls) == workspaces.opened == workspaces.closed == 1
        runs = await store.list_runs(root.id, root.id)
        assert len(runs) == 1 and runs[0]["status"] == "completed"
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
        if delivery is not None and not delivery.done():
            delivery.cancel()
            await asyncio.gather(delivery, return_exceptions=True)


@pytest.mark.parametrize("result_saved", [False, True])
async def test_saved_tool_result_reuse_and_unfinished_shell_reexecution(
    store, postgres_dsn, monkeypatch, result_saved
):
    async with store.transaction() as cursor:
        await cursor.execute(
            "CREATE TABLE fixture_shell_effects "
            "(id bigint GENERATED ALWAYS AS IDENTITY)"
        )

    @tool
    async def run_shell(command: str) -> str:
        """Represent an opaque shell effect using real committed SQL."""
        async with store.transaction() as cursor:
            await cursor.execute("INSERT INTO fixture_shell_effects DEFAULT VALUES")
        return "command finished"

    monkeypatch.setattr(runner_module, "build_tools", lambda context: [run_shell])
    model = RecordingModel(
        responses=[call("run_shell", command="do work"), AIMessage(content="Note")]
    )
    runner, request, root, _ = await harness(store, postgres_dsn, model)
    await store.receive(message(root))
    original = store.append_activity
    lost = False

    async def crash(value):
        nonlocal lost
        if value.kind == ActivityKind.TOOL_RESULT and not lost:
            lost = True
            if result_saved:
                await original(value)
            raise RuntimeError("process lost after shell execution")
        return await original(value)

    monkeypatch.setattr(store, "append_activity", crash)
    with pytest.raises(RuntimeError, match="process lost"):
        await runner.execute(request)
    assert len(model.calls) == 1
    assert (await runner.execute(request)).outcome == "completed"
    assert len(model.calls) == 2
    async with store.transaction() as cursor:
        row = await (
            await cursor.execute("SELECT count(*) AS total FROM fixture_shell_effects")
        ).fetchone()
    assert row["total"] == (1 if result_saved else 2)
    entries = await store.list_activity(root.id, root.id)
    assert [entry["kind"] for entry in entries] == [
        "inbox_input",
        "assistant",
        "tool_call",
        "tool_result",
        "final_note",
    ]


async def test_overlap_serializes_and_rechecks_terminal_result(store, postgres_dsn):
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(messages, number):
        entered.set()
        await release.wait()

    model = RecordingModel(responses=[AIMessage(content="Note")], on_call=hold)
    runner, request, root, workspaces = await harness(store, postgres_dsn, model)
    await store.receive(message(root))
    first = asyncio.create_task(runner.execute(request))
    second = None
    try:
        async with asyncio.timeout(15):
            await entered.wait()
            second = asyncio.create_task(runner.execute(request))
            async with store.database.connection() as connection:
                while True:
                    row = await (
                        await connection.execute(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE query LIKE 'SELECT pg_try_advisory_lock%' "
                            "AND pid<>pg_backend_pid()"
                        )
                    ).fetchone()
                    if row[0] == 1 and workspaces.opened == 1:
                        break
                    await asyncio.sleep(0.01)
            assert not second.done()
            release.set()
            assert await first == await second
    finally:
        for task in (first, second):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(t for t in (first, second) if t is not None), return_exceptions=True
        )
    assert len(model.calls) == workspaces.opened == workspaces.closed == 1


async def test_cancellation_releases_lock_and_invocation_resources(store, postgres_dsn):
    entered = asyncio.Event()

    async def hold(messages, number):
        if number == 1:
            entered.set()
            await asyncio.Event().wait()

    model = RecordingModel(responses=[AIMessage(content="Note")], on_call=hold)
    runner, request, root, workspaces = await harness(store, postgres_dsn, model)
    await store.receive(message(root))
    task = asyncio.create_task(runner.execute(request))
    try:
        async with asyncio.timeout(15):
            await entered.wait()
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert workspaces.opened == workspaces.closed == 1
    async with asyncio.timeout(15):
        assert (await runner.execute(request)).outcome == "completed"
    assert workspaces.opened == workspaces.closed == 2


async def test_long_run_keeps_ram_state_and_same_thread_across_yield(
    store, postgres_dsn, monkeypatch
):
    @tool
    async def next_step() -> str:
        """Continue a deterministic long task."""
        return "done"

    monkeypatch.setattr(runner_module, "build_tools", lambda context: [next_step])
    model = RecordingModel(
        responses=[
            *[call("next_step", identity=f"step-{i}") for i in range(110)],
            AIMessage(content="Note"),
        ]
    )
    runner, request, root, _ = await harness(store, postgres_dsn, model)
    await store.receive(message(root))
    loads = 0
    original = AsyncPostgresSaver.aget_tuple

    async def load(self, config):
        nonlocal loads
        loads += 1
        return await original(self, config)

    monkeypatch.setattr(AsyncPostgresSaver, "aget_tuple", load)

    async def yield_midway(messages, number):
        if number == 60:
            await store.request_run_yield(**request.model_dump())

    model.on_call = yield_midway
    assert (await runner.execute(request)).outcome == "yielded"
    assert len(model.calls) == 60
    assert (await runner.execute(request)).outcome == "completed"
    assert len(model.calls) == 111
    assert loads <= 8
    state = await saved_state(postgres_dsn, root.id)
    assert state["business_run_id"] == str(request.run_id)
    assert len([m for m in state["messages"] if isinstance(m, HumanMessage)]) == 1
    # A new business run keeps the same lifetime thread and working messages.
    next_request = RunInput(leta_id=root.id, agent_id=root.id, run_id=uuid7())
    await store.start_run(**next_request.model_dump())
    await store.receive(message(root, content="Next task"))
    model.responses = [AIMessage(content="Next note")]
    model.i = 0
    assert (await runner.execute(next_request)).cursor == 2
    state = await saved_state(postgres_dsn, root.id)
    assert len([m for m in state["messages"] if isinstance(m, HumanMessage)]) == 2


async def test_upstream_safeguard_yields_instead_of_ending_business_run(
    store, postgres_dsn, monkeypatch
):
    @tool
    async def next_step() -> str:
        """Continue a deterministic task."""
        return "done"

    monkeypatch.setattr(runner_module, "build_tools", lambda context: [next_step])
    monkeypatch.setattr(runner_module, "GRAPH_RECURSION_LIMIT", 40)
    model = RecordingModel(
        responses=[
            *[call("next_step", identity=f"step-{i}") for i in range(15)],
            AIMessage(content="Note"),
        ]
    )
    runner, request, root, _ = await harness(store, postgres_dsn, model)
    await store.receive(message(root))
    results = []
    async with asyncio.timeout(20):
        while True:
            result = await runner.execute(request)
            results.append(result)
            if result.outcome == "completed":
                break
    assert len(results) > 1 and all(r.outcome == "yielded" for r in results[:-1])
    assert len(model.calls) == 16
    state = await saved_state(postgres_dsn, root.id)
    assert state["business_run_id"] == str(request.run_id)
    assert len([m for m in state["messages"] if isinstance(m, HumanMessage)]) == 1


async def test_saver_connection_loss_ends_attempt_without_reconnect(
    store, postgres_dsn
):
    async def terminate_owner(messages, number):
        if number == 1:
            async with store.transaction() as cursor:
                row = await (
                    await cursor.execute(
                        "SELECT pid FROM pg_locks WHERE locktype='advisory' AND granted"
                    )
                ).fetchone()
                assert row is not None
                await cursor.execute("SELECT pg_terminate_backend(%s)", (row["pid"],))

    model = RecordingModel(
        responses=[AIMessage(content="Note")], on_call=terminate_owner
    )
    runner, request, root, workspaces = await harness(store, postgres_dsn, model)
    await store.receive(message(root))
    with pytest.raises(OperationalError):
        await runner.execute(request)
    assert workspaces.opened == workspaces.closed == 1
    assert (await runner.execute(request)).outcome == "completed"
    assert len(model.calls) == workspaces.opened == workspaces.closed == 2
