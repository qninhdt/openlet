import asyncio
import json
from types import SimpleNamespace
from uuid import uuid7

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from openlet.errors import AppError
from test_runtime import RecordingModel, call, harness
from test_store_integration import active_box, active_root, message

from leta.domain import LetiSpec
from leta.runtime.messaging import (
    list_inbox,
    messaging_roster,
    read_inbox,
    send_message,
)
from leta.runtime.tools import build_tools
from leta.temporal.bridges import control_agent
from leta.temporal.types import AgentControl, RunInput
from leta.worker import agent_workers

pytestmark = pytest.mark.integration


async def context(store, root, agent_id, client):
    return SimpleNamespace(
        store=store,
        root=await store.get_agent(root.id, root.id),
        agent=await store.get_agent(root.id, agent_id),
        request=RunInput(leta_id=root.id, agent_id=agent_id, run_id=uuid7()),
        temporal=client,
        events=None,
    )


async def stop_agents(client, ids):
    for identity in ids:
        await control_agent(client, identity, AgentControl(action="stop"))
        await client.get_workflow_handle(f"agent/{identity}").result()


async def test_real_box_peer_and_parent_delivery_keep_box_address_and_true_sender(
    store, postgres_dsn, persistent_temporal
):
    root = await active_root(store)
    box = await active_box(store, root)
    representative, peer = (item.id for item in box.letis)
    client = persistent_temporal
    async with store.transaction() as cursor:
        await cursor.execute("UPDATE agents SET paused=true WHERE id=%s", (root.id,))
    model = RecordingModel(responses=[AIMessage(content="Unexpected model call")])
    runner, _, _, _ = await harness(
        store, postgres_dsn, model, root=root, client=client
    )
    parent = await context(store, root, root.id, client)
    rep = await context(store, root, representative, client)
    child = await context(store, root, peer, client)
    async with agent_workers(client, store, runner.run_agent), asyncio.timeout(30):
        try:
            work_id = uuid7()
            await send_message(parent, work_id, box.name, "Research this")
            await send_message(parent, work_id, str(box.id), "Research this")
            inbox = await store.list_inbox(root.id, representative)
            assert len(inbox) == 1 and inbox[0]["id"] == work_id
            assert inbox[0]["source_type"] == "agent"
            assert inbox[0]["reply_to"] == {"type": "box", "id": str(box.id)}
            to_peer = uuid7()
            await send_message(rep, to_peer, box.letis[1].name, "Write a draft")
            peer_reply = uuid7()
            await send_message(
                child, peer_reply, str(representative), "Draft", str(to_peer)
            )
            result_id = uuid7()
            await send_message(rep, result_id, "parent", "Done", str(work_id))
            result = await store.get_message(root.id, result_id)
            assert result["recipient_agent_id"] == root.id
            assert result["sender_agent_id"] == representative
            assert result["source_type"] == "box" and result["source_id"] == str(box.id)
            assert result["reply_to"] == {"type": "box", "id": str(box.id)}
            assert result["conversation_key"] == f"box:{box.id}"
            await send_message(
                parent, uuid7(), str(box.id), "One more thing", str(result_id)
            )
            with pytest.raises(ValueError, match="allowed roster"):
                await send_message(child, uuid7(), "parent", "Bypass representative")
            with pytest.raises(ValueError, match="allowed roster"):
                await send_message(rep, uuid7(), "owner", "Direct child chat")
            with pytest.raises(AppError, match="original address"):
                await send_message(rep, uuid7(), str(peer), "Wrong reply", str(work_id))
            assert model.calls == []
        finally:
            await stop_agents(client, [root.id, representative, peer])


