import json
from time import perf_counter
from types import SimpleNamespace
from uuid import uuid7

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from openlet.errors import AppError
from test_runtime import RecordingModel, call, harness, saved_state
from test_store_integration import active_box, active_root, message

from leta.filesystem.tools import FilesystemTools
from leta.history import activity_entry
from leta.runtime import runner as runner_module
from leta.runtime.history import read_history, search_history
from leta.temporal.types import RunInput

pytestmark = pytest.mark.integration


def assert_complete_tool_groups(messages):
    pending = set()
    for item in messages:
        if isinstance(item, ToolMessage):
            assert item.tool_call_id in pending
            pending.remove(item.tool_call_id)
        else:
            assert not pending
            if isinstance(item, AIMessage):
                pending = {call["id"] for call in item.tool_calls}
    assert not pending


async def test_cold_load_of_compacted_state_with_many_old_checkpoints(
    store, postgres_dsn, monkeypatch
):
    runner, request, root, _, _ = await compaction_harness(
        store, postgres_dsn, monkeypatch
    )
    await runner.execute(request)
    config = {"configurable": {"thread_id": str(root.id)}}
    async with AsyncPostgresSaver.from_conn_string(postgres_dsn) as saver:
        started = perf_counter()
        before = await saver.aget_tuple(config)
        baseline_ms = (perf_counter() - started) * 1000
    async with store.database.connection() as connection:
        await connection.execute(
            "WITH latest AS (SELECT * FROM checkpoints WHERE thread_id=%s "
            "AND checkpoint_ns='' ORDER BY checkpoint_id DESC LIMIT 1) "
            "INSERT INTO checkpoints(thread_id,checkpoint_ns,checkpoint_id,"
            "parent_checkpoint_id,type,checkpoint,metadata) "
            "SELECT thread_id,checkpoint_ns,"
            "'00000000-0000-6000-8000-'||lpad(to_hex(n),12,'0'),"
            "parent_checkpoint_id,type,checkpoint,metadata "
            "FROM latest CROSS JOIN generate_series(1,10000) AS n",
            (str(root.id),),
        )
        await connection.execute("ANALYZE checkpoints")
        row = await (
            await connection.execute(
                "SELECT count(*),pg_total_relation_size('checkpoints') "
                "FROM checkpoints WHERE thread_id=%s",
                (str(root.id),),
            )
        ).fetchone()
    async with AsyncPostgresSaver.from_conn_string(postgres_dsn) as saver:
        started = perf_counter()
        after = await saver.aget_tuple(config)
        grown_ms = (perf_counter() - started) * 1000
    assert row[0] > 10000
    assert after.config == before.config
    assert after.checkpoint == before.checkpoint
    assert (
        after.checkpoint["channel_values"]["messages"][0].additional_kwargs["openlet"][
            "kind"
        ]
        == "compaction"
    )
    print(
        json.dumps(
            {
                "checkpoint_rows": row[0],
                "relation_bytes": row[1],
                "baseline_cold_ms": round(baseline_ms, 2),
                "grown_cold_ms": round(grown_ms, 2),
            }
        )
    )


async def compaction_harness(store, postgres_dsn, monkeypatch):
    # This fixture deliberately forces compaction with its single gather tool.
    store.models = store.models.model_copy(
        update={
            "models": [
                store.models.models[0].model_copy(
                    update={"context_window_tokens": 10000}
                )
            ]
        }
    )

    @tool
    async def gather(index: int) -> str:
        """Read a large public working result."""
        return (
            f"BEGIN_{index}"
            + "x" * 2400
            + f"MIDDLE_{index}"
            + "y" * 2400
            + f"END_{index}"
        )

    monkeypatch.setattr(runner_module, "build_tools", lambda context: [gather])
    first = call("gather", identity="step-0", index=0)
    first.content = [
        {"type": "reasoning", "text": "PRIVATE_REASONING_SENTINEL"},
        {"type": "text", "text": "Gathering public results"},
    ]
    first.additional_kwargs = {"reasoning_content": "PRIVATE_REASONING_SENTINEL"}
    model = RecordingModel(
        responses=[
            first,
            call("gather", identity="step-1", index=1),
            call("gather", identity="step-2", index=2),
            AIMessage(content="Short note"),
        ]
    )
    runner, request, root, workspaces = await harness(store, postgres_dsn, model)
    await store.receive(message(root, content="Keep all useful work"))
    return runner, request, root, model, workspaces


