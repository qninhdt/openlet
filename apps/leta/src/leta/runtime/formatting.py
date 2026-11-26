from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast


def format_hitl_response(payload: object, response: object) -> str:
    """Render a HITL response as clean human-readable UTF-8 text."""
    if response is None:
        return ""
    if not isinstance(response, Mapping):
        return str(response)
    resp = cast(Mapping[str, object], response)
    lines: list[str] = []

    raw_answers = resp.get("answers")
    if isinstance(raw_answers, Mapping):
        answers = cast(Mapping[str, object], raw_answers)
        q_meta: dict[str, tuple[str, dict[str, str]]] = {}
        if isinstance(payload, Mapping):
            raw_qs = cast(Mapping[str, object], payload).get("questions")
            if isinstance(raw_qs, list):
                for q in cast(list[object], raw_qs):
                    if not isinstance(q, Mapping):
                        continue
                    qd = cast(Mapping[str, object], q)
                    qid = str(qd.get("id") or "")
                    qtext = str(qd.get("text") or "")
                    opts: dict[str, str] = {}
                    raw_opts = qd.get("options")
                    if isinstance(raw_opts, list):
                        for o in cast(list[object], raw_opts):
                            if isinstance(o, Mapping):
                                od = cast(Mapping[str, object], o)
                                oid = str(od.get("id") or "")
                                lbl = str(od.get("label") or "")
                                if oid and lbl:
                                    opts[oid] = lbl
                    if qid:
                        q_meta[qid] = (qtext, opts)

        if answers:
            lines.append("Answers:")
            for qid, raw_val in answers.items():
                q_key = str(qid)
                qtext, opt_labels = q_meta.get(q_key, ("", {}))
                label = f"{q_key} ({qtext})" if qtext else q_key
                if isinstance(raw_val, list):
                    val_text = ", ".join(
                        opt_labels.get(str(v), str(v))
                        for v in cast(list[object], raw_val)
                    )
                else:
                    s_val = str(raw_val)
                    val_text = opt_labels.get(s_val, s_val)
                if "\n" in val_text:
                    indented = "\n".join(f"  {ln}" for ln in val_text.splitlines())
                    lines.append(f"- {label}:\n{indented}")
                else:
                    lines.append(f"- {label}: {val_text}")

    raw_note = resp.get("note")
    if isinstance(raw_note, str) and raw_note.strip():
        note = raw_note.strip()
        if "\n" in note:
            lines.append(f"Note:\n{note}")
        else:
            lines.append(f"Note: {note}")

    if not lines:
        return json.dumps(dict(resp), ensure_ascii=False, default=str)
    return "\n".join(lines)


def format_hitl_outcome_attr(outcome: object) -> str:
    """Short single-line outcome status suitable for XML attributes and UI summaries."""
    if outcome is None:
        return ""
    if isinstance(outcome, str):
        return outcome
    if isinstance(outcome, Mapping):
        om = cast(Mapping[str, object], outcome)
        applied = om.get("applied")
        if applied is True:
            role = str(om.get("role") or "").strip()
            return f"applied ({role})" if role else "applied"
        if applied is False:
            reason = str(om.get("reason") or "failed").strip()
            return f"not_applied: {reason}"
        return json.dumps(dict(om), ensure_ascii=False, default=str)
    return str(outcome)


def format_hitl_outcome(outcome: object) -> str:
    """Human-readable outcome summary for agent text outputs."""
    if outcome is None:
        return ""
    if isinstance(outcome, str):
        return outcome
    if isinstance(outcome, Mapping):
        om = cast(Mapping[str, object], outcome)
        applied = om.get("applied")
        if applied is True:
            details: list[str] = []
            if om.get("role"):
                details.append(f"role={om['role']}")
            if om.get("storage_id"):
                details.append(f"storage_id={om['storage_id']}")
            suffix = f" ({', '.join(details)})" if details else ""
            return f"Access granted{suffix}."
        if applied is False:
            reason = str(om.get("reason") or "unknown reason")
            return f"Not applied: {reason}."
        return json.dumps(dict(om), ensure_ascii=False, default=str)
    return str(outcome)
