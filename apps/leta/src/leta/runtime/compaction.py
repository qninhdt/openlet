from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Literal, cast

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from openlet_sdk.config import JSON

from ..config import CompactionConfig, ModelConfig, ModelSpec
from ..hitl.service import list_leta_hitl
from ..runs import record_run_usage
from ..schedules.service import list_schedules
from ..subagents.service import list_active_subagents_status
from .prompts import render_system_prompt
from .retry import ContextOverflowError, compute_output_limit, retry_one_shot
from .state import (
    AgentState,
    PrecomputedCompaction,
    RuntimeContext,
    UsageTotals,
    build_chat_model,
    compute_cost_usd,
)

logger = logging.getLogger(__name__)

CHECKPOINT_OPEN = "<conversation-checkpoint>"
CHECKPOINT_CLOSE = "</conversation-checkpoint>"

SUMMARY_SECTIONS = (
    "## Objective",
    "## Requirements",
    "## Decisions",
    "## Work State",
    "## Next Move",
    "## Relevant Files",
    "## Important Context",
)

NUDGE_PROMPT = (
    "The previous response did not fill in the required summary template. "
    "Do not call tools. Return the summary as text using the exact section "
    "headings from the template."
)


def is_checkpoint_message(msg: BaseMessage) -> bool:
    return isinstance(msg, HumanMessage) and msg.text.lstrip().startswith(
        CHECKPOINT_OPEN
    )


def estimate_text_tokens(text: str, chars_per_token: int = 4) -> int:
    if not text:
        return 0
    return max(0, round(len(text) / max(1, chars_per_token)))


def estimate_message_tokens(msg: BaseMessage, cfg: ModelConfig) -> int:
    total = 0
    content = msg.content
    if isinstance(content, str):
        total += estimate_text_tokens(content, cfg.chars_per_token)
    else:
        for block in content:
            if isinstance(block, str):
                total += estimate_text_tokens(block, cfg.chars_per_token)
            else:
                d = cast(dict[str, object], block)
                btype = str(d.get("type", ""))
                if btype == "text":
                    total += estimate_text_tokens(
                        str(d.get("text", "")), cfg.chars_per_token
                    )
                elif btype == "image_url":
                    total += cfg.image_token_estimate
                elif btype in ("file", "document", "pdf"):
                    total += cfg.pdf_token_estimate
                else:
                    total += estimate_text_tokens(
                        json.dumps(d, default=str), cfg.chars_per_token
                    )
    if isinstance(msg, AIMessage) and msg.tool_calls:
        total += estimate_text_tokens(
            json.dumps(msg.tool_calls, default=str), cfg.chars_per_token
        )
    return total


@dataclass(frozen=True, slots=True)
class PromptTokenEstimate:
    measured: int
    estimated: int
    anchor_index: int | None

    @property
    def total(self) -> int:
        return self.measured + self.estimated


def estimate_prompt_tokens(
    messages: Sequence[BaseMessage],
    model_cfg: ModelConfig,
    *,
    system_prompt: str = "",
    model_id: str | None = None,
) -> PromptTokenEstimate:
    """Anchor-based token estimator matching OpenCode v2."""
    anchor_idx: int | None = None
    anchor_measured = 0
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if not isinstance(msg, AIMessage):
            continue
        meta_model = msg.additional_kwargs.get("openlet_model_id")
        if model_id and meta_model and str(meta_model) != model_id:
            continue
        usage = msg.usage_metadata
        if usage is not None:
            in_tok = int(usage.get("input_tokens", 0) or 0)
            out_tok = int(usage.get("output_tokens", 0) or 0)
            if in_tok + out_tok > 0:
                anchor_idx = idx
                anchor_measured = in_tok + out_tok
                break

    if anchor_idx is None:
        est = estimate_text_tokens(system_prompt, model_cfg.chars_per_token)
        for m in messages:
            est += estimate_message_tokens(m, model_cfg)
        return PromptTokenEstimate(measured=0, estimated=est, anchor_index=None)

    est_after = 0
    for m in messages[anchor_idx + 1 :]:
        est_after += estimate_message_tokens(m, model_cfg)
    return PromptTokenEstimate(
        measured=anchor_measured, estimated=est_after, anchor_index=anchor_idx
    )


