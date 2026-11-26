from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID, uuid5

from langchain_core.tools import InjectedToolArg, StructuredTool
from langgraph.prebuilt import ToolRuntime
from openlet_sdk.config import JSON
from pydantic import BaseModel, ConfigDict

from ..state import AgentState, RuntimeContext

type ToolContent = str | list[dict[str, Any]]
type ToolResult = tuple[ToolContent, dict[str, JSON]]


class ToolArgs(BaseModel):
    """Base Pydantic schema for LangChain StructuredTool inputs with LangGraph ToolRuntime injection."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    runtime: Annotated[Any, InjectedToolArg] = None


def idempotency_key(runtime: ToolRuntime[RuntimeContext, AgentState]) -> UUID:
    return uuid5(runtime.context.agent_id, runtime.tool_call_id or "")


def make_tool(
    *,
    name: str,
    description: str,
    args_schema: type[BaseModel],
    coroutine: Callable[..., Awaitable[ToolResult]],
) -> StructuredTool:
    return StructuredTool.from_function(
        coroutine=coroutine,
        name=name,
        description=description,
        args_schema=args_schema,
        response_format="content_and_artifact",
    )
