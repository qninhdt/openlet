from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import ExitStack
from time import monotonic
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langfuse import propagate_attributes
from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
from openlet_sdk.types import is_object_list, is_str_mapping

from ..channels.base import CallerContext
from ..channels.internal_agent import InternalAgentAdapter
from ..channels.openlet_chat import OpenletChatAdapter
from ..channels.router import ChannelRouter
from ..config import Services
from ..db import (
    LeaseLostError,
    WriterBusyError,
    acquire_lease,
    release_lease,
    renew_lease,
)
from ..filesystem.workspace import Filesystem
from ..runs import (
    RunOutcome,
    load_agent_runtime_record,
    start_run,
    touch_run_heartbeat,
)
from .checkpoint import make_checkpointer
from .graph import build_agent_graph
from .prompts import prompt_version_hash
from .state import AgentState, RuntimeContext
from .tools.files import build_file_tools
from .tools.messaging import build_messaging_tools
from .tools.web import build_web_tools
from .tools.workspace_tools import build_domain_tools

logger = logging.getLogger(__name__)


def build_tool_catalog(services: Services, *, is_root: bool) -> dict[str, BaseTool]:
    flags = services.settings.tools
    tools: list[BaseTool] = []
    tools.extend(
        build_file_tools(
            enable_bash=flags.bash,
            enable_semantic_search=flags.semantic_search,
        )
    )
    if flags.web:
        tools.extend(build_web_tools())
    tools.extend(build_messaging_tools(is_root=is_root, enable_react=flags.react))
    tools.extend(
        build_domain_tools(
            is_root=is_root,
            enable_subagents=flags.subagents,
            enable_hitl=flags.hitl,
            enable_schedule=flags.schedule,
            enable_todo=flags.todo,
        )
    )
    return {t.name: t for t in tools}


def find_orphaned_tool_calls(messages: list[BaseMessage]) -> list[tuple[str, str]]:
    """Return [(call_id, tool_name)] for an AIMessage whose tool_calls lack matching ToolMessages."""
    if not messages:
        return []
    # Find the last AIMessage after which only ToolMessages (if any) appear.
    answered: set[str] = set()
    ai_msg: AIMessage | None = None
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            answered.add(msg.tool_call_id)
        elif isinstance(msg, AIMessage):
            ai_msg = msg
            break
        else:
            break
    if ai_msg is None or not ai_msg.tool_calls:
        return []
    missing: list[tuple[str, str]] = []
    for tc in ai_msg.tool_calls:
        cid = str(tc.get("id") or "")
        cname = str(tc.get("name") or "")
        if cid and cid not in answered:
            missing.append((cid, cname))
    return missing


