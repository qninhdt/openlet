from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from time import monotonic
from typing import Any, Literal, Protocol, cast

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest, ToolInvocationError
from langgraph.runtime import Runtime
from langgraph.types import Command
from openlet_sdk.config import JSON
from pydantic import BaseModel

from ...truncation import format_head_truncated, truncate_head
from ..state import AgentState, RuntimeContext
from ..tool_repair import (
    format_tool_error,
    repair_tool_args_with_notes,
    resolve_tool_alias,
)

logger = logging.getLogger(__name__)

_TOOL_CONCURRENCY = 8


def _safe_artifact_for_event(artifact: dict[str, JSON]) -> dict[str, JSON]:
    """Ensure raw image base64 and internal _* flags are never persisted into activity_events."""
    cleaned: dict[str, JSON] = {}
    for k, v in artifact.items():
        if k.startswith("_") or k in ("data_url", "base64", "image_base64"):
            continue
        cleaned[k] = v
    return cleaned


def _text_from_content(content: str | list[str | dict[Any, Any]]) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for blk in content:
        if isinstance(blk, str):
            parts.append(blk)
        elif blk.get("type") == "text":
            parts.append(str(blk.get("text", "")))
        elif blk.get("type") == "image_url":
            parts.append("[inline image attached]")
    return "\n".join(parts)


def _tool_schema_and_params(tool: BaseTool) -> tuple[dict[str, object], list[str]]:
    schema_cls = tool.tool_call_schema
    if isinstance(schema_cls, type) and issubclass(schema_cls, BaseModel):
        schema = cast(dict[str, object], schema_cls.model_json_schema())
    elif isinstance(schema_cls, dict):
        schema = cast(dict[str, object], schema_cls)
    else:
        schema = {}
    props = schema.get("properties")
    valid = (
        sorted(str(k) for k in cast(dict[str, object], props).keys())
        if isinstance(props, dict)
        else []
    )
    return schema, valid


async def _emit_tool_result(
    rt: RuntimeContext,
    *,
    call_id: str,
    name: str,
    status: Literal["success", "error"],
    full_text: str,
    artifact: dict[str, JSON],
    duration_ms: int,
) -> None:
    preview_limit = 2000
    preview = full_text[:preview_limit]
    has_more = len(full_text) > preview_limit
    base: dict[str, JSON] = {
        "tool_call_id": call_id,
        "name": name,
        "status": status,
        "preview": preview,
        "has_more_content": has_more,
        "truncated": bool(artifact.get("truncated", False)),
        "output_path": artifact.get("output_path"),
        "duration_ms": duration_ms,
        "artifact": artifact,
    }
    db_data: dict[str, JSON] = {**base, "content": full_text}
    await rt.emitter.emit(
        leta_id=rt.leta_id,
        agent_id=rt.agent_id,
        run_id=rt.run_id,
        event_type="activity.tool_result",
        data=db_data,
        realtime_data=base,
    )


def _is_truncated_by_length(state: object) -> bool:
    if not isinstance(state, dict):
        return False
    msgs = cast(dict[str, object], state).get("messages")
    if not isinstance(msgs, list) or not msgs:
        return False
    last = cast(list[object], msgs)[-1]
    if not isinstance(last, AIMessage):
        return False
    return str(last.response_metadata.get("finish_reason") or "").lower() == "length"


class ToolsNodeFn(Protocol):
    async def __call__(
        self,
        state: AgentState,
        runtime: Runtime[RuntimeContext],
    ) -> dict[str, object]: ...


