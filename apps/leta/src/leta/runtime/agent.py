import asyncio
import json
from collections.abc import Awaitable, Callable, Iterable, Sequence
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from time import monotonic
from typing import cast
from uuid import UUID

from langchain.agents import create_agent  # pyright: ignore[reportUnknownVariableType]  # Native overload contains an unspecialized checkpoint generic.
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    SummarizationMiddleware,
    ToolCallRequest,
)
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import (
    MessageLikeRepresentation,
    convert_to_messages,
)
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langfuse import Langfuse, propagate_attributes
from langfuse.langchain import CallbackHandler
from langfuse.model import TextPromptClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph  # pyright: ignore[reportMissingTypeStubs]  # Upstream package does not publish type stubs.
from langgraph.runtime import Runtime
from langgraph.types import Command
from openlet_sdk.config import JSON, ReasoningEffort, secret
from openlet_sdk.inference import InferenceSettings, response_cost
from opentelemetry import metrics
from temporalio import activity
from temporalio.client import WorkflowUpdateFailedError
from temporalio.exceptions import ApplicationError

from .. import events
from ..agents import history_id, record_batch, stable
from ..config import Services
from ..db import Row, dsn
from ..filesystem.workspace import Filesystem
from ..jobs.agent import RunInput, RunResult
from ..messages import has_pending
from .inbox import Inbox, State
from .model import ChatModel
from .tools import Context, tools

meter = metrics.get_meter("openlet.leta")
tool_duration = meter.create_histogram("openlet.leta.tool.duration", unit="s")
state_duration = meter.create_histogram("openlet.leta.state.duration", unit="s")
active = meter.create_up_down_counter("openlet.leta.runtime.active")


class InferenceCost(BaseCallbackHandler):
    run_inline = True

    def __init__(self, lf: Langfuse) -> None:
        self.lf = lf

    def on_llm_end(self, response: LLMResult, **kwargs: object) -> None:
        for group in response.generations:
            for generation in group:
                if isinstance(generation, ChatGeneration):
                    cost = response_cost(
                        generation.message.response_metadata.get("response_cost")
                    )
                    if cost is not None:
                        self.lf.update_current_generation(cost_details=cost)


class ToolEffects(AgentMiddleware[State, Context]):
    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[object]]],
    ) -> ToolMessage | Command[object]:
        started, outcome = monotonic(), "ok"
        try:
            message = cast(State, request.state)["messages"][-1]
            if (
                isinstance(message, AIMessage)
                and message.response_metadata.get("finish_reason") == "length"
            ):
                raise ValueError(
                    "Tool call was not executed: the model response reached its output limit. "
                    "Split large content into smaller operations and reissue complete arguments."
                )
            result = await handler(request)
            if (
                isinstance(result, ToolMessage)
                and result.status != "error"
                and request.tool_call["name"] == "exec_shell"
                and json.loads(result.text)["exit_code"] != 0
            ):
                result.status = "error"
            if isinstance(result, ToolMessage) and result.status == "error":
                outcome = "rejected"
            return result
        except (ValueError, LookupError, PermissionError, OSError) as error:
            outcome = "rejected"
            return ToolMessage(
                content=(
                    "Command exceeded its execution time limit. File changes may be incomplete; "
                    "inspect affected files before retrying."
                    if isinstance(error, TimeoutError)
                    else str(error)
                ),
                name=request.tool_call["name"],
                tool_call_id=request.tool_call["id"],
                status="error",
            )
        except WorkflowUpdateFailedError as error:
            cause = error.cause
            while isinstance(cause, BaseException):
                if isinstance(cause, ApplicationError) and cause.type in {
                    "ValueError",
                    "LookupError",
                    "PermissionError",
                }:
                    outcome = "rejected"
                    return ToolMessage(
                        content=cause.message,
                        name=request.tool_call["name"],
                        tool_call_id=request.tool_call["id"],
                        status="error",
                    )
                cause = getattr(cause, "cause", None)
            outcome = "error"
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            tool_duration.record(
                monotonic() - started,
                {"tool": request.tool_call["name"], "outcome": outcome},
            )


