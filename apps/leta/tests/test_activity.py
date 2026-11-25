from collections.abc import AsyncGenerator, Sequence
from typing import cast
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from leta import activity, events
from leta.config import Services
from leta.db import Pool, Row
from leta.filesystem.workspace import Filesystem
from leta.runtime import agent
from leta.runtime.tools import Context
from openlet_sdk.config import JSON


async def test_projection_keeps_error_status_and_image_reference_without_base64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = uuid4()
    context = Context(
        services=cast(Services, None),
        agent={"id": identity, "leta_id": identity},
        run_id=uuid4(),
        filesystem=cast(Filesystem, None),
    )
    captured: list[tuple[str, str, JSON]] = []

    async def record(
        db: object,
        agent_id: UUID,
        run_id: UUID,
        entries: Sequence[tuple[str, str, JSON]],
    ) -> list[tuple[UUID, str, JSON]]:
        captured.extend(entries)
        return [(uuid4(), kind, body) for _, kind, body in entries]

    async def publish(
        redis: object, root: UUID, entries: Sequence[events.Event]
    ) -> bool:
        return True

    from types import SimpleNamespace

    services = cast(Services, SimpleNamespace(db=None, redis=None))
    monkeypatch.setattr(agent, "record_batch", record)
    monkeypatch.setattr(agent.events, "publish_batch", publish)
    messages: list[BaseMessage] = [
        AIMessage(
            content="",
            id="model",
            tool_calls=[
                {
                    "name": "file_read",
                    "id": "image",
                    "args": {"path": "~/diagram.png"},
                }
            ],
        ),
        ToolMessage(
            id="image-result",
            name="file_read",
            tool_call_id="image",
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,private"},
                }
            ],
            artifact="~/diagram.png",
        ),
        ToolMessage(
            id="error-result",
            name="execute",
            tool_call_id="error",
            content="Timeout",
            status="error",
        ),
    ]
    await agent.project(services, context, messages)
    image = cast(dict[str, JSON], captured[1][2])
    error = cast(dict[str, JSON], captured[2][2])
    assert image["file"] == {"path": "~/diagram.png", "kind": "image"}
    assert image["status"] == "success" and error["status"] == "error"
    assert "base64" not in str(captured)


async def test_activity_read_entry_formats_notes_pairs_and_wraps_oversized_lines() -> (
    None
):
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone

    from leta.output import BYTE_BUDGET

    run = uuid4()
    ts = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)
    entries: dict[int, Row] = {
        1: {
            "id": uuid4(),
            "run_id": run,
            "seq": 1,
            "kind": "final_note",
            "created_at": ts,
            "payload": {"text": "Ready to reply.", "reasoning": "Checked Q4 file."},
        },
        2: {
            "id": uuid4(),
            "run_id": run,
            "seq": 2,
            "kind": "tool_call",
            "created_at": ts,
            "payload": {
                "tool_call_id": "call-1",
                "name": "execute",
                "args": {"command": "python run.py"},
            },
        },
        3: {
            "id": uuid4(),
            "run_id": run,
            "seq": 3,
            "kind": "tool_result",
            "created_at": ts,
            "payload": {
                "tool_call_id": "call-1",
                "name": "execute",
                "status": "error",
                "file": {"path": "~/diagram.png", "kind": "image"},
                "text": "x" * (BYTE_BUDGET + 50),
            },
        },
    }

    class Cursor:
        def __init__(self, row: Row | None) -> None:
            self.row = row

        async def fetchone(self) -> Row | None:
            return self.row

    class Conn:
        async def execute(self, query: str, params: tuple[object, ...]) -> Cursor:
            if "WHERE agent_id=%s AND seq=%s" in query:
                return Cursor(entries.get(cast(int, params[1])))
            target_kind = params[2]
            for row in entries.values():
                if row["kind"] == target_kind:
                    return Cursor({"seq": row["seq"], "payload": row["payload"]})
            return Cursor(None)

    class DB:
        @asynccontextmanager
        async def connection(self) -> AsyncGenerator[Conn]:
            yield Conn()

    db = cast(Pool, DB())
    note_text, note_data = await activity.read_entry(db, uuid4(), 1)
    assert "Reasoning:\nChecked Q4 file." in note_text
    assert "Note:\nReady to reply." in note_text
    assert note_data["kind"] == "final_note"

    call_text, call_data = await activity.read_entry(db, uuid4(), 2)
    assert "Result entry: 3 | status=error" in call_text
    assert '"command": "python run.py"' in call_text
    assert call_data["paired_entry"] == 3

    res_text, res_data = await activity.read_entry(db, uuid4(), 3)
    assert "Entry 3 | tool_result | execute | error" in res_text
    assert 'Call entry: 2 | execute({"command":"python run.py"})' in res_text
    assert "File: ~/diagram.png (image)" in res_text
    assert "[More content. Continue with start_line=" in res_text
    assert "Use execute with jq" not in res_text
    assert res_data["paired_entry"] == 2 and res_data["status"] == "error"

    entries[4] = {
        "id": uuid4(),
        "run_id": run,
        "seq": 4,
        "kind": "tool_result",
        "created_at": ts,
        "payload": {
            "tool_call_id": "call-img",
            "name": "file_read",
            "status": "success",
            "file": {"path": "~/diagram.png", "kind": "image"},
            "text": "",
        },
    }
    img_text, _ = await activity.read_entry(db, uuid4(), 4)
    assert "File: ~/diagram.png (image)" in img_text
    assert "Payload:" not in img_text and "Output:\n(empty output)" in img_text