def build_tools_node(tools: Sequence[BaseTool]) -> ToolsNodeFn:
    """Build a LangGraph ToolNode wrapped with 3-tier auto-heal, truncation/spill, and activity emission."""
    tools_list = list(tools)
    tools_by_name: dict[str, BaseTool] = {t.name: t for t in tools_list}
    sem = asyncio.Semaphore(_TOOL_CONCURRENCY)

    def _handle_error(exc: Exception) -> str:
        valid_params: list[str] | None = None
        if isinstance(exc, ToolInvocationError):
            t = tools_by_name.get(exc.tool_name)
            if t is not None:
                _, valid_params = _tool_schema_and_params(t)
        return format_tool_error(exc, valid_params=valid_params)

    async def _awrap_tool_call(
        request: ToolCallRequest,
        execute: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        req_runtime: Any = getattr(request, "runtime")
        rt = cast(RuntimeContext, req_runtime.context)
        to_cfg = rt.services.settings.tool_output
        call = request.tool_call
        call_id = str(call.get("id") or "")
        called_name = str(call.get("name") or "")
        raw_args: object = call.get("args", {})
        start = monotonic()

        if _is_truncated_by_length(request.state):
            dumped = json.dumps(raw_args, ensure_ascii=False, default=str)
            if len(dumped) > to_cfg.input_excerpt_limit:
                dumped = dumped[: to_cfg.input_excerpt_limit] + "... [truncated]"
            err_msg = (
                "Tool call arguments were truncated because the model hit the output token limit "
                "(finish_reason=length). Do not retry the same oversized call; split the operation "
                f"into smaller pieces.\n\nPartial arguments:\n{dumped}"
            )
            await _emit_tool_result(
                rt,
                call_id=call_id,
                name=called_name,
                status="error",
                full_text=err_msg,
                artifact={"truncated": False},
                duration_ms=int((monotonic() - start) * 1000),
            )
            return ToolMessage(
                content=err_msg,
                tool_call_id=call_id,
                name=called_name,
                status="error",
            )

        async with sem:
            resolved_name, repair_note = resolve_tool_alias(called_name, tools_by_name)
            target_tool = tools_by_name.get(resolved_name)
            if target_tool is None:
                available = ", ".join(sorted(tools_by_name))
                err_msg = f"Unknown tool {called_name!r}. Available tools: {available}"
                await _emit_tool_result(
                    rt,
                    call_id=call_id,
                    name=called_name,
                    status="error",
                    full_text=err_msg,
                    artifact={},
                    duration_ms=int((monotonic() - start) * 1000),
                )
                return ToolMessage(
                    content=err_msg,
                    tool_call_id=call_id,
                    name=called_name,
                    status="error",
                )

            schema, _ = _tool_schema_and_params(target_tool)
            healed_args, heal_notes = repair_tool_args_with_notes(
                raw_args,
                schema,
                tool_name=resolved_name,
                max_depth=to_cfg.input_repair_max_depth,
            )
            next_call = {**call, "name": resolved_name, "args": healed_args}
            healed_request = request.override(tool=target_tool, tool_call=next_call)  # pyright: ignore[reportArgumentType]
            result = await execute(healed_request)

        duration_ms = int((monotonic() - start) * 1000)
        if not isinstance(result, ToolMessage):
            return result

        if result.status == "error":
            err_text = _text_from_content(result.content)
            await _emit_tool_result(
                rt,
                call_id=call_id,
                name=resolved_name,
                status="error",
                full_text=err_text,
                artifact={},
                duration_ms=duration_ms,
            )
            return ToolMessage(
                content=result.content,
                tool_call_id=call_id,
                name=called_name,
                status="error",
            )

        raw_artifact = getattr(result, "artifact", None)
        artifact: dict[str, JSON] = (
            dict(cast(dict[str, JSON], raw_artifact))
            if isinstance(raw_artifact, dict)
            else {}
        )
        pre_truncated = bool(artifact.pop("_pre_truncated", False))
        extra_note = artifact.pop("_note", None)
        if isinstance(extra_note, str) and extra_note:
            heal_notes.append(extra_note)

        content: str | list[str | dict[Any, Any]] = result.content
        truncated = bool(artifact.get("truncated", False))
        spill_path: str | None = (
            str(artifact["output_path"]) if artifact.get("output_path") else None
        )

        if isinstance(content, str) and not pre_truncated:
            trunc = truncate_head(
                content,
                max_lines=to_cfg.max_lines,
                max_bytes=to_cfg.max_bytes,
                max_line_length=to_cfg.max_line_length,
            )
            if trunc.truncated:
                truncated = True
                spill_path = await rt.fs.write_spill(resolved_name, content)
                content = format_head_truncated(trunc, spill_path)
                artifact["truncated"] = True
                if spill_path:
                    artifact["output_path"] = spill_path

        prefix_parts: list[str] = []
        if repair_note:
            prefix_parts.append(repair_note.rstrip("\n"))
        if heal_notes:
            prefix_parts.append("\n".join(heal_notes))
        if prefix_parts:
            prefix = "\n".join(prefix_parts) + "\n"
            if isinstance(content, str):
                content = prefix + content
            else:
                content = [{"type": "text", "text": prefix}, *content]

        safe_artifact = _safe_artifact_for_event(artifact)
        full_text = _text_from_content(content)
        await _emit_tool_result(
            rt,
            call_id=call_id,
            name=resolved_name,
            status="success",
            full_text=full_text,
            artifact={
                **safe_artifact,
                "truncated": truncated,
                "output_path": spill_path,
            },
            duration_ms=duration_ms,
        )
        return ToolMessage(
            content=content,
            tool_call_id=call_id,
            name=called_name,
            status="success",
            artifact=safe_artifact,
        )

    native_tool_node = ToolNode(
        tools_list,
        handle_tool_errors=_handle_error,
        awrap_tool_call=_awrap_tool_call,
    )

    async def _tools_node(
        state: AgentState,
        runtime: Runtime[RuntimeContext],
    ) -> dict[str, object]:
        msgs = state["messages"]
        if not msgs or not isinstance(msgs[-1], AIMessage):
            return {}
        ai_msg = msgs[-1]
        out_msgs: list[ToolMessage] = []

        if ai_msg.tool_calls:
            res: object = await native_tool_node.ainvoke(state)
            if isinstance(res, dict):
                res_msgs = cast(dict[str, object], res).get("messages")
                if isinstance(res_msgs, list):
                    out_msgs.extend(cast(list[ToolMessage], res_msgs))

        if ai_msg.invalid_tool_calls:
            rt = runtime.context
            to_cfg = rt.services.settings.tool_output
            finish_reason = str(
                ai_msg.response_metadata.get("finish_reason") or ""
            ).lower()
            truncated_by_length = finish_reason == "length"
            for itc in ai_msg.invalid_tool_calls:
                cid = str(itc.get("id") or "")
                cname = str(itc.get("name") or "")
                raw = str(itc.get("args") or "")
                if len(raw) > to_cfg.input_excerpt_limit:
                    raw = raw[: to_cfg.input_excerpt_limit] + "... [truncated]"
                if truncated_by_length:
                    err_msg = (
                        "Tool call arguments were truncated because the model hit the output token limit "
                        "(finish_reason=length). Do not retry the same oversized call; split the operation "
                        f"into smaller pieces.\n\nPartial arguments:\n{raw}"
                    )
                else:
                    parse_err = str(itc.get("error") or "malformed JSON arguments")
                    err_msg = (
                        f"Invalid tool arguments ({parse_err}).\n\n"
                        f"Raw arguments:\n{raw}\n\n"
                        "Provide valid JSON arguments and call the tool again."
                    )
                await _emit_tool_result(
                    rt,
                    call_id=cid,
                    name=cname,
                    status="error",
                    full_text=err_msg,
                    artifact={"truncated": False},
                    duration_ms=0,
                )
                out_msgs.append(
                    ToolMessage(
                        content=err_msg,
                        tool_call_id=cid,
                        name=cname,
                        status="error",
                    )
                )

        return {"messages": out_msgs} if out_msgs else {}

    return _tools_node


def after_tools_router(state: AgentState) -> Literal["end_turn", "inbox"]:
    """Inspect latest ToolMessage batch directly: fast-exit if all OK & any end_turn=True."""
    msgs = state["messages"]
    batch: list[ToolMessage] = []
    for msg in reversed(msgs):
        if isinstance(msg, ToolMessage):
            batch.append(msg)
        else:
            break
    if not batch:
        return "inbox"
    all_ok = all(tm.status != "error" for tm in batch)
    any_end_turn = False
    for tm in batch:
        raw_art: object = getattr(tm, "artifact", None)
        if (
            isinstance(raw_art, dict)
            and cast(dict[str, object], raw_art).get("end_turn") is True
        ):
            any_end_turn = True
            break
    if all_ok and any_end_turn:
        return "end_turn"
    return "inbox"