class ExecutionModel(AgentMiddleware[State, Context]):
    def __init__(
        self,
        s: Services,
        defaults: InferenceSettings,
        prompt: TextPromptClient,
        compaction: TextPromptClient,
        catalog: list[BaseTool],
        box_context: str,
    ) -> None:
        self.s, self.defaults, self.prompt, self.compaction = (
            s,
            defaults,
            prompt,
            compaction,
        )
        self.catalog, self.box_context = catalog, box_context
        self.selection: tuple[str, ReasoningEffort, str] | None = None
        self.chat: ChatModel
        self.summary: SummarizationMiddleware[JSON, Context]
        self.system = ""
        self.tokens = 0

    async def refresh(self, agent: Row) -> None:
        selected = cast(str | None, agent["model_id"] or agent["root_model_id"])
        effort = cast(
            ReasoningEffort,
            agent["reasoning_effort"]
            if agent["model_id"]
            else agent["root_reasoning_effort"],
        )
        if selected is None:
            selected, effort = self.defaults.model, self.defaults.reasoning_effort
        selection = (selected, effort, str(agent["system_prompt"]))
        if selection == self.selection:
            return
        entry = await self.s.models.get(selected, effort)
        if self.defaults.max_tokens > entry.max_output_tokens:
            raise ValueError("prompt output budget exceeds gateway model limit")
        settings = self.s.config["services"]["leta"]["compaction"]
        if settings["summary_max_tokens"] > entry.max_output_tokens:
            raise ValueError("summary output budget exceeds gateway model limit")
        self.summary_instruction = self.compaction.compile(
            summary_max_tokens=settings["summary_max_tokens"]
        )
        self.system = self.prompt.compile(
            agent_instructions=selection[2], box_context=self.box_context
        )
        gateway = self.s.config["models"]["gateway"]
        if self.selection is None or selection[:2] != self.selection[:2]:
            parameters = self.defaults.model_copy(
                update={"reasoning_effort": effort}
            ).parameters()
            self.chat = ChatModel(
                model="litellm_proxy/" + selected,
                api_base=gateway["base_url"],
                api_key=secret(gateway["api_key"]),
                request_timeout=gateway["timeout_seconds"],
                max_retries=0,
                max_tokens=self.defaults.max_tokens,
                metadata={"ls_model_name": selected},
                model_kwargs={
                    **{k: v for k, v in parameters.items() if k != "max_tokens"},
                    "num_retries": 0,
                    "stream_options": {"include_usage": True},
                },
            )
        self.tokens = entry.context_window_tokens - self.defaults.max_tokens
        overhead = self.count_tokens(
            [
                SystemMessage(content=self.system),
                HumanMessage(content=self.summary_instruction),
            ],
            include_tools=True,
        )
        history_budget = self.tokens - overhead
        if settings["keep_tokens"] + settings["summary_max_tokens"] >= history_budget:
            raise ApplicationError(
                "model context is too small for instructions, tools, summary and retained tail",
                non_retryable=True,
            )
        self.summary = SummarizationMiddleware[JSON, Context](
            self.chat,
            # Native triggers also compare provider usage for the full request.
            trigger=("tokens", int(self.tokens * settings["trigger_fraction"])),
            keep=("tokens", settings["keep_tokens"]),
            token_counter=self.count_tokens,
            trim_tokens_to_summarize=None,
            summarizer=self.summarize,
        )
        self.selection = selection

    def count_tokens(
        self,
        messages: Iterable[MessageLikeRepresentation],
        *,
        include_tools: bool = False,
    ) -> int:
        return self.chat.count_tokens(
            convert_to_messages(messages), tools=self.catalog if include_tools else None
        )

    def guard(self, messages: list[BaseMessage]) -> None:
        if self.count_tokens(messages, include_tools=True) > self.tokens:
            raise ApplicationError(
                "working context exceeds model input budget",
                type="context_limit",
                non_retryable=True,
            )

    async def summarize(self, messages: list[AnyMessage]) -> str:
        request: list[BaseMessage] = [
            SystemMessage(content=self.system),
            *messages,
            HumanMessage(content=self.summary_instruction),
        ]
        self.guard(request)
        with propagate_attributes(prompt=self.compaction):
            bound = self.chat.bind_tools(  # pyright: ignore[reportUnknownMemberType]  # Native overload includes untyped callable tools.
                self.catalog,
                tool_choice="none",
                max_tokens=self.s.config["services"]["leta"]["compaction"][
                    "summary_max_tokens"
                ],
            )
            result = await bound.ainvoke(request)
        if (
            not result.text.strip()
            or result.response_metadata.get("finish_reason") == "length"
        ):
            raise ApplicationError(
                "compaction summary is empty or exceeded its output budget",
                type="summary_limit",
                non_retryable=True,
            )
        return result.text

    async def abefore_model(
        self, state: State, runtime: Runtime[Context]
    ) -> dict[str, object] | None:
        return await self.summary.abefore_model(state, runtime)

    async def awrap_model_call(
        self,
        request: ModelRequest[Context],
        handler: Callable[[ModelRequest[Context]], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        self.guard([SystemMessage(content=self.system), *request.messages])
        return await handler(
            request.override(
                model=self.chat, system_message=SystemMessage(content=self.system)
            )
        )


async def runtime_agent(s: Services, id: UUID) -> Row:
    async with s.db.connection() as conn:
        row = await (
            await conn.execute(
                """SELECT a.*,l.workspace_id,l.storage_id,l.state,l.paused,b.home_node_id,b.state AS box_state,
            r.model_id AS root_model_id,r.reasoning_effort AS root_reasoning_effort
            FROM agents a JOIN letas l ON l.id=a.leta_id JOIN agents r ON r.id=a.leta_id
            LEFT JOIN boxes b ON b.id=a.box_id WHERE a.id=%s""",
                (id,),
            )
        ).fetchone()
    if row is None:
        raise LookupError("agent not found")
    return row


async def box_context(s: Services, agent: Row) -> str:
    if agent["box_id"] is None:
        return ""
    async with s.db.connection() as conn:
        box = await (
            await conn.execute(
                "SELECT name,description,representative_agent_id FROM boxes WHERE id=%s",
                (agent["box_id"],),
            )
        ).fetchone()
        members = await (
            await conn.execute(
                """SELECT a.id,a.name,a.description,EXISTS(SELECT 1 FROM box_edges e
            WHERE e.box_id=a.box_id AND ((e.agent_low_id=%s AND e.agent_high_id=a.id)
            OR (e.agent_high_id=%s AND e.agent_low_id=a.id))) AS connected
            FROM agents a WHERE a.box_id=%s ORDER BY a.name,a.id""",
                (agent["id"], agent["id"], agent["box_id"]),
            )
        ).fetchall()
    assert box is not None
    lines = [
        f"Box: {box['name']}",
        f"Purpose: {box['description']}",
        f"You: {agent['name']}",
        "Teammates:",
    ]
    for member in members:
        if member["id"] == agent["id"]:
            continue
        representative = (
            " (representative)"
            if member["id"] == box["representative_agent_id"]
            else ""
        )
        recipient = f"; recipient: {member['id']}" if member["connected"] else ""
        lines.append(
            f"- {member['name']}{representative}: {member['description']}{recipient}"
        )
    if box["representative_agent_id"] == agent["id"]:
        lines.append(f"You are the representative. Root recipient: {agent['leta_id']}")
    return "\n".join(lines)


async def project(s: Services, ctx: Context, messages: Sequence[BaseMessage]) -> None:
    entries: list[tuple[str, str, JSON]] = []
    for message in messages:
        if not message.id:
            continue
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
                        "status": message.status,
                        **(
                            {"file": {"path": message.artifact, "kind": "image"}}
                            if message.name == "file_read"
                            and isinstance(message.artifact, str)
                            else {}
                        ),
                    },
                )
            )
    projected: list[events.Event] = []
    for id, kind, body in await record_batch(s.db, ctx.id, ctx.run_id, entries):
        preview = json.dumps(body, ensure_ascii=False)
        reference: dict[str, JSON] = {
            "id": str(id),
            "kind": kind,
            "preview": preview[:500],
            "truncated": len(preview) > 500,
        }
        if kind == "tool_result" and isinstance(body, dict):
            projected.append(
                events.event(
                    "TOOL_CALL_RESULT",
                    ctx.id,
                    ctx.run_id,
                    messageId=str(id),
                    toolCallId=body["tool_call_id"],
                    role="tool",
                    content=json.dumps(reference, ensure_ascii=False),
                )
            )
        projected.append(
            events.event(
                "CUSTOM", ctx.id, ctx.run_id, name="openlet.history", value=reference
            )
        )
    await events.publish_batch(s.redis, ctx.root, projected)


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
                self.text = (
                    str(history_id(self.ctx.id, message.id)) if message.id else None
                )
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