async def test_real_summary_checkpoint_public_card_and_complete_prefix(
    store, postgres_dsn, monkeypatch
):
    runner, request, root, model, _ = await compaction_harness(
        store, postgres_dsn, monkeypatch
    )
    original = store.append_activity

    async def verify_barrier(value):
        if value.kind in {
            "inbox_input",
            "assistant",
            "final_note",
            "compaction",
            "tool_call",
        }:
            committed = await saved_state(postgres_dsn, root.id)
            identities = {message.id for message in committed["messages"]}
            assert value.llm_message_id in identities
            if value.kind == "inbox_input":
                assert committed["inbox_cursor"] == value.data["cursor_to"]
            if value.kind == "compaction":
                assert committed["messages"][0].content == value.data["summary"]
        return await original(value)

    monkeypatch.setattr(store, "append_activity", verify_barrier)
    assert (await runner.execute(request)).outcome == "completed"
    assert len(model.calls) == 4 and len(model.summary_calls) == 1
    sent = "\n".join(message.content for message in model.summary_calls[0][1:])
    assert "PRIVATE_REASONING_SENTINEL" not in sent
    # More than the old 4000-token trim: the complete selected older prefix is present.
    for index in range(2):
        for position in ("BEGIN", "MIDDLE", "END"):
            assert f"{position}_{index}" in sent
    state = await saved_state(postgres_dsn, root.id)
    for position in ("BEGIN", "MIDDLE", "END"):
        assert f"{position}_2" in str(state["messages"])
    assert state["inbox_cursor"] == 1
    assert_complete_tool_groups(state["messages"])
    summary = state["messages"][0]
    assert (
        isinstance(summary, HumanMessage)
        and summary.additional_kwargs["openlet"]["kind"] == "compaction"
    )
    assert len(state["messages"]) < 8
    entries = await store.list_activity(root.id, root.id, limit=100)
    cards = [activity_entry(row) for row in entries]
    compaction = next(card for card in cards if card.kind == "compaction")
    assert compaction.data.summary == summary.content
    assert compaction.data.summary_message_id == summary.id
    assert summary.content == model.calls[-1][1].content
    assert [card.kind for card in cards].count("final_note") == 1
    assert "PRIVATE_REASONING_SENTINEL" not in json.dumps(
        [card.model_dump(mode="json") for card in cards]
    )
    assert "PRIVATE_REASONING_SENTINEL" not in str(state)
    assert len([card for card in cards if card.kind == "tool_result"]) == 3


@pytest.mark.parametrize("after_commit", [False, True])
async def test_summary_publisher_recovery_does_not_summarize_again(
    store, postgres_dsn, monkeypatch, after_commit
):
    runner, request, root, model, _ = await compaction_harness(
        store, postgres_dsn, monkeypatch
    )
    original = store.append_activity
    lost = False

    async def crash(value):
        nonlocal lost
        if value.kind == "compaction" and not lost:
            lost = True
            if after_commit:
                await original(value)
            raise RuntimeError("publisher process lost")
        return await original(value)

    monkeypatch.setattr(store, "append_activity", crash)
    with pytest.raises(RuntimeError, match="publisher process lost"):
        await runner.execute(request)
    state = await saved_state(postgres_dsn, root.id)
    summary_id = state["messages"][0].id
    assert len(model.summary_calls) == 1 and len(model.calls) == 3
    assert (await runner.execute(request)).outcome == "completed"
    assert len(model.summary_calls) == 1 and len(model.calls) == 4
    entries = await store.list_activity(root.id, root.id, limit=100)
    assert len([row for row in entries if row["kind"] == "compaction"]) == 1
    assert (
        next(row for row in entries if row["kind"] == "compaction")["data"][
            "summary_message_id"
        ]
        == summary_id
    )


