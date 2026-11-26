from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import cast
from zoneinfo import ZoneInfoNotFoundError

import grpc
from langchain_core.tools import ToolException
from langgraph.prebuilt.tool_node import ToolInvocationError
from pydantic import ValidationError
from pydantic_core import ErrorDetails

from ..channels.base import ChannelError

TOOL_ALIASES: dict[str, str] = {
    "execute": "bash",
    "shell": "bash",
    "bash": "bash",
    "run_command": "bash",
    "read": "file_read",
    "file_list": "file_read",
    "ls": "file_read",
    "list_dir": "file_read",
    "edit": "file_edit",
    "str_replace": "file_edit",
    "write": "file_write",
    "create_file": "file_write",
    "glob_files": "glob",
    "find_files": "glob",
    "grep_files": "grep",
    "search_files": "grep",
    "web_search": "websearch",
    "web_fetch": "webfetch",
    "fetch_url": "webfetch",
    "inbox_send": "send_message",
    "reply": "send_message",
    "inbox_react": "react_message",
}

GLOBAL_PARAM_ALIASES: dict[str, str] = {
    "file_path": "path",
    "filepath": "path",
    "filePath": "path",
    "oldString": "old_string",
    "newString": "new_string",
    "replaceAll": "replace_all",
    "caseSensitive": "case_sensitive",
    "cwd": "workdir",
    "working_dir": "workdir",
    "working_directory": "workdir",
    "max_results": "limit",
    "maxResults": "limit",
    "reply_to": "reply_to_message_id",
    "replyTo": "reply_to_message_id",
    "replyToMessageId": "reply_to_message_id",
    "endTurn": "end_turn",
    "include_hidden": "hidden",
}

TOOL_PARAM_ALIASES: dict[str, dict[str, str]] = {
    "agent_status": {"handle": "agent", "agent_id": "agent", "id": "agent"},
    "stop_agent": {"handle": "agent", "agent_id": "agent", "id": "agent"},
    "hitl_ask": {
        "user": "recipient",
        "user_id": "recipient",
        "user_handle": "recipient",
        "to": "recipient",
    },
    "hitl_request_access": {
        "user": "recipient",
        "user_id": "recipient",
        "user_handle": "recipient",
        "to": "recipient",
    },
    "hitl_cancel": {"id": "request_id"},
    "hitl_list": {"id": "request_id"},
    "schedule_create": {
        "target": "target_agent",
        "target_agent_id": "target_agent",
        "agent": "target_agent",
    },
    "schedule_update": {
        "id": "schedule_id",
        "target": "target_agent",
        "target_agent_id": "target_agent",
        "agent": "target_agent",
    },
    "schedule_delete": {"id": "schedule_id"},
    "schedule_list": {"id": "schedule_id"},
}

_NULLISH_STRINGS = frozenset({"null", "none", "undefined"})


def resolve_tool_alias(
    called_name: str, available_tools: Mapping[str, object]
) -> tuple[str, str | None]:
    if called_name in available_tools:
        return called_name, None
    target = TOOL_ALIASES.get(called_name) or TOOL_ALIASES.get(called_name.lower())
    if target is not None and target in available_tools:
        note = (
            f'<tool-repair>\nThere is no "{called_name}" tool, so this ran as '
            f'"{target}". Call "{target}" next time.\n</tool-repair>\n'
        )
        return target, note
    return called_name, None


def _is_nullable(schema: Mapping[str, object]) -> bool:
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        return any(
            isinstance(b, Mapping)
            and cast(Mapping[str, object], b).get("type") == "null"
            for b in cast(list[object], any_of)
        )
    return schema.get("type") == "null"