async def test_single_agent_box_has_same_route_and_unlinked_agents_stay_unreachable(
    store, postgres_dsn, persistent_temporal
):
    root = await active_root(store)
    box = await active_box(
        store,
        root,
        letis=[LetiSpec(id=uuid7(), name="Solo", system_prompt="Work")],
        edges=[],
        representative="Solo",
    )
    disconnected = await active_box(
        store,
        root,
        name="Other team",
        letis=[
            LetiSpec(id=uuid7(), name="A", system_prompt="Work"),
            LetiSpec(id=uuid7(), name="B", system_prompt="Work"),
        ],
        edges=[],
        representative="A",
    )
    client = persistent_temporal
    async with store.transaction() as cursor:
        await cursor.execute("UPDATE agents SET paused=true WHERE id=%s", (root.id,))
    runner, _, _, _ = await harness(
        store, postgres_dsn, RecordingModel(responses=[]), root=root, client=client
    )
    parent = await context(store, root, root.id, client)
    solo = await context(store, root, box.letis[0].id, client)
    isolated = await context(store, root, disconnected.letis[1].id, client)
    assert await messaging_roster(isolated) == []
    async with agent_workers(client, store, runner.run_agent), asyncio.timeout(30):
        try:
            task_id = uuid7()
            await send_message(parent, task_id, str(box.id), "Work")
            await send_message(solo, uuid7(), str(box.id), "Result", str(task_id))
            for target in (root.id, disconnected.letis[0].id, root.created_by_user_id):
                with pytest.raises(ValueError):
                    await send_message(solo, uuid7(), str(target), "Forbidden route")
        finally:
            await stop_agents(client, [root.id, box.letis[0].id])


async def test_send_tool_reuses_committed_message_after_lost_result_and_hides_runtime(
    store, postgres_dsn, monkeypatch
):
    root = await active_root(store)
    incoming = message(
        root,
        source={"type": "user", "id": str(root.created_by_user_id), "label": "Owner"},
        reply_to={"type": "user", "id": root.created_by_user_id},
    )
    await store.receive(incoming)
    model = RecordingModel(
        responses=[
            call(
                "send_message",
                to="owner",
                content="Actual reply",
                in_reply_to=str(incoming.id),
            ),
            AIMessage(content="Reply sent"),
        ]
    )
    runner, request, _, _ = await harness(store, postgres_dsn, model, root=root)
    schema_context = await context(store, root, root.id, None)
    schema_context.workspace = SimpleNamespace(session=None)
    schema = next(
        item for item in build_tools(schema_context) if item.name == "send_message"
    ).tool_call_schema.model_json_schema()
    assert set(schema["properties"]) == {"to", "content", "in_reply_to"}
    original = store.append_activity
    lost = False

    async def crash(value):
        nonlocal lost
        if value.kind == "tool_result" and not lost:
            lost = True
            raise RuntimeError("lost before message result checkpoint")
        return await original(value)

    monkeypatch.setattr(store, "append_activity", crash)
    with pytest.raises(RuntimeError, match="message result checkpoint"):
        await runner.execute(request)
    assert (await runner.execute(request)).outcome == "completed"
    chat = await store.list_conversation(root.id, "owner")
    received = [row for row in chat if row["recipient_user_id"]]
    assert len(received) == 1 and received[0]["content"] == "Actual reply"
    assert received[0]["seq"] is None
    assert len(model.calls) == 2
    entries = await store.list_activity(root.id, root.id)
    assert sum(row["kind"] == "tool_result" for row in entries) == 1
    assert [row for row in entries if row["kind"] == "final_note"][0]["data"][
        "content"
    ] == [{"type": "text", "text": "Reply sent"}]


