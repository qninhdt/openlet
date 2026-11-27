from __future__ import annotations

import logging
import time
from typing import Literal
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langgraph.runtime import Runtime

from ...activity import StreamCoalescer
from ...db import json_value
from ...runs import record_run_usage
from ..compaction import (
    estimate_prompt_tokens,
    maybe_start_background_compaction,
)
from ..content import extract_chunk_reasoning_delta, extract_chunk_text_delta
from ..media import bound_history_images
from ..prompts import render_system_prompt
from ..retry import ContextOverflowError, compute_output_limit, invoke_with_retry
from ..state import (
    AgentState,
    AgentStateUpdate,
    RuntimeContext,
    UsageTotals,
    build_chat_model,
    compute_cost_usd,
)

logger = logging.getLogger(__name__)

LENGTH_CONTINUATION_PROMPT = (
    "Your last response hit the output token limit (stop reason: length). "
    "Do not apologize, recap, or repeat yourself. Break the remaining work into smaller pieces."
)


class ContextLimitError(RuntimeError):
    """Non-retryable Temporal error when context still overflows after compaction."""


async def _record_step_usage(rt: RuntimeContext, msg: AIMessage) -> None:
    meta = msg.usage_metadata
    delta = UsageTotals()
    if meta is not None:
        in_tok = int(meta.get("input_tokens", 0) or 0)
        out_tok = int(meta.get("output_tokens", 0) or 0)
        in_details = meta.get("input_token_details") or {}
        out_details = meta.get("output_token_details") or {}
        cached = int(in_details.get("cache_read", 0) or 0)
        reasoning = int(out_details.get("reasoning", 0) or 0)
        cost = compute_cost_usd(
            rt.model_spec,
            input_tokens=in_tok,
            cached_input_tokens=cached,
            output_tokens=out_tok,
        )
        delta.add(
            input_tokens=in_tok,
            cached_input_tokens=cached,
            output_tokens=out_tok,
            reasoning_tokens=reasoning,
            cost_usd=cost,
            llm_calls=1,
        )
    else:
        delta.add(llm_calls=1)

    rt.usage.merge(delta)
    try:
        await record_run_usage(
            rt.services.db,
            rt.run_id,
            input_tokens=delta.input_tokens,
            cached_input_tokens=delta.cached_input_tokens,
            output_tokens=delta.output_tokens,
            reasoning_tokens=delta.reasoning_tokens,
            cost_usd=delta.cost_usd,
            llm_calls=delta.llm_calls,
        )
    except Exception:
        logger.warning("failed to persist model usage to runs", exc_info=True)


