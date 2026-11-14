from collections.abc import Sequence
from typing import cast
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from leta import events
from leta.config import Services
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
