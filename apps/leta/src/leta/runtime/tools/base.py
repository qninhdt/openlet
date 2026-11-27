"""Shared tool argument base class, type aliases, and StructuredTool factory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID, uuid5

from langchain_core.tools import InjectedToolArg, StructuredTool
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.prebuilt import ToolRuntime
    from openlet_sdk.config import JSON

    from leta.runtime.content import MessageContentBlock
    from leta.runtime.state import AgentState, RuntimeContext

type ToolContent = str | list[MessageContentBlock]
type ToolResult = tuple[ToolContent, dict[str, JSON]]


class ToolArgs(BaseModel):
    """Base Pydantic schema for LangChain StructuredTool inputs with LangGraph ToolRuntime injection."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    runtime: Annotated[Any, InjectedToolArg] = None


def idempotency_key(runtime: ToolRuntime[RuntimeContext, AgentState]) -> UUID:
    """Derive a deterministic idempotency UUID from the agent ID and tool call ID."""
    return uuid5(runtime.context.agent_id, runtime.tool_call_id or "")


def make_tool(
    *,
    name: str,
    description: str,
    args_schema: type[BaseModel],
    coroutine: Callable[..., Awaitable[ToolResult]],
) -> StructuredTool:
    """Create a LangChain ``StructuredTool`` with ``content_and_artifact`` response format."""
    return StructuredTool.from_function(
        coroutine=coroutine,
        name=name,
        description=description,
        args_schema=args_schema,
        response_format="content_and_artifact",
    )
