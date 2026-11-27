"""LangGraph fast-exit end-turn node emitting a synthetic final assistant message."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from langchain_core.messages import AIMessage

from leta.channels.base import CallerContext

if TYPE_CHECKING:
    from langgraph.runtime import Runtime

    from leta.runtime.state import AgentState, AgentStateUpdate, RuntimeContext

SYNTHETIC_END_TURN_TEXT = "Message delivered. Standing by."


async def end_turn_node(
    state: AgentState, runtime: Runtime[RuntimeContext]
) -> AgentStateUpdate:
    """Zero-LLM-call fast exit closing the turn on a valid assistant message."""
    _ = state
    rt = runtime.context
    caller = CallerContext(
        workspace_id=rt.workspace_id,
        leta_id=rt.leta_id,
        agent_id=rt.agent_id,
        handle=rt.handle,
        name=rt.agent_name,
        is_root=rt.is_root,
    )
    for addr in list(rt.active_typing):
        rt.active_typing.discard(addr)
        await rt.router.set_typing(caller, addr, active=False)

    msg = AIMessage(
        id=str(uuid4()),
        content=SYNTHETIC_END_TURN_TEXT,
        additional_kwargs={"openlet_synthetic": True},
    )
    await rt.emitter.emit(
        leta_id=rt.leta_id,
        agent_id=rt.agent_id,
        run_id=rt.run_id,
        event_type="activity.message",
        data={
            "message_id": msg.id or "",
            "text": SYNTHETIC_END_TURN_TEXT,
            "reasoning": None,
            "synthetic": True,
        },
    )
    return {"messages": [msg]}
