import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from leta.events import event, fold
from leta.runtime.agent import protected
from leta.schedules import Timing, native_spec, normalize


async def test_cancellation_waits_for_boundary_to_settle() -> None:
    entered, finish = asyncio.Event(), asyncio.Event()
    durable = False

    async def boundary() -> None:
        nonlocal durable
        entered.set()
        await finish.wait()
        durable = True

    task = asyncio.create_task(protected(boundary()))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert durable


def test_stream_folding_preserves_agent_scope_and_terminal_events() -> None:
    agent, other, run = uuid4(), uuid4(), uuid4()
    first = event("TEXT_MESSAGE_CONTENT", agent, run, messageId="text", delta="first")
    second = event(
        "TEXT_MESSAGE_CONTENT", agent, run, messageId="text", delta=" second"
    )
    child = event("TEXT_MESSAGE_CONTENT", other, run, messageId="text", delta="child")
    end = event("TEXT_MESSAGE_END", agent, run, messageId="text")
    result = fold([("1-0", first), ("2-0", second), ("3-0", child), ("4-0", end)])
    assert [cursor for cursor, _ in result] == ["2-0", "3-0", "4-0"]
    assert result[0][1]["delta"] == "first second"
    assert result[1][1]["metadata"] != result[0][1]["metadata"]
    assert result[2][1]["type"] == "TEXT_MESSAGE_END"


def test_relative_schedule_uses_workflow_time_and_native_spec() -> None:
    now = datetime(2026, 1, 2, 3, 4, 5, 123, tzinfo=timezone.utc)
    result = normalize(Timing(after_seconds=10), now)
    assert result is not None
    kind, fields = result
    expected = (now + timedelta(seconds=10)).replace(microsecond=0)
    assert fields["at"] == expected.isoformat()
    spec = native_spec(kind, fields)
    assert spec.calendars[0].second[0].start == expected.second
    assert spec.calendars[0].year[0].start == expected.year
    with pytest.raises(ValueError, match="one timing"):
        Timing(at=now, after_seconds=10)


async def test_shell_capture_is_bounded_and_redirection_remains_complete() -> None:
    from leta.filesystem.workspace import shell
    from mirage import Mount, MountMode, Workspace
    from mirage.vfs.ram import RAMVFS

    workspace = Workspace(
        {"/data": Mount(vfs=RAMVFS(), mode=MountMode.WRITE)}, network=False
    )
    try:
        session = await workspace.session("tools")
        result = await shell(session, "seq 1 10000 | tee /data/full.txt", cwd="/")
        assert result["truncated"] is True
        assert len(str(result["stdout"]).encode()) <= 16000
        assert (await session.vfs.read("/data/full.txt")).endswith(b"10000\n")
    finally:
        await workspace.close()


async def test_execution_reuses_client_and_native_compaction_preserves_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path
    from types import SimpleNamespace
    from typing import cast

    import yaml
    from langchain_core.messages import (
        AIMessage,
        AnyMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )
    from langchain_core.runnables import RunnableLambda
    from langchain_litellm import ChatLiteLLM
    from langfuse.api.prompts.types.prompt import Prompt_Text
    from langfuse.model import TextPromptClient
    from langgraph.runtime import Runtime
    from leta.config import Services
    from leta.db import Row
    from leta.models import Model, Models
    from leta.runtime.agent import ExecutionModel
    from leta.runtime.tools import Context, exec_shell
    from openlet_sdk.config import Config, ReasoningEffort
    from openlet_sdk.inference import InferenceSettings

    class Catalog:
        async def get(self, model: str, effort: ReasoningEffort) -> Model:
            return Model(
                model_id=model,
                reasoning_efforts=[None, "low"],
                context_window_tokens=24000,
                max_output_tokens=4096,
            )

    def prompt(text: str) -> TextPromptClient:
        return TextPromptClient(
            Prompt_Text(
                name="fixture", version=1, prompt=text, labels=[], tags=[], config={}
            )
        )

    config = cast(
        Config, yaml.safe_load(Path("infra/config/openlet.example.yaml").read_text())
    )
    monkeypatch.setenv("LITELLM_MASTER_KEY", "fixture")
    services = cast(
        Services, SimpleNamespace(config=config, models=cast(Models, Catalog()))
    )
    runtime = ExecutionModel(
        services,
        InferenceSettings(model="chat", max_tokens=1024),
        prompt("Product rules\nYour instructions\n{{agent_instructions}}"),
        prompt("Summarize only."),
        [exec_shell],
        "",
    )
    agent: Row = {
        "model_id": None,
        "reasoning_effort": None,
        "root_model_id": None,
        "root_reasoning_effort": None,
        "system_prompt": "Do useful work.",
    }
    await runtime.refresh(agent)
    original, middleware = runtime.chat, runtime.summary
    await runtime.refresh(agent)
    assert runtime.chat is original and runtime.summary is middleware
    agent["system_prompt"] = "Review evidence."
    await runtime.refresh(agent)
    assert runtime.chat is original and runtime.summary is not middleware
    assert runtime.system.endswith("Review evidence.")
    agent.update(model_id="another", reasoning_effort="low")
    await runtime.refresh(agent)
    assert runtime.chat is not original

    received: list[AnyMessage] = []
    binding: dict[str, object] = {}

    async def summarize(messages: list[AnyMessage]) -> AIMessage:
        received.extend(messages)
        return AIMessage(content="Keep the goal and confirmed effects.")

    def bind(
        self: ChatLiteLLM, tools: object, **kwargs: object
    ) -> RunnableLambda[list[AnyMessage], AIMessage]:
        binding.update(tools=tools, **kwargs)
        return RunnableLambda(summarize)

    monkeypatch.setattr(ChatLiteLLM, "bind_tools", bind)
    messages: list[AnyMessage] = []
    for index in range(6):
        messages.extend(
            [
                HumanMessage(content=("source " * 2000), id=f"input-{index}"),
                AIMessage(
                    content="",
                    id=f"call-{index}",
                    tool_calls=[
                        {
                            "id": str(index),
                            "name": "exec_shell",
                            "args": {"command": "pwd"},
                        }
                    ],
                ),
                ToolMessage(
                    content="/home", id=f"result-{index}", tool_call_id=str(index)
                ),
            ]
        )
    messages.append(HumanMessage(content="Please finish the report.", id="latest"))
    update = await runtime.summary.abefore_model(
        {"messages": messages}, Runtime[Context](context=cast(Context, None))
    )
    assert update is not None
    assert (
        isinstance(received[0], SystemMessage) and received[0].content == runtime.system
    )
    assert received[-1].content == "Summarize only."
    prefix = received[1:-1]
    assert prefix == messages[: len(prefix)]
    calls = {
        call["id"]
        for message in prefix
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    }
    results = {
        message.tool_call_id for message in prefix if isinstance(message, ToolMessage)
    }
    assert calls == results
    assert binding == {"tools": [exec_shell], "tool_choice": "none"}
    replacements = cast(list[AnyMessage], update["messages"])
    assert replacements[1].additional_kwargs["lc_source"] == "summarization"
    assert replacements[2:] == messages[len(prefix) :]
