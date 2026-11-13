import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from time import monotonic
from typing import cast

from langchain.agents import create_agent  # pyright: ignore[reportUnknownVariableType]  # Native overload contains an unspecialized checkpoint generic.
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    SummarizationMiddleware,
    ToolCallRequest,
)
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    get_buffer_string,
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langfuse import Langfuse, propagate_attributes
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph  # pyright: ignore[reportMissingTypeStubs]  # Upstream package does not publish type stubs.
from langgraph.types import Command
from openlet_sdk.config import JSON, ReasoningEffort, secret
from opentelemetry import metrics
from pydantic import SecretStr
from temporalio import activity
from temporalio.exceptions import ApplicationError

from .. import events
from ..agents import get_agent, record, stable
from ..config import Services, model
from ..db import dsn
from ..filesystem.workspace import Filesystem
from ..jobs.agent import RunInput
from ..messages import pending
from .inbox import Inbox, State
from .tools import Context, tools

meter = metrics.get_meter("openlet.leta")
tool_duration = meter.create_histogram("openlet.leta.tool.duration", unit="s")
state_duration = meter.create_histogram("openlet.leta.state.duration", unit="s")
active = meter.create_up_down_counter("openlet.leta.runtime.active")


class ToolEffects(AgentMiddleware[State, Context]):
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[object]]],
    ) -> ToolMessage | Command[object]:
        started, outcome = monotonic(), "ok"
        try:
            return await handler(request)
        except (ValueError, LookupError, PermissionError, OSError) as error:
            outcome = "rejected"
            return ToolMessage(
                content=str(error), tool_call_id=request.tool_call["id"], status="error"
            )
        except Exception:
            outcome = "error"
            raise
        finally:
            tool_duration.record(
                monotonic() - started,
                {"tool": request.tool_call["name"], "outcome": outcome},
            )


