import asyncio
import json
import logging
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
from psycopg import Error as DatabaseError
from psycopg_pool import PoolTimeout
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
        self.selection: tuple[str, ReasoningEffort, str, str, str, str] | None = None
        self.chat: ChatModel
        self.summary: SummarizationMiddleware[JSON, Context]
        self.system = ""
        self.tokens = 0

    async def refresh(self, agent: Row) -> None:
        selected = cast(str | None, agent["model_id"] or agent["leta_model_id"])
        effort = cast(
            ReasoningEffort,
            agent["reasoning_effort"]
            if agent["model_id"]
            else agent["leta_reasoning_effort"],
        )
        if selected is None:
            selected, effort = self.defaults.model, self.defaults.reasoning_effort
        instructions = str(agent["system_prompt"])
        name, title, handle = (
            str(agent.get(field, "")) for field in ("name", "title", "handle")
        )
        selection = (selected, effort, instructions, name, title, handle)
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
            agent_instructions=instructions,
            agent_name=name,
            agent_title=title,
            agent_handle=handle,
            box_context=self.box_context,
        )
        gateway = self.s.config["models"]["gateway"]
        if self.selection is None or selection[:2] != self.selection[:2]:
            parameters = self.defaults.model_copy(
                update={"reasoning_effort": effort}
            ).parameters()
            self.chat = ChatModel(
                model=selected,
                custom_llm_provider="litellm_proxy",
                api_base=gateway["base_url"],
                api_key=secret(gateway["api_key"]),
                request_timeout=gateway["timeout_seconds"],
                max_retries=0,
                max_tokens=self.defaults.max_tokens,
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
        messages = state["messages"]
        last = messages[-1] if messages else None
        # With sync durability the preceding Inbox node is already checkpointed.
        if isinstance(last, HumanMessage) and "openlet" in last.additional_kwargs:
            await project(self.s, runtime.context, [last])
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
                """SELECT a.*,l.workspace_id,l.storage_id,l.state,l.paused,b.handle AS box_handle,b.leader_agent_id,b.state AS box_state,
            r.handle AS leta_handle,r.model_id AS leta_model_id,r.reasoning_effort AS leta_reasoning_effort
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
                "SELECT name,handle,description,workflow,leader_agent_id FROM boxes WHERE id=%s",
                (agent["box_id"],),
            )
        ).fetchone()
        members = await (
            await conn.execute(
                """SELECT a.id,a.name,a.title,a.description,a.handle,EXISTS(SELECT 1 FROM box_links e
            WHERE e.box_id=a.box_id AND ((e.agent_low_id=%s AND e.agent_high_id=a.id)
            OR (e.agent_high_id=%s AND e.agent_low_id=a.id))) AS connected
            FROM agents a WHERE a.box_id=%s AND a.id<>%s ORDER BY a.name,a.id""",
                (agent["id"], agent["id"], agent["box_id"], agent["id"]),
            )
        ).fetchall()
    assert box is not None
    leader = box["leader_agent_id"]
    lines = [
        f"Box: {box['name']}",
        f"Purpose: {box['description']}",
        f"Work directory: ~/.boxes/{box['handle']}/",
    ]
    if box["workflow"]:
        lines.append(f"Workflow: {box['workflow']}")
    if agent["id"] == leader:
        lines.append(f"You are the Box Leader. Leta: agent:{agent['leta_handle']}")
    lines.append("Teammates:")
    for member in members:
        name = f"{member['name']} The {member['title']}"
        role = " (Leader)" if member["id"] == leader else ""
        contact = (
            f"agent:{member['handle']}"
            if agent["id"] == leader or member["id"] == leader or member["connected"]
            else "contact through the Leader"
        )
        lines.append(f"- {name}{role} | {contact} | {member['description']}")
    return "\n".join(lines)


def reasoning_text(message: AIMessage) -> str:
    parts: list[str] = []
    for block in message.content_blocks:
        if block["type"] == "reasoning":
            text = block.get("reasoning")
            if isinstance(text, str):
                parts.append(text)
    if parts:
        return "".join(parts)
    # LiteLLM retains signed Anthropic blocks separately for replay; publish only their readable text.
    blocks = cast(
        object, message.additional_kwargs.get("thinking_blocks", message.content)
    )
    if isinstance(blocks, list):
        for value in cast(list[object], blocks):
            if isinstance(value, dict):
                block = cast(dict[str, object], value)
                text = block.get("thinking")
                if block.get("type") == "thinking" and isinstance(text, str):
                    parts.append(text)
    return "".join(parts)


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
            input_body: dict[str, JSON] = {"text": message.text}
            metadata = message.additional_kwargs.get("openlet")
            if isinstance(metadata, dict):
                public_metadata = cast(dict[str, JSON], metadata)
                if public_metadata.get("version") == 1:
                    input_body["ui"] = public_metadata
            entries.append((message.id, kind, input_body))
        elif isinstance(message, AIMessage):
            reasoning = reasoning_text(message)
            if message.text or reasoning:
                entries.append(
                    (
                        message.id,
                        "assistant" if message.tool_calls else "final_note",
                        {
                            "text": message.text,
                            **({"reasoning": reasoning} if reasoning else {}),
                        },
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
            artifact = (
                cast(dict[str, JSON], cast(object, message.artifact))
                if isinstance(cast(object, message.artifact), dict)
                else {}
            )
            ui = artifact.get("ui")
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
                            {"ui": ui}
                            if isinstance(ui, dict) and ui.get("version") == 1
                            else {}
                        ),
                        **(
                            {
                                "file": {
                                    "path": cast(str, cast(object, message.artifact)),
                                    "kind": "image",
                                }
                            }
                            if message.name == "file_read"
                            and isinstance(cast(object, message.artifact), str)
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
    await events.publish_batch(s.redis, ctx.leta_id, projected)


class Live:
    def __init__(self, s: Services, ctx: Context) -> None:
        self.s, self.ctx = s, ctx
        self.text: str | None = None
        self.reasoning: str | None = None
        self.message: str | None = None
        self.calls: dict[int, str] = {}
        self.available = True

    async def emit(self, type: str, **fields: JSON) -> None:
        if self.available:
            self.available = await events.publish(
                self.s.redis,
                self.ctx.leta_id,
                events.event(type, self.ctx.id, self.ctx.run_id, **fields),
            )

    async def chunk(self, message: AIMessageChunk) -> None:
        id = str(history_id(self.ctx.id, message.id)) if message.id else self.message
        if id and self.message != id:
            await self.close()
            self.message = id
        reasoning = reasoning_text(message)
        if reasoning and id:
            if self.reasoning is None:
                self.reasoning = id
                await self.emit("REASONING_MESSAGE_START", messageId=id)
            await self.emit("REASONING_MESSAGE_CONTENT", messageId=id, delta=reasoning)
        if message.text and id:
            if self.text is None:
                self.text = id
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
        if self.reasoning:
            await self.emit("REASONING_MESSAGE_END", messageId=self.reasoning)
        if self.text:
            await self.emit("TEXT_MESSAGE_END", messageId=self.text)
        for id in self.calls.values():
            await self.emit("TOOL_CALL_END", toolCallId=id)
        self.reasoning = self.text = None
        self.calls.clear()


async def heartbeat(s: Services, run: UUID) -> None:
    last = 0.0
    while True:
        activity.heartbeat()
        if monotonic() - last >= 5:
            last = monotonic()
            try:
                async with asyncio.timeout(2), s.db.connection() as conn:
                    await conn.execute(
                        "UPDATE runs SET heartbeat_at=now() WHERE id=%s AND status='running'",
                        (run,),
                    )
            except DatabaseError, PoolTimeout, TimeoutError:
                logging.getLogger(__name__).warning(
                    "runtime heartbeat summary unavailable", extra={"run_id": str(run)}
                )
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
        pulse = asyncio.create_task(heartbeat(s, input.run_id))

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
                "INSERT INTO runs(id,agent_id,status,heartbeat_at) VALUES(%s,%s,'running',now()) ON CONFLICT(id) DO UPDATE SET status='running',heartbeat_at=now(),finished_at=NULL,error_code=NULL",
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
                    call["name"] in ("file_write", "file_edit", "execute")
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
        role = "leta" if agent["box_id"] is None else "leti"
        trace_name = f"{role}.agent"
        execution = activity.info()
        metadata = {
            "workspace_id": str(agent["workspace_id"]),
            "agent_id": str(ctx.id),
            "leta_id": str(ctx.leta_id),
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
            ctx.leta_id,
            events.event(
                "RUN_STARTED",
                ctx.id,
                ctx.run_id,
                threadId=str(ctx.id),
                runId=str(ctx.run_id),
            ),
        )
        catalog = tools(leta=agent["box_id"] is None, web=s.web is not None)
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
                                for node, update in cast(
                                    dict[str, object], value
                                ).items():
                                    if node == "Inbox.before_model":
                                        continue
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
