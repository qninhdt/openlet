"""Real saver and Redis prove public callback identity and failure boundaries."""

import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from redis.asyncio import Redis
from test_runtime import RecordingModel, call, harness, saved_state
from test_store_integration import message

from leta.runtime.events import ModelEvents
from leta.streaming import Publisher, keys, read_events

pytestmark = pytest.mark.integration


class StreamingModel(RecordingModel):
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        response = await super()._agenerate(messages, stop, run_manager, **kwargs)
        output = response.generations[0].message
        # Match the installed ChatOpenRouter._astream callback contract.
        for content in ([{"type": "reasoning", "text": "PRIVATE"}], "Public ", "note"):
            await run_manager.on_llm_new_token(
                "ignored raw token",
                chunk=ChatGenerationChunk(message=AIMessageChunk(content=content)),
            )
        for tool in output.tool_calls:
            arguments = json.dumps(tool["args"])
            for part in (
                {"index": 0, "id": tool["id"], "name": tool["name"], "args": "{"},
                {"index": 0, "args": arguments[1:]},
            ):
                await run_manager.on_llm_new_token(
                    "",
                    chunk=ChatGenerationChunk(
                        message=AIMessageChunk(content="", tool_call_chunks=[part])
                    ),
                )
        return response


async def test_runtime_stream_matches_checkpoint_history_and_completes_once(
    store, postgres_dsn, redis_url
):
    model = StreamingModel(
        responses=[
            call("send_message", to="owner", content="Actual owner reply"),
            AIMessage(content="Public note"),
        ]
    )
    runner, request, root, _ = await harness(store, postgres_dsn, model)
    await store.receive(message(root))
    async with Redis.from_url(redis_url) as redis:
        runner.publisher = Publisher(redis, store)
        assert (await runner.execute(request)).outcome == "completed"
        rows = await read_events(redis, root.id, "0-0", count=200)
        saved = await saved_state(postgres_dsn, root.id)
        assistant = [m for m in saved["messages"] if isinstance(m, AIMessage)]
        events = [e["event"] for _, e in rows]
        assert (
            events[0]["type"] == "RUN_STARTED" and events[-1]["type"] == "RUN_FINISHED"
        )
        starts = [e["messageId"] for e in events if e["type"] == "TEXT_MESSAGE_START"]
        assert starts == [m.id for m in assistant]
        calls = [e for e in events if e["type"] == "TOOL_CALL_START"]
        assert calls[0]["toolCallId"] == assistant[0].tool_calls[0]["id"]
        assert calls[0]["parentMessageId"] == assistant[0].id
        assert "PRIVATE" not in str(events) and "ignored raw token" not in str(events)
        entries = [
            e["value"]
            for e in events
            if e["type"] == "CUSTOM" and e["name"] == "activity"
        ]
        assert [e["kind"] for e in entries] == [
            "inbox_input",
            "assistant",
            "tool_call",
            "tool_result",
            "final_note",
        ]
        assert entries[-1]["data"]["llm_message_id"] == starts[-1]
        assert "message" not in next(
            e["data"] for e in entries if e["kind"] == "tool_result"
        )
        references = [e["value"] for e in events if e.get("name") == "resource"]
        assert len(references) == 1 and references[0]["kind"] == "message"
        from uuid import UUID

        sent = await store.get_message(root.id, UUID(references[0]["id"]))
        assert sent["content"] == "Actual owner reply"
        assert sent["recipient_user_id"] == root.created_by_user_id
        arguments = "".join(e["delta"] for e in events if e["type"] == "TOOL_CALL_ARGS")
        assert json.loads(arguments) == {"to": "owner", "content": "Actual owner reply"}
        count = await redis.xlen(keys(root.id)[0])
        await runner.execute(request)
        assert await redis.xlen(keys(root.id)[0]) == count


async def test_runtime_redis_failure_still_checkpoints_and_does_not_repeat_tool(
    store, postgres_dsn, redis_url
):
    from redis.exceptions import ConnectionError

    attempts = 0

    async def unavailable(*args):
        nonlocal attempts
        attempts += 1
        raise ConnectionError("Redis unavailable")

    model = RecordingModel(
        responses=[
            call("run_shell", command="echo once > /home/effect"),
            AIMessage(content="Done"),
        ]
    )
    runner, request, root, workspace = await harness(store, postgres_dsn, model)
    await store.receive(message(root))
    runner.publisher = Publisher(SimpleNamespace(eval=unavailable), store)
    assert (await runner.execute(request)).outcome == "completed"
    assert attempts == 1 and len(model.calls) == 2
    state = await saved_state(postgres_dsn, root.id)
    assert state["messages"][-1].content == "Done"
    assert workspace.opened == workspace.closed
    await runner.execute(request)
    assert attempts == 1


async def test_summary_callbacks_and_cancelled_blocks_are_not_public():
    published = []

    async def emit(event):
        published.append(event)
        return True

    callback = ModelEvents(SimpleNamespace(emit=emit))
    chunk = ChatGenerationChunk(message=AIMessageChunk(content="Summary private input"))
    await callback.on_llm_new_token("", chunk=chunk)
    assert published == []
    callback.begin("stable-message")
    await callback.on_llm_new_token(
        "", chunk=ChatGenerationChunk(message=AIMessageChunk(content="Visible"))
    )
    assert [e["type"] for e in published] == [
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
    ]
    assert all(e["messageId"] == "stable-message" for e in published)
    assert not any(e["type"] == "TEXT_MESSAGE_END" for e in published)