async def test_exact_committed_input_replays_and_history_stays_scoped(
    store, postgres_dsn, monkeypatch
):
    model = RecordingModel(responses=[AIMessage(content="Short note")])
    runner, request, root, _ = await harness(store, postgres_dsn, model)
    first = message(root, content="Original input")
    await store.receive(first)
    original = store.append_activity
    lost = False

    async def crash(value):
        nonlocal lost
        if value.kind == "inbox_input" and not lost:
            lost = True
            raise RuntimeError("input publisher lost")
        return await original(value)

    monkeypatch.setattr(store, "append_activity", crash)
    with pytest.raises(RuntimeError, match="input publisher lost"):
        await runner.execute(request)
    second = message(root, content="Later input")
    await store.receive(second)
    assert (await runner.execute(request)).cursor == 1
    entries = await store.list_activity(root.id, root.id)
    card = activity_entry(entries[0])
    assert card.data.groups[0].message_ids == [first.id]
    assert second.id not in card.data.groups[0].message_ids
    assert card.data.cursor_to == 1
    context = SimpleNamespace(store=store, request=request)
    recent = await search_history(context, limit=1)
    assert len(recent["items"]) == 1 and recent["next_cursor"]
    older = await search_history(context, limit=1, cursor=recent["next_cursor"])
    assert older["items"][0]["id"] == str(card.id) and older["next_cursor"] is None
    detail = await read_history(context, str(card.id), start_line=1, max_lines=1)
    assert detail["total_lines"] > 1 and not detail["complete"]
    assert detail["entry"]["kind"] == "inbox_input"
    assert len((await search_history(context, query="Original input"))["items"]) == 1
    box = await active_box(store, root)
    foreign = SimpleNamespace(
        store=store, request=request.model_copy(update={"agent_id": box.letis[0].id})
    )
    assert (await search_history(foreign))["items"] == []
    with pytest.raises(AppError):
        await read_history(foreign, str(card.id))
    with pytest.raises(AppError):
        await store.get_activity(uuid7(), root.id, card.id)
    with pytest.raises(ValueError):
        await search_history(context, cursor="-1")