async def test_reply_cannot_read_foreign_or_nonreplyable_input(store):
    root, foreign = await active_root(store), await active_root(store)
    own = await context(store, root, root.id, None)
    invalid = message(root)
    outsider = message(foreign)
    await store.receive(invalid)
    await store.receive(outsider)
    with pytest.raises(AppError, match="not replyable"):
        await send_message(own, uuid7(), "owner", "No reply address", str(invalid.id))
    with pytest.raises(AppError, match="not found"):
        await send_message(own, uuid7(), "owner", "Foreign", str(outsider.id))
    # A box can share the reserved owner's display alias; canonical IDs disambiguate.
    await active_box(store, root, name="owner")
    with pytest.raises(ValueError, match="ambiguous"):
        await send_message(own, uuid7(), "owner", "Ambiguous")
    await send_message(own, uuid7(), str(root.created_by_user_id), "Canonical target")


async def test_send_returns_after_inbox_commit_while_recipient_model_is_busy(
    store, postgres_dsn, persistent_temporal
):
    root = await active_root(store)
    box = await active_box(store, root)
    client = persistent_temporal
    entered = asyncio.Event()

    async def hold(messages, number):
        entered.set()
        await asyncio.Event().wait()

    model = RecordingModel(responses=[AIMessage(content="Note")], on_call=hold)
    runner, _, _, workspaces = await harness(
        store, postgres_dsn, model, root=root, client=client
    )
    parent = await context(store, root, root.id, client)
    async with agent_workers(client, store, runner.run_agent), asyncio.timeout(30):
        try:
            await send_message(parent, uuid7(), str(box.id), "First work")
            await entered.wait()
            second = uuid7()
            assert (await send_message(parent, second, str(box.id), "New work"))[
                "status"
            ] == "sent"
            assert [
                row["id"] for row in await store.list_inbox(root.id, box.letis[0].id)
            ][-1] == second
            assert len(model.calls) == 1
        finally:
            await stop_agents(client, [box.letis[0].id])
    assert workspaces.opened == workspaces.closed == 1


async def test_inbox_tools_group_generic_sources_and_mark_only_returned_details(store):
    root = await active_root(store)
    own = await context(store, root, root.id, None)
    own.workspace = SimpleNamespace(session=None)
    user_source = {
        "type": "user",
        "id": str(root.created_by_user_id),
        "label": "Owner",
    }
    sent = []
    for index in range(3):
        item = message(
            root,
            source=user_source,
            content=f"Owner task {index}",
            reply_to={"type": "user", "id": root.created_by_user_id},
        )
        await store.receive(item)
        sent.append(item)
    notice = message(
        root,
        source={"type": "future.integration", "id": "source-1", "label": "A source"},
        conversation_key=None,
        content="Information only",
    )
    await store.receive(notice)
    toolset = {item.name: item for item in build_tools(own)}
    list_tool = toolset["list_inbox"]
    assert "from" in list_tool.tool_call_schema["properties"]
    filtered = await list_tool.ainvoke({"from": "owner", "limit": 1})
    group = filtered["items"][0]
    assert group["conversation_id"] == "owner"
    assert group["unread_count"] == group["message_count"] == 3
    assert group["preview"] == "Owner task 2"
    assert len((await list_inbox(own))["items"]) == 2
    first = await read_inbox(own, "owner", limit=1)
    assert first["items"][0]["message_id"] == str(sent[0].id)
    assert first["next_cursor"]
    stored = await store.list_inbox(root.id, root.id, conversation="owner")
    assert [row["read_at"] is not None for row in stored] == [True, False, False]
    second = await read_inbox(own, "owner", limit=1, cursor=first["next_cursor"])
    assert second["items"][0]["message_id"] == str(sent[1].id)
    assert (await list_inbox(own, from_="owner"))["items"][0]["unread_count"] == 1
    assert (await store.bootstrap_agent(root.id, root.id))["cursor"] == 0
    assert (await store.get_agent(root.id, root.id))["inbox_seq"] == 4
    newest = await list_inbox(own, limit=1)
    assert newest["next_cursor"]
    source_group = newest["items"][0]
    assert source_group["source"]["type"] == "future.integration"
    assert source_group["reply_to"] is None and source_group["conversation_id"]
    detail = await read_inbox(own, source_group["conversation_id"])
    assert detail["items"][0]["message_id"] == str(notice.id)
    assert detail["items"][0]["content"] == "Information only"
    older = await list_inbox(own, cursor=newest["next_cursor"])
    assert [item["conversation_id"] for item in older["items"]] == ["owner"]
    foreign = await active_root(store)
    foreign_context = await context(store, foreign, foreign.id, None)
    assert (await read_inbox(foreign_context, "owner"))["items"] == []
    box = await active_box(store, root)
    child = await context(store, root, box.letis[0].id, None)
    child.workspace = SimpleNamespace(session=None)
    assert not {"list_inbox", "read_inbox"} & {item.name for item in build_tools(child)}
    with pytest.raises(AppError, match="no inbox tools"):
        await read_inbox(child, "owner")
    for cursor in ("-1", "abc", "0"):
        with pytest.raises(ValueError, match="cursor"):
            await list_inbox(own, cursor=cursor)


