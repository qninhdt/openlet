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


@pytest.mark.parametrize("last_line", [10000, 200000])
async def test_shell_capture_is_bounded_and_redirection_remains_complete(
    last_line: int,
) -> None:
    from leta.filesystem.workspace import shell
    from mirage import Mount, MountMode, Workspace
    from mirage.vfs.ram import RAMVFS

    workspace = Workspace(
        {"/data": Mount(vfs=RAMVFS(), mode=MountMode.WRITE)}, network=False
    )
    try:
        session = await workspace.session("tools")
        result = await shell(
            session,
            f"seq 1 {last_line} | tee /data/full.txt",
            cwd="/",
            output_path="/data/output.txt",
        )
        assert result["truncated"] is True
        assert len(str(result["stdout"]).encode()) <= 16384
        assert str(result["stdout"]).startswith("1\n")
        assert str(result["stdout"]).endswith(f"{last_line}\n")
        full = await session.vfs.read("/data/full.txt")
        captured = await session.vfs.read("/data/output.txt")
        assert full.endswith(f"{last_line}\n".encode())
        assert captured == full[: 1024 * 1024]
        assert result["output_complete"] is (len(full) <= 1024 * 1024)
    finally:
        await workspace.close()


@pytest.mark.parametrize("keep_fraction", [0.0, 0.3])
async def test_execution_reuses_client_and_native_compaction_preserves_prefix(
    monkeypatch: pytest.MonkeyPatch,
    keep_fraction: float,
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
    from temporalio.exceptions import ApplicationError

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
    config["services"]["leta"]["compaction"]["keep_fraction"] = keep_fraction
    monkeypatch.setenv("LITELLM_MASTER_KEY", "fixture")
    services = cast(
        Services, SimpleNamespace(config=config, models=cast(Models, Catalog()))
    )
    runtime = ExecutionModel(
        services,
        InferenceSettings(model="chat", max_tokens=1024),
        prompt("Product rules\nYour instructions\n{{agent_instructions}}"),
        prompt("Summarize only, within {{summary_max_tokens}} tokens."),
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
    finish_reason = "stop"

    async def summarize(messages: list[AnyMessage]) -> AIMessage:
        received.extend(messages)
        return AIMessage(
            content="Keep the goal and confirmed effects.",
            response_metadata={"finish_reason": finish_reason},
        )

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
                HumanMessage(content=("source " * 3500), id=f"input-{index}"),
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
    assert received[-1].content == "Summarize only, within 2048 tokens."
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
    assert binding == {
        "tools": [exec_shell],
        "tool_choice": "none",
        "max_tokens": 2048,
    }
    replacements = cast(list[AnyMessage], update["messages"])
    assert replacements[1].additional_kwargs["lc_source"] == "summarization"
    assert replacements[2:] == messages[len(prefix) :]
    if keep_fraction == 0:
        assert prefix == messages
        assert len(replacements) == 2
        received.clear()
        after_tool = await runtime.summary.abefore_model(
            {"messages": messages[:-1]}, Runtime[Context](context=cast(Context, None))
        )
        assert after_tool is not None
        assert received[1:-1] == messages[:-1]
        assert len(cast(list[AnyMessage], after_tool["messages"])) == 2

    agent["system_prompt"] = "Fixed product rules. " * 1200
    await runtime.refresh(agent)
    recent: list[AnyMessage] = [
        HumanMessage(content="Retained source details. " * 1800),
        AIMessage(
            content="Continue the remaining work.",
            response_metadata={"model_provider": "litellm"},
            usage_metadata={
                "input_tokens": 17000,
                "output_tokens": 100,
                "total_tokens": 17100,
            },
        ),
    ]
    received.clear()
    assert (
        await runtime.summary.abefore_model(
            {"messages": recent}, Runtime[Context](context=cast(Context, None))
        )
        is None
    )
    assert not received
    cast(AIMessage, recent[-1]).usage_metadata = {
        "input_tokens": 19000,
        "output_tokens": 100,
        "total_tokens": 19100,
    }
    assert (
        await runtime.summary.abefore_model(
            {"messages": recent}, Runtime[Context](context=cast(Context, None))
        )
        is not None
    )

    ledger: list[AnyMessage] = [
        HumanMessage(content="KH-001,điều chỉnh đã duyệt,1.234.567.890 VND\n" * 30)
        for _ in range(12)
    ]
    ledger.append(recent[-1])
    update = await runtime.summary.abefore_model(
        {"messages": ledger}, Runtime[Context](context=cast(Context, None))
    )
    assert update is not None
    retained = cast(list[AnyMessage], update["messages"])[2:]
    if keep_fraction == 0:
        assert retained == []
    else:
        assert runtime.count_tokens(retained) <= int(runtime.summary.keep[1])

    finish_reason = "length"
    with pytest.raises(ApplicationError, match="summary is empty or exceeded"):
        await runtime.summarize([HumanMessage(content="Keep this original context.")])


def test_compaction_config_allows_no_tail_and_requires_positive_summary_budget() -> (
    None
):
    from pathlib import Path
    from typing import cast

    import yaml
    from leta.config import validate
    from openlet_sdk.config import Config

    config = cast(
        Config, yaml.safe_load(Path("infra/config/openlet.example.yaml").read_text())
    )
    validate(config)
    settings = config["services"]["leta"]["compaction"]
    settings["keep_fraction"] = -0.1
    with pytest.raises(ValueError, match="keep_fraction"):
        validate(config)
    settings["keep_fraction"] = 0
    settings["summary_max_tokens"] = 0
    with pytest.raises(ValueError, match="summary_max_tokens"):
        validate(config)