@pytest.mark.parametrize("crash_after_summary", [False, True])
async def test_pending_full_input_compacts_old_history_and_pins_snapshot(
    store, postgres_dsn, monkeypatch, crash_after_summary
):
    store.models = store.models.model_copy(
        update={
            "models": [
                store.models.models[0].model_copy(
                    update={"context_window_tokens": 10000}
                )
            ]
        }
    )
    monkeypatch.setattr(runner_module, "build_tools", lambda context: [])
    root = await active_root(store)
    box = await active_box(store, root)
    child = box.letis[0].id
    model = RecordingModel(
        responses=[
            AIMessage(content="A" * 2000),
            AIMessage(content="B" * 2000),
            AIMessage(content="Final note"),
        ]
    )
    runner, request, _, _ = await harness(
        store, postgres_dsn, model, root=root, target=child
    )
    for index in range(2):
        if index:
            request = RunInput(leta_id=root.id, agent_id=child, run_id=uuid7())
            await store.start_run(**request.model_dump())
        await store.receive(
            message(root, target=child, content=f"Earlier task {index}")
        )
        assert (await runner.execute(request)).outcome == "completed"
    assert not model.summary_calls
    old = await saved_state(postgres_dsn, child)
    from leta.runtime.middleware import count_context_tokens

    assert count_context_tokens(old["messages"]) < 6000
    request = RunInput(leta_id=root.id, agent_id=child, run_id=uuid7())
    await store.start_run(**request.model_dump())
    incoming = message(root, target=child, content="N" * 12000)
    await store.receive(incoming)
    later = message(root, target=child, content="Arrived during summarization")

    async def arrive_during_summary(messages):
        await store.receive(later)
        return AIMessage(
            content="Earlier tasks complete; preserve the new task in full."
        )

    model.on_summary = arrive_during_summary
    original = AsyncPostgresSaver.aput
    crashed = False

    async def save(self, config, checkpoint, metadata, new_versions):
        nonlocal crashed
        result = await original(self, config, checkpoint, metadata, new_versions)
        current = checkpoint["channel_values"].get("messages", [])
        if (
            crash_after_summary
            and not crashed
            and current
            and current[0].additional_kwargs.get("openlet", {}).get("kind")
            == "compaction"
        ):
            crashed = True
            raise RuntimeError("lost after summary checkpoint")
        return result

    monkeypatch.setattr(AsyncPostgresSaver, "aput", save)
    if crash_after_summary:
        with pytest.raises(RuntimeError, match="summary checkpoint"):
            await runner.execute(request)
        saved = await saved_state(postgres_dsn, child)
        assert saved["inbox_cursor"] == 2
        assert (
            saved["pending_input"].additional_kwargs["openlet"]["payload"]["cursor_to"]
            == 3
        )
        assert len(model.calls) == 2 and len(model.summary_calls) == 1
    assert (await runner.execute(request)).cursor == 3
    assert len(model.summary_calls) == 1 and len(model.calls) == 3
    assert "N" * 12000 not in str(model.summary_calls)
    batch = model.calls[-1][-1].additional_kwargs["openlet"]["payload"]
    assert [item["message_id"] for item in batch["items"]] == [str(incoming.id)]
    assert batch["items"][0]["content"] == "N" * 12000
    state = await saved_state(postgres_dsn, child)
    assert state["pending_input"] is None and state["inbox_cursor"] == 3
    assert (
        state["messages"][0].additional_kwargs["openlet"]["payload"][
            "retained_message_ids"
        ]
        == []
    )
    assert (await store.get_agent(root.id, child))["inbox_seq"] == 4


async def test_successive_compactions_and_reused_provider_ids_are_distinct_calls(
    store, postgres_dsn, monkeypatch
):
    runner, request, root, model, _ = await compaction_harness(
        store, postgres_dsn, monkeypatch
    )
    model.responses = [
        call("gather", identity="reused-call", index=0),
        *[call("gather", identity=f"middle-{i}", index=i) for i in range(1, 3)],
        call("gather", identity="reused-call", index=0),
        *[call("gather", identity=f"later-{i}", index=i) for i in range(4, 9)],
        AIMessage(content="Final note"),
    ]
    model.responses[0].id = model.responses[3].id = "reused-provider-message"
    assert (await runner.execute(request)).outcome == "completed"
    assert len(model.summary_calls) >= 2 and len(model.calls) == 10
    assert "Continuation summary" in str(model.summary_calls[-1])
    rows = await store.list_activity(root.id, root.id, limit=100)
    reused = [
        row
        for row in rows
        if row["kind"] == "tool_result" and row["tool_call_id"] == "reused-call"
    ]
    assert (
        len(reused) == 2 and reused[0]["llm_message_id"] != reused[1]["llm_message_id"]
    )
    assert len([row for row in rows if row["kind"] == "tool_result"]) == 9
    assert len([row for row in rows if row["kind"] == "compaction"]) == len(
        model.summary_calls
    )
    state = await saved_state(postgres_dsn, root.id)
    assert_complete_tool_groups(state["messages"])
    assert (
        len(
            [
                message
                for message in state["messages"]
                if message.additional_kwargs.get("openlet", {}).get("kind")
                == "compaction"
            ]
        )
        == 1
    )