def compaction_ceiling(model: ModelSpec, cfg: CompactionConfig) -> float:
    window = model.context_window_tokens
    if window <= 0:
        return math.inf
    reserve = max(
        math.floor(window * cfg.reserve_share),
        cfg.reserve_min_tokens if window >= 2 * cfg.reserve_min_tokens else 0,
    )
    return float(max(1, window - reserve))


def _clamp_codepoints(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[truncated]"


def _clip_middle(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    half = max(1, max_chars // 2)
    omitted = len(text) - (half * 2)
    return f"{text[:half]}\n[... {omitted} characters omitted ...]\n{text[-half:]}"


def serialize_recent_context(
    messages: Sequence[BaseMessage],
    *,
    keep_recent_tokens: int,
    recent_tool_output_max_chars: int,
    chars_per_token: int = 4,
) -> tuple[str, int, int]:
    """Verbatim OpenCode v2 recent-text.ts backward serializer.

    Returns (serialized_text, estimated_tokens, start_index_in_messages).
    """
    if not messages or keep_recent_tokens <= 0:
        return "", 0, len(messages)

    blocks_rev: list[str] = []
    used_tokens = 0
    start_idx = len(messages)

    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if is_checkpoint_message(msg):
            break
        parts: list[str] = []
        if isinstance(msg, HumanMessage):
            txt = msg.text.strip()
            if txt:
                parts.append(f"[User]: {txt}")
        elif isinstance(msg, AIMessage):
            txt = msg.text.strip()
            if txt:
                parts.append(f"[Assistant]: {txt}")
            for tc in msg.tool_calls:
                args_str = json.dumps(
                    tc.get("args", {}), ensure_ascii=False, default=str
                )
                parts.append(f"[Assistant tool call]: {tc.get('name', '')}({args_str})")
        elif isinstance(msg, ToolMessage):
            label = "[Tool error]" if msg.status == "error" else "[Tool result]"
            txt = _clamp_codepoints(msg.text.strip(), recent_tool_output_max_chars)
            parts.append(f"{label}: {txt}")

        if not parts:
            continue
        rendered = "\n".join(parts)
        tok = estimate_text_tokens(rendered, chars_per_token)
        if blocks_rev and used_tokens + tok > keep_recent_tokens:
            break
        blocks_rev.append(rendered)
        used_tokens += tok
        start_idx = idx

    blocks_rev.reverse()
    return "\n\n".join(blocks_rev), used_tokens, start_idx


def _group_exchanges(messages: Sequence[BaseMessage]) -> list[list[BaseMessage]]:
    """Group messages into logical exchanges starting on each HumanMessage."""
    exchanges: list[list[BaseMessage]] = []
    current: list[BaseMessage] = []
    for msg in messages:
        if isinstance(msg, HumanMessage) and current:
            exchanges.append(current)
            current = [msg]
        else:
            current.append(msg)
    if current:
        exchanges.append(current)
    return exchanges


def _render_exchange_at_level(
    exchange: Sequence[BaseMessage], level: int, clip_chars: int
) -> str:
    """Render an exchange across the 5 OpenCode v2 degradation levels (0..4)."""
    if level >= 4:
        return ""
    lines: list[str] = []
    for msg in exchange:
        if isinstance(msg, HumanMessage):
            txt = msg.text.strip()
            if level >= 3:
                txt = _clip_middle(txt, clip_chars)
            if txt:
                lines.append(f"[User]: {txt}")
        elif isinstance(msg, AIMessage):
            if level >= 3:
                continue
            txt = msg.text.strip()
            if txt:
                lines.append(f"[Assistant]: {txt}")
            for tc in msg.tool_calls:
                args_str = json.dumps(
                    tc.get("args", {}), ensure_ascii=False, default=str
                )
                if level >= 2:
                    args_str = _clip_middle(args_str, clip_chars)
                lines.append(f"[Assistant tool call]: {tc.get('name', '')}({args_str})")
        elif isinstance(msg, ToolMessage):
            if level >= 3:
                continue
            is_err = msg.status == "error"
            if level >= 2:
                lines.append(
                    "[Tool error omitted]" if is_err else "[Tool result omitted]"
                )
            else:
                txt = msg.text.strip()
                if level == 1:
                    txt = _clip_middle(txt, clip_chars)
                label = "[Tool error]" if is_err else "[Tool result]"
                lines.append(f"{label}: {txt}")
    return "\n".join(lines)


def flatten_and_drop_oldest(
    messages: Sequence[BaseMessage],
    *,
    room_tokens: int,
    clip_chars: int = 2000,
    chars_per_token: int = 4,
) -> str | None:
    """5-level oldest-first degradation ladder; newest exchange is never omitted."""
    exchanges = _group_exchanges(messages)
    if not exchanges:
        return ""
    renders: list[list[str]] = [
        [_render_exchange_at_level(ex, lvl, clip_chars) for lvl in range(5)]
        for ex in exchanges
    ]
    levels = [0] * len(exchanges)
    total = sum(estimate_text_tokens(r[0], chars_per_token) for r in renders)
    newest = len(exchanges) - 1

    for lvl in (1, 2, 3, 4):
        for idx in range(len(exchanges)):
            if total <= room_tokens:
                break
            if idx == newest and not renders[idx][lvl]:
                continue
            old_tok = estimate_text_tokens(renders[idx][levels[idx]], chars_per_token)
            new_tok = estimate_text_tokens(renders[idx][lvl], chars_per_token)
            total += new_tok - old_tok
            levels[idx] = lvl

    if total > room_tokens:
        # Final emergency clip of the newest exchange if still slightly over budget
        kept = renders[newest][levels[newest]]
        max_chars = max(512, room_tokens * chars_per_token)
        if not kept:
            return None
        omitted = len(exchanges) - 1
        prefix = f"[{omitted} older exchange(s) omitted]\n\n" if omitted > 0 else ""
        return prefix + _clip_middle(kept, max_chars)

    omitted_count = sum(1 for i, lvl in enumerate(levels) if not renders[i][lvl])
    body = "\n\n".join(
        renders[i][levels[i]] for i in range(len(exchanges)) if renders[i][levels[i]]
    )
    if omitted_count > 0:
        return f"[{omitted_count} older exchange(s) omitted]\n\n{body}"
    return body


def build_summary_prompt(*, is_update: bool) -> str:
    mode_note = (
        "This conversation already contains an earlier <conversation-checkpoint>. "
        "Update that summary with all newer progress: newer history always takes precedence; "
        "reconcile Completed, Active, and Blocked; do not reproduce any XML wrapper tags."
        if is_update
        else "Summarize the conversation so work can continue seamlessly without losing any factual detail."
    )
    return (
        f"{mode_note}\n"
        "Do NOT call any tools. Return ONLY Markdown using these exact section headings:\n\n"
        "## Objective\n"
        "## Requirements\n"
        "## Decisions\n"
        "## Work State\n"
        "### Completed\n"
        "### Active\n"
        "### Blocked\n"
        "## Next Move\n"
        "## Relevant Files\n"
        "## Important Context\n\n"
        "Rules:\n"
        "- Preserve ALL verified figures, calculations, table totals, reconciliation facts, "
        "exact file/artifact paths (at most 15 paths in ## Relevant Files), and active reply "
        "addresses (`chat:<conv_id>`, `agent:<handle>`).\n"
        "- Be dense, concrete, and faithful to the evidence in the conversation."
    )


def _has_template_headings(text: str) -> bool:
    return any(heading in text for heading in SUMMARY_SECTIONS)


def _usage_from_ai_message(msg: AIMessage, spec: ModelSpec) -> UsageTotals:
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


async def _invoke_summary_call(
    rt: RuntimeContext,
    prompt_messages: list[BaseMessage],
    *,
    max_tokens: int,
    include_tools: bool,
) -> tuple[str, UsageTotals]:
    llm = build_chat_model(
        rt.services,
        rt.model_spec,
        None,
        max_tokens=max_tokens,
        streaming=False,
    )
    runnable = (
        llm.bind_tools(  # pyright: ignore[reportUnknownMemberType]
            list(rt.tools.values()),
            tool_choice="none",
        )
        if include_tools and rt.tools
        else llm
    )

    async def _call() -> AIMessage:
        return await runnable.ainvoke(prompt_messages)

    with ExitStack() as stack:
        obs = None
        if rt.services.langfuse is not None:
            obs = stack.enter_context(
                rt.services.langfuse.start_as_current_observation(
                    name="leta.compaction.summarize",
                    as_type="generation",
                    model=rt.model_spec.model_id,
                    metadata={"include_tools": include_tools, "max_tokens": max_tokens},
                )
            )
        ai_msg = await retry_one_shot(_call, cfg=rt.services.settings.model.retry)
        usage = _usage_from_ai_message(ai_msg, rt.model_spec)
        text = ai_msg.text.strip()

        if not _has_template_headings(text):
            nudge_msgs = [
                *prompt_messages,
                AIMessage(content=text or "(empty)"),
                HumanMessage(content=NUDGE_PROMPT),
            ]

            async def _nudge() -> AIMessage:
                return await runnable.ainvoke(nudge_msgs)

            ai_msg2 = await retry_one_shot(_nudge, cfg=rt.services.settings.model.retry)
            usage.merge(_usage_from_ai_message(ai_msg2, rt.model_spec))
            text2 = ai_msg2.text.strip()
            if text2:
                text = text2

        if obs is not None:
            obs.update(
                usage_details={
                    "input": usage.input_tokens,
                    "output": usage.output_tokens,
                },
                cost_details={"total": round(usage.cost_usd, 6)},
            )

    return text, usage


async def summarize_messages(
    rt: RuntimeContext,
    messages: Sequence[BaseMessage],
    *,
    prefix_end_idx: int | None = None,
    target_budget: int | None = None,
) -> tuple[str, UsageTotals]:
    """Run OpenCode v2 cache-hot Attempt 1 -> Attempt 2 -> Attempt 3 (5-level flatten) + shrink cascade."""
    comp_cfg = rt.services.settings.compaction
    model_cfg = rt.services.settings.model
    spec = rt.model_spec
    system_prompt = render_system_prompt(rt)
    is_update = any(is_checkpoint_message(m) for m in messages)
    summary_prompt = build_summary_prompt(is_update=is_update)

    window = spec.context_window_tokens or comp_cfg.unknown_window_tokens
    summary_out = max(
        comp_cfg.summary_output_floor,
        compute_output_limit(
            spec,
            measured_tokens=target_budget or int(window * 0.7),
            estimated_tokens=0,
            cfg=model_cfg,
            headroom=0.0,
        ),
    )
    summary_out = min(summary_out, spec.max_output_tokens or model_cfg.output_token_max)
    overhead = (
        estimate_text_tokens(system_prompt, model_cfg.chars_per_token)
        + estimate_text_tokens(summary_prompt, model_cfg.chars_per_token)
        + 1024
    )
    cap_budget = max(2048, window - summary_out - overhead)
    budget = min(cap_budget, target_budget) if target_budget is not None else cap_budget
    total_usage = UsageTotals()

    # Attempt 1: Cache-hot full conversation + tools with tool_choice="none"
    est_full = estimate_prompt_tokens(
        messages, model_cfg, system_prompt=system_prompt, model_id=spec.model_id
    ).total
    if est_full <= budget:
        try:
            text, u = await _invoke_summary_call(
                rt,
                [
                    SystemMessage(content=system_prompt),
                    *messages,
                    HumanMessage(content=summary_prompt),
                ],
                max_tokens=summary_out,
                include_tools=True,
            )
            total_usage.merge(u)
            if text:
                return text, total_usage
        except ContextOverflowError:
            pass

    # Attempt 2: Cache-hot prefix without tail
    if prefix_end_idx is not None and 0 < prefix_end_idx < len(messages):
        prefix = messages[:prefix_end_idx]
        est_prefix = estimate_prompt_tokens(
            prefix, model_cfg, system_prompt=system_prompt, model_id=spec.model_id
        ).total
        if est_prefix <= budget:
            try:
                text, u = await _invoke_summary_call(
                    rt,
                    [
                        SystemMessage(content=system_prompt),
                        *prefix,
                        HumanMessage(content=summary_prompt),
                    ],
                    max_tokens=summary_out,
                    include_tools=True,
                )
                total_usage.merge(u)
                if text:
                    return text, total_usage
            except ContextOverflowError:
                pass

    # Attempt 3: Flattened transcript with 5-level oldest-first degradation + shrink_steps cascade
    source_msgs = (
        messages[:prefix_end_idx]
        if prefix_end_idx is not None and 0 < prefix_end_idx < len(messages)
        else messages
    )
    shrink_factors = (1.0, *comp_cfg.shrink_steps)
    last_err: Exception | None = None
    for factor in shrink_factors:
        room = max(2048, math.floor(budget * factor))
        flattened = flatten_and_drop_oldest(
            source_msgs,
            room_tokens=room,
            clip_chars=comp_cfg.transcript_clip_chars,
            chars_per_token=model_cfg.chars_per_token,
        )
        if not flattened:
            continue
        try:
            text, u = await _invoke_summary_call(
                rt,
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(
                        content=f"Conversation transcript:\n\n{flattened}\n\n{summary_prompt}"
                    ),
                ],
                max_tokens=summary_out,
                include_tools=False,
            )
            total_usage.merge(u)
            if text:
                return text, total_usage
        except ContextOverflowError as exc:
            last_err = exc
            continue

    raise ContextOverflowError(
        f"compaction failed after shrink cascade: {last_err or 'empty summary'}"
    )


async def build_live_db_snapshots(rt: RuntimeContext) -> tuple[str, str, str]:
    """Query fresh <subagents>, <pending-hitl>, and <active-schedules> from Postgres."""
    comp_cfg = rt.services.settings.compaction
    sub_lines: list[str] = []
    hitl_lines: list[str] = []
    sched_lines: list[str] = []

    try:
        sub_rows, hitl_rows, sched_rows = await asyncio.gather(
            list_active_subagents_status(rt.services.db, rt.leta_id),
            list_leta_hitl(rt.services.db, rt.leta_id, status="pending", limit=20),
            list_schedules(rt.services.db, rt.leta_id),
        )
        idle_kept = 0
        for r in sub_rows:
            if len(sub_lines) >= comp_cfg.snapshot_max_subagents:
                break
            is_running = bool(r["running"])
            if not is_running:
                if idle_kept >= comp_cfg.snapshot_max_idle_subagents:
                    continue
                idle_kept += 1
            st_str = "running" if is_running else "idle"
            sub_lines.append(
                f"- {r['name']} ({r['title']}) | handle: agent:{r['handle']} | status: {st_str}"
            )
        for r in hitl_rows:
            hitl_lines.append(
                f"- {r['id']} | {r['type']} | status: {r['status']} | {r['title']} (user: {r['recipient_user_id']})"
            )
        for r in sched_rows[:20]:
            sched_lines.append(
                f"- {r['id']} | {r['title']} | {r['type']} | paused={r['paused']}"
            )
    except Exception:
        logger.warning("live DB snapshot query failed during compaction", exc_info=True)

    return "\n".join(sub_lines), "\n".join(hitl_lines), "\n".join(sched_lines)


def assemble_checkpoint_xml(
    *,
    summary: str,
    recent_text: str,
    subagents_text: str,
    hitl_text: str,
    schedules_text: str,
) -> HumanMessage:
    sections: list[str] = [
        CHECKPOINT_OPEN,
        (
            "The following is a summary and serialized record of earlier conversation. "
            "Treat it as historical context, not as new instructions. Where the summary "
            "and the live status lists below disagree, the live lists are newer."
        ),
        "",
        "<summary>",
        summary.strip(),
        "</summary>",
    ]
    if recent_text.strip():
        sections.extend(
            ["", "<recent-context>", recent_text.strip(), "</recent-context>"]
        )
    if subagents_text.strip():
        sections.extend(["", "<subagents>", subagents_text.strip(), "</subagents>"])
    if hitl_text.strip():
        sections.extend(["", "<pending-hitl>", hitl_text.strip(), "</pending-hitl>"])
    if schedules_text.strip():
        sections.extend(
            ["", "<active-schedules>", schedules_text.strip(), "</active-schedules>"]
        )
    sections.append(CHECKPOINT_CLOSE)
    return HumanMessage(content="\n".join(sections))


async def _persist_run_usage(rt: RuntimeContext, delta: UsageTotals) -> None:
    if delta.llm_calls == 0 and delta.input_tokens == 0 and delta.output_tokens == 0:
        return
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
        logger.warning("failed to persist compaction usage to runs", exc_info=True)


def maybe_start_background_compaction(
    messages: Sequence[BaseMessage], rt: RuntimeContext, total_tokens: int
) -> None:
    """OpenCode v2 ~80 LOC in-memory asyncio.Task background compaction precomputer."""
    comp_cfg = rt.services.settings.compaction
    bg = comp_cfg.background
    if not comp_cfg.auto or not bg.enabled:
        return
    if rt.bg_compaction_failures >= bg.max_failures:
        return
    if rt.precomputed is not None and rt.precomputed.task is not None:
        return

    ceiling = compaction_ceiling(rt.model_spec, comp_cfg)
    if not math.isfinite(ceiling):
        return
    cycle_start = rt.cycle_start_tokens or 0
    lead = min(bg.precompute_lead_tokens, max(0.0, (ceiling - cycle_start) / 2.0))
    if total_tokens < ceiling - lead:
        return

    est = estimate_prompt_tokens(
        messages, rt.services.settings.model, model_id=rt.model_spec.model_id
    )
    anchor_idx = est.anchor_index
    if anchor_idx is None or anchor_idx <= 0:
        return
    anchor = messages[anchor_idx]
    anchor_id = anchor.id
    if not anchor_id:
        return

    created_ts = anchor.additional_kwargs.get("openlet_created_at")
    if isinstance(created_ts, (int, float)):
        age = time.time() - float(created_ts)
        if age > (bg.cache_lifetime_seconds - bg.cache_margin_seconds):
            return

    snapshot = list(messages[:anchor_idx])
    first_id = messages[0].id if messages else None
    tail_limit = max(2048, math.floor(ceiling * bg.tail_share))

    async def _bg_worker() -> tuple[str, UsageTotals]:
        return await summarize_messages(rt, snapshot)

    task = asyncio.create_task(_bg_worker())
    rt.precomputed = PrecomputedCompaction(
        first_id=first_id,
        keep_id=anchor_id,
        tail_limit=tail_limit,
        failures=rt.bg_compaction_failures,
        task=task,
    )


async def run_compaction(
    state: AgentState,
    rt: RuntimeContext,
    *,
    reason: Literal["auto", "overflow"],
) -> tuple[list[BaseMessage], dict[str, JSON]] | None:
    """Run foreground (or adopt precomputed background) compaction and emit RemoveMessage + checkpoint."""
    messages = state["messages"]
    if not messages or is_checkpoint_message(messages[-1]):
        return None

    comp_cfg = rt.services.settings.compaction
    model_cfg = rt.services.settings.model
    system_prompt = render_system_prompt(rt)
    before_est = estimate_prompt_tokens(
        messages,
        model_cfg,
        system_prompt=system_prompt,
        model_id=rt.model_spec.model_id,
    )
    before_tokens = before_est.total

    summary_text: str | None = None
    effective_reason: Literal["auto", "overflow", "background"] = reason
    recent_slice: Sequence[BaseMessage] = messages

    # Try adopting a valid precomputed background compaction first (only on auto trigger).
    pre = rt.precomputed
    if reason == "auto" and pre is not None and pre.task is not None:
        first_matches = (messages[0].id if messages else None) == pre.first_id
        keep_idx = next(
            (i for i, m in enumerate(messages) if m.id == pre.keep_id), None
        )
        if first_matches and keep_idx is not None:
            tail_tokens = sum(
                estimate_message_tokens(m, model_cfg) for m in messages[keep_idx:]
            )
            if tail_tokens <= pre.tail_limit:
                try:
                    summary_text, bg_usage = await pre.task
                    await _persist_run_usage(rt, bg_usage)
                    effective_reason = "background"
                    recent_slice = messages[keep_idx:]
                except Exception:
                    rt.bg_compaction_failures += 1
                    logger.warning(
                        "background compaction failed; falling back to synchronous",
                        exc_info=True,
                    )
        if not pre.task.done():
            pre.task.cancel()
        rt.precomputed = None
    elif pre is not None:
        if pre.task is not None and not pre.task.done():
            pre.task.cancel()
        rt.precomputed = None

    recent_text, kept_recent_tokens, keep_start_idx = serialize_recent_context(
        recent_slice,
        keep_recent_tokens=comp_cfg.keep_recent_tokens,
        recent_tool_output_max_chars=comp_cfg.recent_tool_output_max_chars,
        chars_per_token=model_cfg.chars_per_token,
    )

    if summary_text is None:
        target_budget: int | None = None
        if reason == "overflow":
            shrink = comp_cfg.shrink_steps[0] if comp_cfg.shrink_steps else 0.85
            target_budget = max(2048, math.floor(before_tokens * shrink))
        summary_text, fg_usage = await summarize_messages(
            rt,
            messages,
            prefix_end_idx=keep_start_idx if keep_start_idx > 0 else None,
            target_budget=target_budget,
        )
        await _persist_run_usage(rt, fg_usage)

    subagents_text, hitl_text, schedules_text = await build_live_db_snapshots(rt)
    checkpoint_msg = assemble_checkpoint_xml(
        summary=summary_text,
        recent_text=recent_text,
        subagents_text=subagents_text,
        hitl_text=hitl_text,
        schedules_text=schedules_text,
    )
    after_tokens = estimate_message_tokens(
        checkpoint_msg, model_cfg
    ) + estimate_text_tokens(system_prompt, model_cfg.chars_per_token)
    rt.cycle_start_tokens = after_tokens

    removals: list[BaseMessage] = [
        RemoveMessage(id=m.id) for m in messages if m.id is not None
    ]
    delta: list[BaseMessage] = [*removals, checkpoint_msg]
    info: dict[str, JSON] = {
        "reason": effective_reason,
        "before_tokens": before_tokens,
        "after_tokens": after_tokens,
        "kept_recent_tokens": kept_recent_tokens,
        "summary_preview": summary_text[:500],
    }
    return delta, info