async def run(s: Services, lf: Langfuse, input: RunInput) -> RunResult:
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
            AsyncPostgresSaver.from_conn_string(dsn(s.config))
        )
        agent = await runtime_agent(s, input.agent_id)
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
                    call["name"] in ("file_write", "file_edit", "exec_shell")
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
            asyncio.to_thread(
                lf.get_prompt,
                f"leta/{role}",
                label=label,
                type="text",
                cache_ttl_seconds=60,
            ),
            asyncio.to_thread(
                lf.get_prompt,
                "leta/compaction",
                label=label,
                type="text",
                cache_ttl_seconds=60,
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
        config["callbacks"] = [InferenceCost(lf), callback]
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
        catalog = tools(root=agent["box_id"] is None)
        execution_model = ExecutionModel(
            s,
            InferenceSettings.model_validate(prompt.config),
            prompt,
            compaction,
            catalog,
            await box_context(s, agent),
        )
        await execution_model.refresh(agent)
        # TODO: invalid-only tool calls can end a turn early; see https://github.com/langchain-ai/langchain/issues/33504.
        graph = cast(
            CompiledStateGraph[State, Context, State, State],
            create_agent(
                execution_model.chat,
                catalog,
                state_schema=State,
                context_schema=Context,
                checkpointer=saver,
                middleware=[
                    Inbox(s.db, ctx.id, agent["box_id"] is None),
                    execution_model,
                    ToolEffects(),
                ],
                interrupt_after=["model", "tools"],
            ),
        )
        cursor = (
            cast(int, checkpoint.checkpoint["channel_values"].get("inbox_cursor", 0))
            if checkpoint
            else 0
        )
        initial = checkpoint is None
        try:
            while True:
                agent = await runtime_agent(s, ctx.id)
                ctx.agent = agent
                if (
                    agent["state"] != "active"
                    or agent["box_id"]
                    and agent["box_state"] != "active"
                ):
                    return RunResult(status="stopped", inbox_cursor=cursor)
                if agent["paused"]:
                    return RunResult(status="paused", inbox_cursor=cursor)
                await execution_model.refresh(agent)
                state = await graph.aget_state(config)
                cursor = cast(int, state.values.get("inbox_cursor", 0))
                if not state.next and not initial:
                    if not await has_pending(
                        s.db, ctx.id, cast(int, state.values.get("inbox_cursor", 0))
                    ):
                        return RunResult(status="completed", inbox_cursor=cursor)
                    graph_input: State | None = {"messages": []}
                else:
                    graph_input = {"messages": []} if initial else None
                initial = False

                async def advance() -> None:
                    live = Live(s, ctx)
                    changed: list[BaseMessage] = []
                    with propagate_attributes(prompt=prompt):
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