async def test_image_replay_and_public_reference_use_resolved_path(
    store, postgres_dsn, monkeypatch
):
    reads = 0
    encoded = "aW1hZ2UtYnl0ZXMtc2VudGluZWw="

    async def image(self, path, start_line, max_lines):
        nonlocal reads
        reads += 1
        assert path == "/home/chart.png"
        # Another tool can change the shared session cwd during a file read.
        await self.session.shell("mkdir -p /home/other; cd /home/other")
        return [
            {"type": "text", "text": "An authorized image preview"},
            {
                "type": "image",
                "mime_type": "image/png",
                "base64": encoded,
                "provider_private": "PRIVATE_IMAGE_MARKER",
            },
        ]

    monkeypatch.setattr(FilesystemTools, "read_file", image)
    tools = runner_module.build_tools
    # Keep this image-recovery case independent of the growing global tool roster.
    monkeypatch.setattr(
        runner_module,
        "build_tools",
        lambda context: [item for item in tools(context) if item.name == "read_file"],
    )
    model = RecordingModel(
        responses=[call("read_file", path="chart.png"), AIMessage(content="Image read")]
    )
    runner, request, root, _ = await harness(store, postgres_dsn, model)
    await store.receive(message(root))
    original = store.append_activity
    lost = False

    async def crash(value):
        nonlocal lost
        row = await original(value)
        if value.kind == "tool_result" and not lost:
            lost = True
            raise RuntimeError("lost after image result commit")
        return row

    monkeypatch.setattr(store, "append_activity", crash)
    with pytest.raises(RuntimeError, match="image result commit"):
        await runner.execute(request)
    assert (await runner.execute(request)).outcome == "completed"
    assert reads == 1
    entries = await store.list_activity(root.id, root.id)
    row = next(row for row in entries if row["kind"] == "tool_result")
    entry = activity_entry(row)
    assert entry.data.result[-1].path == "/home/chart.png"
    assert encoded not in entry.model_dump_json()
    assert "PRIVATE_IMAGE_MARKER" not in str(row)
    assert encoded in str(model.calls[-1])
    context = SimpleNamespace(store=store, request=request)
    assert not (await search_history(context, query=encoded))["items"]


async def test_failure_before_summary_checkpoint_publishes_no_success_card(
    store, postgres_dsn, monkeypatch
):
    runner, request, root, model, _ = await compaction_harness(
        store, postgres_dsn, monkeypatch
    )
    original = AsyncPostgresSaver.aput
    lost = False

    async def save(self, config, checkpoint, metadata, new_versions):
        nonlocal lost
        current = checkpoint["channel_values"].get("messages", [])
        if (
            not lost
            and current
            and current[0].additional_kwargs.get("openlet", {}).get("kind")
            == "compaction"
        ):
            lost = True
            raise RuntimeError("lost before summary checkpoint")
        return await original(self, config, checkpoint, metadata, new_versions)

    monkeypatch.setattr(AsyncPostgresSaver, "aput", save)
    with pytest.raises(RuntimeError, match="before summary checkpoint"):
        await runner.execute(request)
    state = await saved_state(postgres_dsn, root.id)
    assert state["messages"][0].additional_kwargs["openlet"]["kind"] == "inbox_input"
    assert not any(
        row["kind"] == "compaction"
        for row in await store.list_activity(root.id, root.id, limit=100)
    )
    assert len(model.calls) == 3
    assert (await runner.execute(request)).outcome == "completed"
    assert len(model.calls) == 4
    cards = [
        row
        for row in await store.list_activity(root.id, root.id, limit=100)
        if row["kind"] == "compaction"
    ]
    assert len(cards) == 1
    final = await saved_state(postgres_dsn, root.id)
    assert cards[0]["data"]["summary_message_id"] == final["messages"][0].id