def _coerce_value(
    value: object,
    schema: Mapping[str, object],
    defs: Mapping[str, object],
    depth: int,
    max_depth: int,
    *,
    tool_name: str = "",
) -> object:
    if depth > max_depth:
        return value
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        target = defs.get(ref.removeprefix("#/$defs/"))
        if isinstance(target, Mapping):
            return _coerce_value(
                value,
                cast(Mapping[str, object], target),
                defs,
                depth + 1,
                max_depth,
                tool_name=tool_name,
            )

    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        branches = [
            cast(Mapping[str, object], b)
            for b in cast(list[object], any_of)
            if isinstance(b, Mapping)
        ]
        non_null = [b for b in branches if b.get("type") != "null"]
        nullable = len(non_null) < len(branches)
        if value is None:
            return None
        if nullable and isinstance(value, str):
            stripped = value.strip()
            if not stripped or stripped.lower() in _NULLISH_STRINGS:
                return None
        if len(non_null) == 1:
            return _coerce_value(
                value,
                non_null[0],
                defs,
                depth + 1,
                max_depth,
                tool_name=tool_name,
            )
        for branch in non_null:
            coerced = _coerce_value(
                value, branch, defs, depth + 1, max_depth, tool_name=tool_name
            )
            if coerced is not value:
                return coerced
        return value

    expected = schema.get("type")
    if expected == "object":
        if isinstance(value, str):
            try:
                parsed: object = json.loads(value)
                if isinstance(parsed, dict):
                    value = cast(dict[str, object], parsed)
            except Exception:
                return value
        if not isinstance(value, Mapping):
            return value
        props_raw = schema.get("properties")
        props: Mapping[str, object] = (
            cast(Mapping[str, object], props_raw)
            if isinstance(props_raw, Mapping)
            else {}
        )
        required = set(
            cast(list[str], schema.get("required"))
            if isinstance(schema.get("required"), list)
            else []
        )
        tool_aliases = TOOL_PARAM_ALIASES.get(tool_name, {}) if depth == 0 else {}

        raw_items = list(cast(Mapping[str, object], value).items())
        present_keys = {str(k) for k, _ in raw_items}
        out: dict[str, object] = {}
        for k, v in raw_items:
            key = str(k)
            if key not in props:
                mapped = tool_aliases.get(key) or (
                    GLOBAL_PARAM_ALIASES.get(key) if depth == 0 else None
                )
                if (
                    mapped
                    and mapped in props
                    and mapped not in present_keys
                    and mapped not in out
                ):
                    key = mapped
                else:
                    # Preserve unknown keys so Pydantic surfaces a clear error listing valid params.
                    out[key] = v
                    continue
            prop_schema: Mapping[str, object] = (
                cast(Mapping[str, object], props[key])
                if isinstance(props[key], Mapping)
                else {}
            )
            if key not in required:
                if v is None or (v == {} and prop_schema.get("type") != "object"):
                    continue
                if isinstance(v, str):
                    low = v.strip().lower()
                    if low in _NULLISH_STRINGS:
                        continue
                    if v.strip() == "" and _is_nullable(prop_schema):
                        continue
            out[key] = _coerce_value(
                v, prop_schema, defs, depth + 1, max_depth, tool_name=tool_name
            )
        return out

    if expected == "array":
        items_list: list[object]
        if isinstance(value, str):
            try:
                parsed_arr: object = json.loads(value)
                if isinstance(parsed_arr, list):
                    items_list = cast(list[object], parsed_arr)
                else:
                    items_list = [value]
            except Exception:
                items_list = [value]
        elif isinstance(value, list):
            items_list = cast(list[object], value)
        else:
            items_list = [value]
        items_schema = schema.get("items")
        if isinstance(items_schema, Mapping):
            item_map = cast(Mapping[str, object], items_schema)
            return [
                _coerce_value(
                    item, item_map, defs, depth + 1, max_depth, tool_name=tool_name
                )
                for item in items_list
            ]
        return items_list

    if expected == "integer":
        if isinstance(value, str):
            s = value.strip()
            if s.lstrip("+-").isdigit():
                return int(s)
        elif isinstance(value, float) and value.is_integer():
            return int(value)
        return value

    if expected == "number":
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return value
        return value

    if expected == "boolean":
        if isinstance(value, str):
            low = value.strip().lower()
            if low == "true":
                return True
            if low == "false":
                return False
        return value

    return value


def _apply_domain_auto_heals(
    tool_name: str, args: dict[str, object]
) -> tuple[dict[str, object], list[str]]:
    """Tier-1 unambiguous minor-error auto-heals (zero retry)."""
    notes: list[str] = []
    out = dict(args)

    # 1. Milliseconds -> seconds auto-conversion for bash & webfetch timeouts.
    if tool_name in ("bash", "webfetch"):
        max_secs = 600 if tool_name == "bash" else 120
        raw_t = out.get("timeout")
        if (
            isinstance(raw_t, (int, float))
            and not isinstance(raw_t, bool)
            and raw_t > max_secs
        ):
            converted = max(1, min(max_secs, round(raw_t / 1000)))
            out["timeout"] = converted
            notes.append(
                f"Note: interpreted timeout={raw_t} as {converted}s ({tool_name} timeout is in seconds, max {max_secs})."
            )

    # 2. hitl_ask: coerce empty options=[] to None for free-text questions.
    if tool_name == "hitl_ask" and isinstance(out.get("questions"), list):
        fixed_qs: list[object] = []
        for q in cast(list[object], out["questions"]):
            if isinstance(q, Mapping):
                qd = dict(cast(Mapping[str, object], q))
                if qd.get("options") == []:
                    qd["options"] = None
                fixed_qs.append(qd)
            else:
                fixed_qs.append(q)
        out["questions"] = fixed_qs

    # 3. hitl_list: map common status synonyms.
    if tool_name == "hitl_list" and isinstance(out.get("status"), str):
        syn = {
            "open": "pending",
            "waiting": "pending",
            "approved": "accepted",
            "rejected": "denied",
        }
        low = str(out["status"]).strip().lower()
        out["status"] = syn.get(low, low)

    # 4. file_read: tolerant offset=0 / limit=0.
    if tool_name == "file_read":
        if out.get("offset") == 0:
            out["offset"] = 1
        if out.get("limit") == 0:
            out.pop("limit", None)

    return out, notes