class InputBudget(AgentMiddleware[State, Context]):
    def __init__(self, tokens: int) -> None:
        self.tokens = tokens

    async def awrap_model_call(
        self,
        request: ModelRequest[Context],
        handler: Callable[[ModelRequest[Context]], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        messages = [
            *([request.system_message] if request.system_message else []),
            *request.messages,
        ]
        if count_tokens_approximately(messages, tools=request.tools) > self.tokens:
            raise ApplicationError(
                "working context exceeds model input budget",
                type="context_limit",
                non_retryable=True,
            )
        return await handler(request)


async def project(s: Services, ctx: Context, messages: Sequence[BaseMessage]) -> None:
    for message in messages:
        if not message.id:
            continue
        entries: list[tuple[str, str, JSON]] = []
        if isinstance(message, HumanMessage):
            kind = (
                "compaction"
                if message.additional_kwargs.get("lc_source") == "summarization"
                else "inbox_input"
            )
            entries.append((message.id, kind, {"text": message.text}))
        elif isinstance(message, AIMessage):
            if message.text:
                entries.append(
                    (
                        message.id,
                        "assistant" if message.tool_calls else "final_note",
                        {"text": message.text},
                    )
                )
            for call in message.tool_calls:
                entries.append(
                    (
                        f"tool/{call['id']}",
                        "tool_call",
                        {
                            "tool_call_id": str(stable(ctx.id, f"tool/{call['id']}")),
                            "name": call["name"],
                            "args": cast(JSON, call["args"]),
                        },
                    )
                )
        elif isinstance(message, ToolMessage):
            entries.append(
                (
                    f"tool-result/{message.tool_call_id}",
                    "tool_result",
                    {
                        "tool_call_id": str(
                            stable(ctx.id, f"tool/{message.tool_call_id}")
                        ),
                        "name": message.name,
                        "text": message.text,
                    },
                )
            )
        for identity, kind, body in entries:
            id = await record(s.db, ctx.id, ctx.run_id, identity, kind, body)
            preview = json.dumps(body, ensure_ascii=False)
            reference: dict[str, JSON] = {
                "id": str(id),
                "kind": kind,
                "preview": preview[:500],
                "truncated": len(preview) > 500,
            }
            if kind == "tool_result" and isinstance(message, ToolMessage):
                await events.publish(
                    s.redis,
                    ctx.root,
                    events.event(
                        "TOOL_CALL_RESULT",
                        ctx.id,
                        ctx.run_id,
                        messageId=str(id),
                        toolCallId=str(stable(ctx.id, f"tool/{message.tool_call_id}")),
                        role="tool",
                        content=json.dumps(reference, ensure_ascii=False),
                    ),
                )
            await events.publish(
                s.redis,
                ctx.root,
                events.event(
                    "CUSTOM",
                    ctx.id,
                    ctx.run_id,
                    name="openlet.history",
                    value=reference,
                ),
            )


class Live:
    def __init__(self, s: Services, ctx: Context) -> None:
        self.s, self.ctx = s, ctx
        self.text: str | None = None
        self.calls: dict[int, str] = {}
        self.available = True

    async def emit(self, type: str, **fields: JSON) -> None:
        if self.available:
            self.available = await events.publish(
                self.s.redis,
                self.ctx.root,
                events.event(type, self.ctx.id, self.ctx.run_id, **fields),
            )

    async def chunk(self, message: AIMessageChunk) -> None:
        if message.text:
            if self.text is None:
                self.text = str(stable(self.ctx.id, message.id)) if message.id else None
                await self.emit(
                    "TEXT_MESSAGE_START", messageId=self.text, role="assistant"
                )
            await self.emit(
                "TEXT_MESSAGE_CONTENT", messageId=self.text, delta=message.text
            )
        for call in message.tool_call_chunks:
            index = call.get("index") or 0
            if call.get("id"):
                self.calls[index] = str(stable(self.ctx.id, f"tool/{call['id']}"))
                await self.emit(
                    "TOOL_CALL_START",
                    toolCallId=self.calls[index],
                    toolCallName=call.get("name") or "",
                )
            if index in self.calls and call.get("args"):
                await self.emit(
                    "TOOL_CALL_ARGS", toolCallId=self.calls[index], delta=call["args"]
                )

    async def close(self) -> None:
        if self.text:
            await self.emit("TEXT_MESSAGE_END", messageId=self.text)
        for id in self.calls.values():
            await self.emit("TOOL_CALL_END", toolCallId=id)


async def heartbeat() -> None:
    while True:
        activity.heartbeat()
        await asyncio.sleep(2)


async def protected[T](work: Awaitable[T]) -> T:
    task = asyncio.ensure_future(work)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Cancellation acknowledges only after the in-flight boundary is durable.
        await task
        raise


async def run(s: Services, lf: Langfuse, input: RunInput) -> str:
    async with AsyncExitStack() as stack:
        pulse = asyncio.create_task(heartbeat())

        async def stop_heartbeat() -> None:
            pulse.cancel()
            try:
                await pulse
            except asyncio.CancelledError:
                pass

        stack.push_async_callback(stop_heartbeat)
        lock = await stack.enter_async_context(s.db.connection())
        row = await (
            await lock.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s,2)) AS acquired",
                (str(input.agent_id),),
            )
        ).fetchone()
        assert row is not None
        if not row["acquired"]:
            raise ApplicationError("agent writer is busy", type="writer_busy")

        async def unlock() -> None:
            await lock.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s,2))",
                (str(input.agent_id),),
            )

        stack.push_async_callback(unlock)
        saver = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(dsn())
        )
        agent = await get_agent(s.db, input.agent_id)
        ctx = Context(s, agent, input.run_id, Filesystem(s, agent))
        stack.push_async_callback(ctx.filesystem.close)
        async with s.db.connection() as conn:
            await conn.execute(
                "INSERT INTO runs(id,agent_id,status) VALUES(%s,%s,'running') ON CONFLICT(id) DO UPDATE SET status='running',finished_at=NULL,error_code=NULL",
                (ctx.run_id, ctx.id),
            )
        config: RunnableConfig = {
            "configurable": {"thread_id": str(ctx.id)},
            "recursion_limit": 1000000,
        }
        checkpoint = await saver.aget_tuple(config)
        if checkpoint is not None:
            history = cast(
                list[AnyMessage],
                checkpoint.checkpoint["channel_values"].get("messages", []),
            )
            # Completed boundary projection is recovered before pruning or resuming.
            await project(s, ctx, history)
            age = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(checkpoint.checkpoint["ts"])
            ).total_seconds()
            if (
                age > s.config["services"]["letfs"]["idempotency_retention_seconds"]
                and history
                and isinstance(history[-1], AIMessage)
            ):
                if any(
                    call["name"]
                    in ("file_write", "file_edit", "exec_shell", "exec_python")
                    for call in history[-1].tool_calls
                ):
                    raise ApplicationError(
                        "pending file mutation result is unknown after receipt expiry; inspect files before retrying",
                        type="effect_result_unknown",
                        non_retryable=True,
                    )
        label = (
            s.config["langfuse"]["prompt_label"]
            if "langfuse" in s.config
            else "production"
        )
        role = "root" if agent["box_id"] is None else "leti"
        trace_name = "leta.agent" if role == "root" else "leti.agent"
        execution = activity.info()
        metadata = {
            "workspace_id": str(agent["workspace_id"]),
            "agent_id": str(ctx.id),
            "leta_id": str(ctx.root),
            "run_id": str(ctx.run_id),
            "temporal_workflow_id": execution.workflow_id or "",
            "temporal_run_id": execution.workflow_run_id or "",
            "temporal_attempt": str(execution.attempt),
        }
        if agent["box_id"]:
            metadata["box_id"] = str(agent["box_id"])
        prompt, compaction = await asyncio.gather(
            asyncio.to_thread(lf.get_prompt, f"leta/{role}", label=label, type="text"),
            asyncio.to_thread(
                lf.get_prompt, "leta/compaction", label=label, type="text"
            ),
        )
        stack.enter_context(
            propagate_attributes(
                session_id=str(ctx.id),
                trace_name=trace_name,
                metadata=metadata,
                tags=[role],
            )
        )
        stack.enter_context(
            lf.start_as_current_observation(
                name=trace_name,
                as_type="agent",
                trace_context={"trace_id": lf.create_trace_id()},
            )
        )
        callback = CallbackHandler()
        callback.run_inline = True
        config["callbacks"] = [callback]
        config["run_name"] = trace_name
        active.add(1, {"agent_role": role})
        await events.publish(
            s.redis,
            ctx.root,
            events.event(
                "RUN_STARTED",
                ctx.id,
                ctx.run_id,
                threadId=str(ctx.id),
                runId=str(ctx.run_id),
            ),
        )
        initial = checkpoint is None
        try:
            while True:
                agent = await get_agent(s.db, ctx.id)
                ctx.agent = agent
                if (
                    agent["state"] != "active"
                    or agent["box_id"]
                    and agent["box_state"] != "active"
                ):
                    return "stopped"
                if agent["paused"]:
                    return "paused"
                root = await get_agent(s.db, ctx.root) if agent["box_id"] else agent
                effort = (
                    agent["reasoning_effort"]
                    if agent["model_id"]
                    else root["reasoning_effort"]
                )
                if not agent["model_id"] and not root["model_id"]:
                    effort = s.config["models"]["leta"]["default"]["reasoning_effort"]
                entry = model(
                    s.config,
                    cast(str | None, agent["model_id"] or root["model_id"]),
                    cast(ReasoningEffort, effort),
                )
                provider = s.config["models"]["provider"]
                chat = ChatOpenAI(
                    model=entry["model_id"],
                    base_url=provider["base_url"],
                    api_key=SecretStr(secret(provider["api_key"])),
                    timeout=provider["timeout_seconds"],
                    max_retries=0,
                    max_completion_tokens=entry["max_output_tokens"],
                    reasoning_effort=cast(str | None, effort),
                    stream_usage=True,
                )
                context = f"Current time: {datetime.now(timezone.utc).isoformat()}. Timezone: UTC."
                if agent["box_id"]:
                    async with s.db.connection() as conn:
                        box = await (
                            await conn.execute(
                                "SELECT representative_agent_id FROM boxes WHERE id=%s",
                                (agent["box_id"],),
                            )
                        ).fetchone()
                    context += f" You are {'the' if box and box['representative_agent_id'] == ctx.id else 'not the'} box representative."
                system = (
                    prompt.compile()
                    + "\n\nConfigured assignment:\n"
                    + str(agent["system_prompt"])
                    + "\n\n"
                    + context
                )
                catalog = tools(root=agent["box_id"] is None)
                budget = entry["context_window_tokens"] - entry["max_output_tokens"]
                history_budget = budget - count_tokens_approximately(
                    [SystemMessage(content=system)], tools=[item for item in catalog]
                )
                if history_budget < 2000:
                    raise ApplicationError(
                        "model context is too small for agent instructions and tools",
                        non_retryable=True,
                    )

                async def summarize(messages: list[AnyMessage]) -> str:
                    with propagate_attributes(prompt=compaction):
                        result = await chat.ainvoke(
                            [
                                SystemMessage(content=compaction.compile()),
                                HumanMessage(
                                    content=get_buffer_string(messages, format="xml")
                                ),
                            ]
                        )
                    return result.text

                graph = cast(
                    CompiledStateGraph[State, Context, State, State],
                    create_agent(
                        chat,
                        catalog,
                        system_prompt=system,
                        state_schema=State,
                        context_schema=Context,
                        checkpointer=saver,
                        middleware=[
                            Inbox(s.db, ctx.id, agent["box_id"] is None),
                            cast(
                                AgentMiddleware[State, Context],
                                SummarizationMiddleware[JSON, Context](
                                    chat,
                                    trigger=("tokens", int(history_budget * 0.8)),
                                    keep=("tokens", int(history_budget * 0.3)),
                                    trim_tokens_to_summarize=int(history_budget * 0.7),
                                    summarizer=summarize,
                                ),
                            ),
                            ToolEffects(),
                            InputBudget(budget),
                        ],
                        interrupt_after=["model", "tools"],
                    ),
                )
                state = await graph.aget_state(config)
                if not state.next and not initial:
                    if not await pending(
                        s.db, ctx.id, cast(int, state.values.get("inbox_cursor", 0))
                    ):
                        return "completed"
                    graph_input: State | None = {"messages": []}
                else:
                    graph_input = {"messages": []} if initial else None
                initial = False

                async def advance() -> None:
                    live = Live(s, ctx)
                    changed: list[BaseMessage] = []
                    if "tools" in state.next:
                        message = cast(AIMessage, state.values["messages"][-1])
                        if any(
                            call["name"].startswith(("file_", "exec_"))
                            for call in message.tool_calls
                        ):
                            ctx.session = await ctx.filesystem.open()
                    with propagate_attributes(
                        session_id=str(ctx.id),
                        trace_name=trace_name,
                        metadata=metadata,
                        tags=[role],
                        prompt=prompt,
                    ):
                        async for item in graph.astream(  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
                            graph_input,
                            config,
                            context=ctx,
                            stream_mode=["messages", "updates"],
                            durability="sync",
                        ):
                            mode, value = cast(tuple[str, object], item)
                            if mode == "messages":
                                message, graph_metadata = cast(
                                    tuple[BaseMessage, dict[str, object]], value
                                )
                                if (
                                    isinstance(message, AIMessageChunk)
                                    and graph_metadata.get("langgraph_node") == "model"
                                ):
                                    await live.chunk(message)
                            elif mode == "updates":
                                for update in cast(dict[str, object], value).values():
                                    if isinstance(update, dict):
                                        changed.extend(
                                            cast(
                                                list[BaseMessage],
                                                cast(dict[str, object], update).get(
                                                    "messages", []
                                                ),
                                            )
                                        )
                    await live.close()
                    started = monotonic()
                    await project(s, ctx, changed)
                    state_duration.record(
                        monotonic() - started,
                        {"operation": "projection", "outcome": "ok"},
                    )
                    started = monotonic()
                    await saver.aprune([str(ctx.id)], strategy="keep_latest")
                    state_duration.record(
                        monotonic() - started,
                        {"operation": "prune", "outcome": "ok"},
                    )

                await protected(advance())
        finally:
            active.add(-1, {"agent_role": role})
