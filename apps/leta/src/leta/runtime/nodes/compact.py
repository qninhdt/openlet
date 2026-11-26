from __future__ import annotations

import math

from langgraph.runtime import Runtime

from ..compaction import (
    compaction_ceiling,
    estimate_prompt_tokens,
    is_checkpoint_message,
    run_compaction,
)
from ..prompts import render_system_prompt
from ..state import AgentState, RuntimeContext


async def compact_node(
    state: AgentState, runtime: Runtime[RuntimeContext]
) -> dict[str, object]:
    """Check context ceiling (or overflow flag) and compact into <conversation-checkpoint>."""
    rt = runtime.context
    messages = state["messages"]
    if not messages or is_checkpoint_message(messages[-1]):
        rt.pending_overflow_compact = False
        return {}

    comp_cfg = rt.services.settings.compaction
    model_cfg = rt.services.settings.model

    if rt.pending_overflow_compact:
        rt.pending_overflow_compact = False
        outcome = await run_compaction(state, rt, reason="overflow")
    else:
        if not comp_cfg.auto:
            return {}
        ceiling = compaction_ceiling(rt.model_spec, comp_cfg)
        if not math.isfinite(ceiling):
            return {}
        system_prompt = render_system_prompt(rt)
        est = estimate_prompt_tokens(
            messages,
            model_cfg,
            system_prompt=system_prompt,
            model_id=rt.model_spec.model_id,
        )
        if rt.cycle_start_tokens is None:
            rt.cycle_start_tokens = est.total
        if est.total < ceiling:
            return {}
        outcome = await run_compaction(state, rt, reason="auto")

    if outcome is None:
        return {}
    delta_msgs, info = outcome
    await rt.emitter.emit(
        leta_id=rt.leta_id,
        agent_id=rt.agent_id,
        run_id=rt.run_id,
        event_type="activity.compacted",
        data=info,
    )
    return {"messages": delta_msgs}