def repair_tool_args(
    args: object,
    json_schema: Mapping[str, object],
    *,
    tool_name: str = "",
    max_depth: int = 6,
) -> dict[str, object]:
    repaired, _ = repair_tool_args_with_notes(
        args, json_schema, tool_name=tool_name, max_depth=max_depth
    )
    return repaired


def repair_tool_args_with_notes(
    args: object,
    json_schema: Mapping[str, object],
    *,
    tool_name: str = "",
    max_depth: int = 6,
) -> tuple[dict[str, object], list[str]]:
    raw: object = args
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}, []
    if not isinstance(raw, Mapping):
        return {}, []
    raw_map = cast(Mapping[str, object], raw)
    defs_raw = json_schema.get("$defs")
    defs: Mapping[str, object] = (
        cast(Mapping[str, object], defs_raw) if isinstance(defs_raw, Mapping) else {}
    )
    coerced = _coerce_value(
        raw_map, json_schema, defs, 0, max_depth, tool_name=tool_name
    )
    repaired = (
        cast(dict[str, object], coerced) if isinstance(coerced, dict) else dict(raw_map)
    )
    return _apply_domain_auto_heals(tool_name, repaired)


def format_input_issues(
    exc: ValidationError | Sequence[ErrorDetails],
    provided_args: object,
    *,
    valid_params: Sequence[str] | None = None,
    excerpt_limit: int = 2048,
) -> str:
    errors = exc.errors() if isinstance(exc, ValidationError) else list(exc)
    issues: list[str] = []
    has_extra = False
    for err in errors[:5]:
        loc = ".".join(str(part) for part in err.get("loc", ())) or "<root>"
        etype = str(err.get("type") or "")
        msg = str(err.get("msg") or "invalid value")
        if etype == "extra_forbidden":
            has_extra = True
            issues.append(f"- {loc}: unknown parameter")
        else:
            issues.append(f"- {loc}: {msg}")
    if len(errors) > 5:
        issues.append(f"- ...and {len(errors) - 5} more issue(s)")
    extra_hint = (
        f"\nValid parameters: {', '.join(sorted(valid_params))}"
        if has_extra and valid_params
        else ""
    )
    dumped = json.dumps(provided_args, ensure_ascii=False, default=str)
    if len(dumped) > excerpt_limit:
        dumped = dumped[:excerpt_limit] + "... [truncated]"
    return (
        "Invalid tool arguments:\n"
        + "\n".join(issues)
        + extra_hint
        + f"\n\nArguments provided:\n{dumped}\n\n"
        "Update the arguments and call the tool again."
    )


def format_tool_error(
    exc: Exception,
    *,
    valid_params: Sequence[str] | None = None,
    excerpt_limit: int = 2048,
) -> str:
    """Clean model-facing error boundary; never dumps raw gRPC debug strings or errno boilerplate."""
    if isinstance(exc, ToolInvocationError):
        errs = (
            exc.filtered_errors
            if exc.filtered_errors is not None
            else exc.source.errors()
        )
        return format_input_issues(
            errs,
            exc.tool_kwargs,
            valid_params=valid_params,
            excerpt_limit=excerpt_limit,
        )
    if isinstance(exc, ValidationError):
        return format_input_issues(
            exc, {}, valid_params=valid_params, excerpt_limit=excerpt_limit
        )
    if isinstance(exc, (ToolException, ChannelError)):
        return str(exc)
    if isinstance(exc, ZoneInfoNotFoundError):
        key = str(exc).removeprefix("No time zone found with key ").strip("'\"")
        return (
            f"Invalid timezone {key!r}. Use an IANA timezone name such as "
            "'UTC', 'Asia/Ho_Chi_Minh', or 'America/New_York'."
        )
    if isinstance(exc, grpc.aio.AioRpcError):
        code = exc.code()
        details = (exc.details() or "").strip()
        if code == grpc.StatusCode.NOT_FOUND:
            return f"Not found: {details or 'requested resource does not exist'}"
        if code == grpc.StatusCode.PERMISSION_DENIED:
            return f"Permission denied: {details or 'insufficient access'}"
        if code == grpc.StatusCode.INVALID_ARGUMENT:
            return f"Invalid request: {details or 'check arguments and try again'}"
        if code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
            return f"Service temporarily unavailable ({code.name}): {details or 'retry shortly'}"
        return f"Service error ({code.name}): {details or 'operation failed'}"
    if isinstance(exc, FileNotFoundError):
        msg = exc.strerror or str(exc)
        return msg if msg else "File or directory not found."
    if isinstance(exc, PermissionError):
        msg = exc.strerror or str(exc)
        return (
            f"Permission denied: {msg}"
            if not msg.lower().startswith("permission")
            else msg
        )
    if isinstance(exc, OSError):
        msg = exc.strerror or str(exc)
        return f"Filesystem error: {msg}"
    return f"Error: {exc}"