async def run_agent_turn(
    services: Services,
    *,
    agent_id: UUID,
    run_id: UUID,
    heartbeat: Callable[[], None] | None = None,
) -> RunOutcome:
    """Layer 2 runner executing the 5-node LangGraph StateGraph."""
    orch_cfg = services.settings.orchestration
    lease_token = uuid4()

    # Wait briefly if a prior attempt is still unwinding its finally block.
    lease_deadline = monotonic() + 15.0
    while True:
        try:
            await acquire_lease(
                services.db,
                agent_id,
                lease_token,
                ttl_seconds=orch_cfg.lease_ttl_seconds,
            )
            break
        except WriterBusyError:
            if monotonic() >= lease_deadline:
                raise
            if heartbeat is not None:
                try:
                    heartbeat()
                except Exception:
                    pass
            await asyncio.sleep(1.5)

    try:
        agent_row = await load_agent_runtime_record(services.db, agent_id)
        leta_id = agent_row.leta_id
        workspace_id = agent_row.workspace_id
        storage_id = agent_row.storage_id
        is_root = agent_row.parent_agent_id is None
        handle = agent_row.handle
        model_spec = await services.models.get(
            agent_row.model_id, agent_row.reasoning_effort
        )
    except Exception:
        await release_lease(services.db, agent_id, lease_token)
        raise

    router = ChannelRouter(
        [
            OpenletChatAdapter(services.chat, services.platform_internal, services.db),
            InternalAgentAdapter(services.db, services.inbox),
        ]
    )
    fs = Filesystem(services, agent_row)
    tools = build_tool_catalog(services, is_root=is_root)

    rt = RuntimeContext(
        agent_id=agent_id,
        leta_id=leta_id,
        workspace_id=workspace_id,
        storage_id=storage_id,
        is_root=is_root,
        handle=handle,
        agent_name=agent_row.name,
        agent_title=agent_row.title,
        agent_description=agent_row.description,
        custom_instructions=agent_row.custom_instructions,
        parent_handle=agent_row.parent_handle or "",
        model_spec=model_spec,
        reasoning_effort=agent_row.reasoning_effort,
        run_id=run_id,
        services=services,
        emitter=services.activity,
        fs=fs,
        router=router,
        tools=tools,
    )

    trigger_seq = await start_run(services.db, run_id, agent_id)

    await services.activity.emit(
        leta_id=leta_id,
        agent_id=agent_id,
        run_id=run_id,
        event_type="run.started",
        data={"agent_handle": handle, "trigger_seq": trigger_seq},
    )

    # Independent heartbeat task (never blocks on DB or gRPC).
    graph_task: asyncio.Task[int] | None = None
    lease_lost = False

    async def _heartbeat_loop() -> None:
        while True:
            await asyncio.sleep(orch_cfg.heartbeat_interval_seconds)
            if heartbeat is not None:
                try:
                    heartbeat()
                except Exception:
                    pass

    async def _lease_renew_loop() -> None:
        nonlocal lease_lost
        caller = CallerContext(
            workspace_id=workspace_id,
            leta_id=leta_id,
            agent_id=agent_id,
            handle=handle,
            name=rt.agent_name,
            is_root=is_root,
        )
        while True:
            await asyncio.sleep(orch_cfg.lease_renew_interval_seconds)
            ok = await renew_lease(
                services.db,
                agent_id,
                lease_token,
                ttl_seconds=orch_cfg.lease_ttl_seconds,
            )
            if not ok:
                lease_lost = True
                if graph_task is not None and not graph_task.done():
                    graph_task.cancel()
                return
            try:
                await touch_run_heartbeat(services.db, run_id)
            except Exception:
                pass
            for addr in list(rt.active_typing):
                try:
                    await router.set_typing(caller, addr, True)
                except Exception:
                    pass

    hb_task = asyncio.create_task(_heartbeat_loop())
    lease_task = asyncio.create_task(_lease_renew_loop())
    final_cursor = 0

    try:
        # Opportunistically sweep expired spill files (non-blocking best-effort).
        await fs.sweep_spill_dir()

        saver = make_checkpointer(services.db)
        compiled = build_agent_graph(list(tools.values()), checkpointer=saver)
        config: RunnableConfig = {
            "configurable": {"thread_id": str(agent_id)},
            "recursion_limit": 200,
        }
        lf = services.langfuse
        if lf is not None:
            lf_handler = LangfuseCallbackHandler()
            lf_handler.run_inline = True
            config["callbacks"] = [lf_handler]

        snapshot = await compiled.aget_state(config)
        raw_values: object = snapshot.values
        existing_values = raw_values if is_str_mapping(raw_values) else {}
        raw_msgs = existing_values.get("messages")
        existing_msgs: list[BaseMessage] = (
            [m for m in raw_msgs if isinstance(m, BaseMessage)]
            if is_object_list(raw_msgs)
            else []
        )
        raw_cursor = existing_values.get("inbox_cursor")
        final_cursor = raw_cursor if isinstance(raw_cursor, int) else 0

        # Case A: Repair orphaned tool_calls left by an interrupted prior run.
        orphans = find_orphaned_tool_calls(existing_msgs)
        if orphans:
            synthetic_tools = [
                ToolMessage(
                    content="Execution was interrupted before this tool completed.",
                    tool_call_id=cid,
                    name=cname,
                    status="error",
                )
                for cid, cname in orphans
            ]
            await compiled.aupdate_state(config, {"messages": synthetic_tools})
            snapshot = await compiled.aget_state(config)

        # Case B: Resume interrupted worker OOM mid-node vs Case C: normal start.
        async def _run_graph() -> int:
            with ExitStack() as stack:
                if lf is not None:
                    stack.enter_context(
                        lf.start_as_current_observation(
                            name="leta.agent_turn",
                            as_type="agent",
                            metadata={
                                "run_id": str(run_id),
                                "agent_id": str(agent_id),
                                "handle": handle,
                                "is_root": is_root,
                                "model_id": model_spec.model_id,
                                "prompt_hash": prompt_version_hash(is_root),
                            },
                        )
                    )
                    stack.enter_context(
                        propagate_attributes(
                            session_id=str(leta_id),
                            user_id=str(workspace_id),
                            trace_name=f"leta.{'root' if is_root else 'subagent'}.turn",
                            tags=[
                                "leta",
                                "root" if is_root else "subagent",
                                model_spec.model_id,
                            ],
                            metadata={
                                "agent_id": str(agent_id),
                                "leta_id": str(leta_id),
                                "workspace_id": str(workspace_id),
                                "run_id": str(run_id),
                                "prompt_hash": prompt_version_hash(is_root),
                            },
                        )
                    )
                outcome_label = "completed"
                try:
                    if snapshot.next and not orphans:
                        out: object = await compiled.ainvoke(None, config, context=rt)  # pyright: ignore[reportUnknownMemberType]
                    else:
                        initial_state: AgentState = {
                            "messages": [],
                            "inbox_cursor": final_cursor,
                        }
                        out = await compiled.ainvoke(initial_state, config, context=rt)  # pyright: ignore[reportUnknownMemberType]
                    if is_str_mapping(out):
                        raw_out_cursor = out.get("inbox_cursor")
                        if isinstance(raw_out_cursor, int):
                            return raw_out_cursor
                    return final_cursor
                except asyncio.CancelledError:
                    outcome_label = "cancelled"
                    raise
                except Exception:
                    outcome_label = "failed"
                    raise
                finally:
                    if lf is not None:
                        try:
                            lf.score_current_trace(
                                name="run_outcome",
                                value=outcome_label,
                                data_type="CATEGORICAL",
                            )
                            lf.score_current_trace(
                                name="llm_calls",
                                value=float(rt.usage.llm_calls),
                                data_type="NUMERIC",
                            )
                            lf.score_current_trace(
                                name="cost_usd",
                                value=round(rt.usage.cost_usd, 6),
                                data_type="NUMERIC",
                            )
                        except Exception:
                            logger.debug("langfuse score emit failed", exc_info=True)

        graph_task = asyncio.create_task(_run_graph())

        try:
            final_cursor = await graph_task
        except asyncio.CancelledError:
            if lease_lost:
                raise LeaseLostError(f"lost lease for agent {agent_id}") from None
            raise

        reported_cursor, latest_wake_seq = await services.inbox.compute_wake_cursors(
            agent_id, final_cursor
        )

        return RunOutcome(
            inbox_cursor=reported_cursor,
            latest_wake_seq=latest_wake_seq,
        )
    finally:
        for bg_task in (hb_task, lease_task):
            bg_task.cancel()
            try:
                await bg_task
            except asyncio.CancelledError, Exception:
                pass

        if rt.precomputed is not None and rt.precomputed.task is not None:
            if not rt.precomputed.task.done():
                rt.precomputed.task.cancel()
                try:
                    await rt.precomputed.task
                except asyncio.CancelledError, Exception:
                    pass

        caller = CallerContext(
            workspace_id=workspace_id,
            leta_id=leta_id,
            agent_id=agent_id,
            handle=handle,
            name=rt.agent_name,
            is_root=is_root,
        )
        for addr in list(rt.active_typing):
            rt.active_typing.discard(addr)
            await router.set_typing(caller, addr, False)

        await fs.close()
        await release_lease(services.db, agent_id, lease_token)