async def model_node(
    state: AgentState, runtime: Runtime[RuntimeContext]
) -> AgentStateUpdate:
    """Stream LiteLLM response -> 50ms Centrifugo deltas, persist activity & usage."""
    rt = runtime.context
    model_cfg = rt.services.settings.model
    if (
        model_cfg.max_steps_per_run is not None
        and rt.step_count >= model_cfg.max_steps_per_run
    ):
        raise RuntimeError(
            f"agent reached max_steps_per_run ({model_cfg.max_steps_per_run})"
        )

    system_prompt = render_system_prompt(rt)
    bounded_history = bound_history_images(
        list(state["messages"]), rt.services.settings.media
    )
    est = estimate_prompt_tokens(
        bounded_history,
        model_cfg,
        system_prompt=system_prompt,
        model_id=rt.model_spec.model_id,
    )
    if rt.cycle_start_tokens is None:
        rt.cycle_start_tokens = est.total

    max_tokens = compute_output_limit(
        rt.model_spec,
        measured_tokens=est.measured,
        estimated_tokens=est.estimated,
        cfg=model_cfg,
    )
    llm = build_chat_model(
        rt.services,
        rt.model_spec,
        rt.reasoning_effort,
        max_tokens=max_tokens,
        streaming=True,
    )
    runnable = (
        llm.bind_tools(  # pyright: ignore[reportUnknownMemberType]
            list(rt.tools.values())
        )
        if rt.tools
        else llm
    )
    prompt_messages: list[BaseMessage] = [
        SystemMessage(content=system_prompt),
        *bounded_history,
    ]

    coalescer = StreamCoalescer(
        rt.emitter,
        leta_id=rt.leta_id,
        agent_id=rt.agent_id,
        run_id=rt.run_id,
    )
    output_started = False
    reasoning_buf: list[str] = []

    async def _stream_once() -> AIMessage:
        nonlocal output_started
        combined: AIMessageChunk | None = None
        async for raw_chunk in runnable.astream(prompt_messages):
            if not isinstance(raw_chunk, AIMessageChunk):
                continue
            r_delta = extract_chunk_reasoning_delta(raw_chunk)
            if r_delta:
                output_started = True
                reasoning_buf.append(r_delta)
                coalescer.push("stream.thinking_delta", r_delta)
            t_delta = extract_chunk_text_delta(raw_chunk)
            if t_delta:
                output_started = True
                coalescer.push("stream.text_delta", t_delta)
            for tc_chunk in raw_chunk.tool_call_chunks:
                args_delta = tc_chunk.get("args") or ""
                cid = tc_chunk.get("id")
                if args_delta:
                    output_started = True
                    coalescer.push(
                        "stream.tool_args_delta",
                        str(args_delta),
                        tool_call_id=str(cid) if cid else None,
                    )
            combined = raw_chunk if combined is None else combined + raw_chunk

        if combined is None:
            return AIMessage(content="", id=str(uuid4()))

        extra_kw = dict(combined.additional_kwargs)
        extra_kw["openlet_created_at"] = time.time()
        extra_kw["openlet_model_id"] = rt.model_spec.model_id
        if reasoning_buf and "reasoning_content" not in extra_kw:
            extra_kw["reasoning_content"] = "".join(reasoning_buf)

        return AIMessage(
            id=combined.id or str(uuid4()),
            content=combined.content,
            tool_calls=list(combined.tool_calls),
            invalid_tool_calls=list(combined.invalid_tool_calls),
            additional_kwargs=extra_kw,
            response_metadata=dict(combined.response_metadata),
            usage_metadata=combined.usage_metadata,
        )

    try:
        ai_msg = await invoke_with_retry(
            _stream_once,
            cfg=model_cfg.retry,
            has_output_started=lambda: output_started,
        )
    except ContextOverflowError as exc:
        await coalescer.close()
        if not rt.overflow_recovered_this_step:
            rt.overflow_recovered_this_step = True
            rt.pending_overflow_compact = True
            return {}
        raise ContextLimitError(
            f"context window exceeded even after overflow compaction: {exc}"
        ) from exc
    finally:
        await coalescer.close()

    rt.step_count += 1
    rt.overflow_recovered_this_step = False
    await _record_step_usage(rt, ai_msg)

    text = ai_msg.text.strip()
    reasoning_text = (
        "".join(reasoning_buf).strip()
        or str(ai_msg.additional_kwargs.get("reasoning_content") or "").strip()
    )

    if text or reasoning_text:
        await rt.emitter.emit(
            leta_id=rt.leta_id,
            agent_id=rt.agent_id,
            run_id=rt.run_id,
            event_type="activity.message",
            data={
                "message_id": ai_msg.id or "",
                "text": text,
                "reasoning": reasoning_text or None,
                "synthetic": False,
            },
        )

    for tc in ai_msg.tool_calls:
        await rt.emitter.emit(
            leta_id=rt.leta_id,
            agent_id=rt.agent_id,
            run_id=rt.run_id,
            event_type="activity.tool_call",
            data={
                "tool_call_id": str(tc.get("id", "")),
                "name": str(tc.get("name", "")),
                "args": json_value(tc.get("args", {})),
            },
        )

    # Check if background compaction should start now that we have a fresh measured anchor.
    updated_history = [*bounded_history, ai_msg]
    post_est = estimate_prompt_tokens(
        updated_history,
        model_cfg,
        system_prompt=system_prompt,
        model_id=rt.model_spec.model_id,
    )
    maybe_start_background_compaction(updated_history, rt, post_est.total)

    finish_reason = str(ai_msg.response_metadata.get("finish_reason") or "").lower()
    if (
        finish_reason == "length"
        and not ai_msg.tool_calls
        and not ai_msg.invalid_tool_calls
    ):
        if rt.length_continuations < model_cfg.max_length_continuations:
            rt.length_continuations += 1
            return {
                "messages": [
                    ai_msg,
                    HumanMessage(content=LENGTH_CONTINUATION_PROMPT),
                ]
            }
        raise RuntimeError(
            "output-limit: model hit max output tokens after maximum length continuations"
        )

    rt.length_continuations = 0
    return {"messages": [ai_msg]}


async def after_model_router(
    state: AgentState, runtime: Runtime[RuntimeContext]
) -> Literal["compact", "tools", "inbox", "__end__"]:
    rt = runtime.context
    if rt.pending_overflow_compact:
        return "compact"
    msgs = state["messages"]
    if not msgs:
        return "__end__"
    last = msgs[-1]
    if isinstance(last, HumanMessage):
        # Synthetic length continuation appended by model_node.
        return "compact"
    if isinstance(last, AIMessage) and (last.tool_calls or last.invalid_tool_calls):
        return "tools"

    # Text-only AIMessage: recheck DB for any newly arrived pending inbox items.
    if await rt.services.inbox.has_pending(rt.agent_id):
        return "inbox"
    return "__end__"
