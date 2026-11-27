"""LangGraph checkpoint state, mutable runtime context, and LLM client helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, TypedDict

from langchain_core.messages import BaseMessage  # noqa: TC002  # Evaluated at runtime by LangGraph StateGraph.get_type_hints.
from langchain_litellm import ChatLiteLLM
from langgraph.graph.message import (  # pyright: ignore[reportMissingTypeStubs]
    add_messages,
)
from openlet_sdk.config import secret

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Sequence
    from uuid import UUID

    from langchain_core.messages import AIMessage
    from langchain_core.tools import BaseTool
    from openlet_sdk.config import JSON, ReasoningEffort

    from leta.activity import ActivityEmitter
    from leta.channels.router import ChannelRouter
    from leta.config import ModelSpec, Services
    from leta.filesystem.workspace import Filesystem


class AgentState(TypedDict):
    """Minimal persisted LangGraph checkpoint state (no turn_ended flag)."""

    messages: Annotated[list[BaseMessage], add_messages]
    inbox_cursor: int


class AgentStateUpdate(TypedDict, total=False):
    """Partial state patch returned by LangGraph runtime nodes."""

    messages: Sequence[BaseMessage]
    inbox_cursor: int


@dataclass(slots=True)
class UsageTotals:
    """Mutable token, cost, and LLM-call accumulator for a run."""

    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0

    def add(
        self,
        *,
        input_tokens: int = 0,
        cached_input_tokens: int = 0,
        output_tokens: int = 0,
        reasoning_tokens: int = 0,
        cost_usd: float = 0.0,
        llm_calls: int = 1,
    ) -> None:
        """Accumulate clamped usage metrics from a single LLM invocation."""
        self.input_tokens += max(0, input_tokens)
        self.cached_input_tokens += max(0, cached_input_tokens)
        self.output_tokens += max(0, output_tokens)
        self.reasoning_tokens += max(0, reasoning_tokens)
        self.cost_usd += max(0.0, cost_usd)
        self.llm_calls += max(0, llm_calls)

    def merge(self, other: UsageTotals) -> None:
        """Add another ``UsageTotals`` instance into this accumulator."""
        self.input_tokens += other.input_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.output_tokens += other.output_tokens
        self.reasoning_tokens += other.reasoning_tokens
        self.cost_usd += other.cost_usd
        self.llm_calls += other.llm_calls

    def to_dict(self) -> dict[str, int | float]:
        """Serialize accumulated usage totals to a JSON-friendly dictionary."""
        return {
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "llm_calls": self.llm_calls,
        }


def compute_cost_usd(
    spec: ModelSpec,
    *,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
) -> float:
    """Calculate USD cost from token counts and model pricing rates."""
    uncached = max(0, input_tokens - cached_input_tokens)
    cached_rate = spec.cache_read_input_token_cost or spec.input_cost_per_token
    return (
        uncached * spec.input_cost_per_token
        + cached_input_tokens * cached_rate
        + output_tokens * spec.output_cost_per_token
    )


def usage_from_ai_message(msg: AIMessage, spec: ModelSpec) -> UsageTotals:
    """Extract ``UsageTotals`` from an ``AIMessage``'s ``usage_metadata``."""
    u = UsageTotals()
    meta = msg.usage_metadata
    if meta is None:
        u.add(llm_calls=1)
        return u
    in_tok = int(meta.get("input_tokens", 0) or 0)
    out_tok = int(meta.get("output_tokens", 0) or 0)
    in_details = meta.get("input_token_details") or {}
    out_details = meta.get("output_token_details") or {}
    cached = int(in_details.get("cache_read", 0) or 0)
    reasoning = int(out_details.get("reasoning", 0) or 0)
    cost = compute_cost_usd(
        spec,
        input_tokens=in_tok,
        cached_input_tokens=cached,
        output_tokens=out_tok,
    )
    u.add(
        input_tokens=in_tok,
        cached_input_tokens=cached,
        output_tokens=out_tok,
        reasoning_tokens=reasoning,
        cost_usd=cost,
        llm_calls=1,
    )
    return u


@dataclass(slots=True)
class PrecomputedCompaction:
    """Handle and anchor metadata for an in-flight background compaction task."""

    first_id: str | None
    keep_id: str
    tail_limit: int
    failures: int = 0
    task: asyncio.Task[tuple[str, UsageTotals]] | None = None


@dataclass(slots=True)
class RuntimeContext:
    """Per-turn dependency and mutable execution state injected into LangGraph nodes."""

    agent_id: UUID
    leta_id: UUID
    workspace_id: UUID
    storage_id: UUID
    is_root: bool
    handle: str
    agent_name: str
    agent_title: str
    agent_description: str
    custom_instructions: str
    parent_handle: str
    model_spec: ModelSpec
    reasoning_effort: ReasoningEffort
    run_id: UUID
    services: Services
    emitter: ActivityEmitter
    fs: Filesystem
    router: ChannelRouter
    tools: dict[str, BaseTool]
    step_count: int = 0
    drained_this_step: bool = False
    length_continuations: int = 0
    overflow_recovered_this_step: bool = False
    pending_overflow_compact: bool = False
    cycle_start_tokens: int | None = None
    usage: UsageTotals = field(default_factory=UsageTotals)
    active_channels: dict[str, float] = field(default_factory=dict[str, float])
    active_typing: set[str] = field(default_factory=set[str])
    precomputed: PrecomputedCompaction | None = None
    bg_compaction_failures: int = 0


def reasoning_kwargs_for_model(
    model_id: str, effort: ReasoningEffort
) -> dict[str, JSON]:
    """Map reasoning_effort cleanly across provider families (OpenAI / Anthropic / Gemini)."""
    if effort is None:
        return {}
    low = model_id.lower()
    if "claude" in low or "anthropic" in low:
        budgets = {"low": 4096, "medium": 10240, "high": 24576, "max": 32768}
        return {
            "thinking": {"type": "enabled", "budget_tokens": budgets.get(effort, 10240)}
        }
    return {"reasoning_effort": effort}


def build_chat_model(
    services: Services,
    model_spec: ModelSpec,
    reasoning_effort: ReasoningEffort,
    *,
    max_tokens: int,
    streaming: bool = True,
) -> ChatLiteLLM:
    """Build a configured ``ChatLiteLLM`` client pointing at the LiteLLM gateway."""
    gw = services.config["models"]["gateway"]
    base_url = gw["base_url"].rstrip("/")
    api_key = secret(gw["api_key"])
    timeout = float(gw["timeout_seconds"])

    model_kwargs: dict[str, object] = {
        "num_retries": 0,
        "stream_options": {"include_usage": True} if streaming else None,
        **reasoning_kwargs_for_model(model_spec.model_id, reasoning_effort),
    }
    clean_kwargs = {k: v for k, v in model_kwargs.items() if v is not None}

    return ChatLiteLLM(
        model=f"openai/{model_spec.model_id}",
        api_base=f"{base_url}/v1",
        api_key=api_key,
        max_tokens=max_tokens,
        max_retries=0,
        streaming=streaming,
        request_timeout=timeout,
        model_kwargs=clean_kwargs,
    )
