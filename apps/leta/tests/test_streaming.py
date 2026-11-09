import json
from uuid import uuid7

import pytest

from leta.streaming import Envelope, coalesce_events, cursor, public_event, sse


def envelope(root, agent, run, event):
    return Envelope(leta_id=root, agent_id=agent, run_id=run, event=event).model_dump(
        mode="json"
    )


def test_coalescing_preserves_agent_run_block_order_boundaries_and_utf8():
    root, child, run, other_run = uuid7(), uuid7(), uuid7(), uuid7()
    events = [
        (
            root,
            run,
            {"type": "TEXT_MESSAGE_START", "messageId": "m", "role": "assistant"},
        ),
        (
            root,
            run,
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "Xin "},
        ),
        (
            root,
            run,
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "chào"},
        ),
        (
            child,
            run,
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "child"},
        ),
        (
            child,
            other_run,
            {
                "type": "TEXT_MESSAGE_CONTENT",
                "messageId": "m",
                "delta": "different run",
            },
        ),
        (root, run, {"type": "CUSTOM", "name": "activity", "value": {"id": "entry"}}),
        (
            root,
            run,
            {"type": "TOOL_CALL_START", "toolCallId": "t", "toolCallName": "read_file"},
        ),
        (root, run, {"type": "TOOL_CALL_ARGS", "toolCallId": "t", "delta": '{"path":'}),
        (root, run, {"type": "TOOL_CALL_ARGS", "toolCallId": "t", "delta": '"/a"}'}),
        (root, run, {"type": "TOOL_CALL_END", "toolCallId": "t"}),
        (root, run, {"type": "TEXT_MESSAGE_END", "messageId": "m"}),
    ]
    rows = [(f"1-{i}", envelope(root, a, r, e)) for i, (a, r, e) in enumerate(events)]
    merged = coalesce_events(rows)
    assert len(merged) == 9
    assert merged[1][0] == "1-2" and merged[1][1]["event"]["delta"] == "Xin chào"
    assert merged[-3][0] == "1-8"
    assert json.loads(merged[-3][1]["event"]["delta"]) == {"path": "/a"}
    assert [e["event"]["type"] for _, e in merged] == [
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_CONTENT",
        "CUSTOM",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "TEXT_MESSAGE_END",
    ]
    assert len(coalesce_events(rows, max_bytes=8)) == 11  # 'Xin chào' is 9 UTF-8 bytes.
    assert sse(*merged[1]).startswith(b"id: 1-2\ndata: ")


@pytest.mark.parametrize(
    "value", ["", "0", "1-", "-1-0", "1-2\ndata: injected", "18446744073709551616-0"]
)
def test_invalid_stream_cursors(value):
    with pytest.raises(ValueError):
        cursor(value)


def test_private_provider_and_reasoning_events_never_enter_public_stream():
    event = public_event(
        {
            "type": "TEXT_MESSAGE_CONTENT",
            "messageId": "m",
            "delta": "Public",
            "rawEvent": {"private_provider_payload": "hidden"},
        }
    )
    assert "rawEvent" not in event and event["delta"] == "Public"
    with pytest.raises(ValueError):
        public_event(
            {"type": "REASONING_MESSAGE_CONTENT", "messageId": "m", "delta": "Hidden"}
        )


async def test_slow_sse_sender_closes_body_iterator(monkeypatch):
    import asyncio

    from starlette.requests import ClientDisconnect

    from leta.http import events

    closed = asyncio.Event()

    async def body():
        try:
            yield b"data: provisional\n\n"
        finally:
            closed.set()

    async def send(message):
        if message["type"] == "http.response.body":
            await asyncio.Event().wait()

    async def receive():
        await asyncio.Event().wait()

    monkeypatch.setattr(events, "SEND_SECONDS", 0.01)
    with pytest.raises(ClientDisconnect):
        await events.EventResponse(body())(
            {"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send
        )
    assert closed.is_set()
