"""LangGraph StateGraph builder for the 5-node Openlet Leta agent loop."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]

from leta.runtime.nodes.compact import compact_node
from leta.runtime.nodes.end_turn import end_turn_node
from leta.runtime.nodes.inbox import after_inbox_router, inbox_node
from leta.runtime.nodes.model import after_model_router, model_node
from leta.runtime.nodes.tools import after_tools_router, build_tools_node
from leta.runtime.state import AgentState, RuntimeContext

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.tools import BaseTool
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph  # pyright: ignore[reportMissingTypeStubs]


def build_agent_graph(
    tools: Sequence[BaseTool],
    *,
    checkpointer: BaseCheckpointSaver[str] | None = None,
) -> CompiledStateGraph[AgentState, RuntimeContext, AgentState, AgentState]:
    """Build the explicit 5-node Openlet Leta StateGraph with native RuntimeContext injection."""
    graph: StateGraph[AgentState, RuntimeContext, AgentState, AgentState] = StateGraph(
        AgentState, context_schema=RuntimeContext
    )

    graph.add_node("inbox", inbox_node)  # pyright: ignore[reportUnknownMemberType]
    graph.add_node("compact", compact_node)  # pyright: ignore[reportUnknownMemberType]
    graph.add_node("model", model_node)  # pyright: ignore[reportUnknownMemberType]
    graph.add_node("tools", build_tools_node(tools))  # pyright: ignore[reportUnknownMemberType]
    graph.add_node("end_turn", end_turn_node)  # pyright: ignore[reportUnknownMemberType]

    graph.add_edge(START, "inbox")
    graph.add_conditional_edges(
        "inbox",
        after_inbox_router,
        {"compact": "compact", "__end__": END},
    )
    graph.add_edge("compact", "model")
    graph.add_conditional_edges(
        "model",
        after_model_router,
        {
            "compact": "compact",
            "tools": "tools",
            "inbox": "inbox",
            "__end__": END,
        },
    )
    graph.add_conditional_edges(
        "tools",
        after_tools_router,
        {"end_turn": "end_turn", "inbox": "inbox"},
    )
    graph.add_edge("end_turn", END)

    return graph.compile(checkpointer=checkpointer)  # pyright: ignore[reportUnknownMemberType]
