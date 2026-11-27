from __future__ import annotations

import json
from collections.abc import Mapping

from openlet_sdk.types import JSON

from ..hitl.models import (
    ApprovalPayload,
    ApprovalResponse,
    AskPayload,
    AskResponse,
    HitlOutcome,
)


def format_hitl_response(
    payload: AskPayload | ApprovalPayload | Mapping[str, JSON] | None,
    response: AskResponse | ApprovalResponse | Mapping[str, JSON] | str | None,
) -> str:
    """Render a HITL response as clean human-readable UTF-8 text."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response

    lines: list[str] = []
    raw_note: str | None = None

    if isinstance(response, AskResponse):
        raw_note = response.note
        if response.answers:
            q_meta: dict[str, tuple[str, dict[str, str]]] = {}
            if isinstance(payload, AskPayload):
                for q in payload.questions:
                    q_meta[q.id] = (q.text, {o.id: o.label for o in q.options})

            lines.append("Answers:")
            for qid, val in response.answers.items():
                qtext, opt_labels = q_meta.get(qid, ("", {}))
                label = f"{qid} ({qtext})" if qtext else qid
                if isinstance(val, list):
                    val_text = ", ".join(opt_labels.get(v, v) for v in val)
                else:
                    val_text = opt_labels.get(val, val)
                if "\n" in val_text:
                    indented = "\n".join(f"  {ln}" for ln in val_text.splitlines())
                    lines.append(f"- {label}:\n{indented}")
                else:
                    lines.append(f"- {label}: {val_text}")
    elif isinstance(response, ApprovalResponse):
        raw_note = response.note
    else:
        return json.dumps(dict(response), ensure_ascii=False, default=str)

    if raw_note and raw_note.strip():
        note = raw_note.strip()
        lines.append(f"Note:\n{note}" if "\n" in note else f"Note: {note}")

    if not lines:
        return json.dumps(
            response.model_dump(exclude_none=True),
            ensure_ascii=False,
            default=str,
        )
    return "\n".join(lines)


def format_hitl_outcome_attr(outcome: HitlOutcome | str | None) -> str:
    """Short single-line outcome status suitable for XML attributes and UI summaries."""
    if outcome is None or isinstance(outcome, str):
        return outcome or ""
    if outcome.applied:
        role = (outcome.role or "").strip()
        return f"applied ({role})" if role else "applied"
    reason = (outcome.reason or "failed").strip()
    return f"not_applied: {reason}"


def format_hitl_outcome(outcome: HitlOutcome | str | None) -> str:
    """Human-readable outcome summary for agent text outputs."""
    if outcome is None or isinstance(outcome, str):
        return outcome or ""
    if outcome.applied:
        details: list[str] = []
        if outcome.role:
            details.append(f"role={outcome.role}")
        if outcome.storage_id:
            details.append(f"storage_id={outcome.storage_id}")
        suffix = f" ({', '.join(details)})" if details else ""
        return f"Access granted{suffix}."
    reason = (outcome.reason or "unknown reason").strip()
    return f"Not applied: {reason}."