@pytest.mark.parametrize("after_commit", [False, True])
async def test_read_marker_and_saved_tool_result_commit_together(
    store, postgres_dsn, monkeypatch, after_commit
):
    root = await active_root(store)
    incoming = [message(root, content=f"Details {index}") for index in range(2)]
    for item in incoming:
        await store.receive(item)
    model = RecordingModel(
        responses=[
            call("read_inbox", conversation_id="owner", limit=1),
            AIMessage(content="Details read"),
        ]
    )
    runner, request, _, _ = await harness(store, postgres_dsn, model, root=root)
    original = store.append_activity
    lost = False

    async def crash(value, **kwargs):
        nonlocal lost
        if value.kind == "tool_result" and not lost:
            lost = True
            if after_commit:
                await original(value, **kwargs)
            raise RuntimeError("read result process lost")
        return await original(value, **kwargs)

    monkeypatch.setattr(store, "append_activity", crash)
    with pytest.raises(RuntimeError, match="read result process lost"):
        await runner.execute(request)
    before = await store.list_inbox(root.id, root.id)
    assert [row["read_at"] is not None for row in before] == [after_commit, False]
    assert (await runner.execute(request)).outcome == "completed"
    selected = next(item for item in model.calls[-1] if isinstance(item, ToolMessage))
    assert json.loads(selected.content)["items"][0]["message_id"] == str(incoming[0].id)
    after = await store.list_inbox(root.id, root.id)
    assert [row["read_at"] is not None for row in after] == [True, False]


async def test_committed_send_recovers_after_root_rename_and_box_archive(store):
    from leta.domain import AgentConfiguration, NewMessage

    root = await active_root(store)
    parent = await context(store, root, root.id, None)
    owner_message = uuid7()
    first = await send_message(parent, owner_message, "owner", "Sent")
    await store.configure_agent(root.id, root.id, AgentConfiguration(name="New name"))
    parent.agent = await store.get_agent(root.id, root.id)
    assert await send_message(parent, owner_message, "owner", "Sent") == first
    with pytest.raises(AppError, match="different content"):
        await send_message(parent, owner_message, "owner", "Changed")
    box = await active_box(store, root)
    identity = uuid7()
    await store.receive(
        NewMessage(
            id=identity,
            leta_id=root.id,
            sender_agent_id=root.id,
            recipient_agent_id=box.letis[0].id,
            source={"type": "agent", "id": str(root.id), "label": "New name"},
            reply_to={"type": "box", "id": box.id},
            conversation_key=f"box:{box.id}",
            content="Work",
        )
    )
    await store.begin_delete(root.id, box.id)
    await store.archive(root.id, box.id)
    result = await send_message(parent, identity, box.name, "Work")
    assert result["status"] == "sent" and result["to"]["id"] == str(box.id)
    with pytest.raises(AppError, match="different recipient"):
        await send_message(parent, identity, "owner", "Work")
    assert len(await store.list_inbox(root.id, box.letis[0].id)) == 1
