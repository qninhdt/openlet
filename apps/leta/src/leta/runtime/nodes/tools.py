"""LangGraph tool-execution node with argument repair, truncation spill, and activity events."""

from __future__ import annotations

import asyncio
import json
import logging
from time import monotonic
from typing import TYPE_CHECKING, Any, Protocol, cast

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolInvocationError
from openlet_sdk.types import is_object_list, is_str_mapping
from pydantic import BaseModel

from leta.runtime.content import (
    extract_text_from_content,
    message_artifact_dict,
    parse_tool_artifact,
)
from leta.runtime.tool_repair import (
    format_tool_error,
    repair_tool_args_with_notes,
    resolve_tool_alias,
)
from leta.truncation import format_head_truncated, truncate_head

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from typing import Literal

    from langchain_core.messages import ToolCall
    from langchain_core.tools import BaseTool
    from langgraph.prebuilt.tool_node import ToolCallRequest
    from langgraph.runtime import Runtime
    from langgraph.types import Command
    from openlet_sdk.config import JSON

    from leta.runtime.state import AgentState, AgentStateUpdate, RuntimeContext

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


def _tool_schema_and_params(tool: BaseTool) -> tuple[dict[str, object], list[str]]:
    schema_cls = tool.tool_call_schema
    if isinstance(schema_cls, type) and issubclass(schema_cls, BaseModel):
        raw_schema: object = schema_cls.model_json_schema()
        schema: dict[str, object] = (
            dict(raw_schema) if is_str_mapping(raw_schema) else {}
        )
    elif is_str_mapping(schema_cls):
        schema = dict(schema_cls)
    else:
        schema = {}
    props = schema.get("properties")
    valid = sorted(props.keys()) if is_str_mapping(props) else []
    return schema, valid


async def _emit_tool_result(
    rt: RuntimeContext,
    *,
    call_id: str,
    name: str,
    status: Literal["success", "error"],
    full_text: str,
    artifact: dict[str, JSON],
    truncated: bool = False,
    output_path: str | None = None,
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
        "truncated": truncated,
        "output_path": output_path,
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
    if not is_str_mapping(state):
        return False
    msgs = state.get("messages")
    if not is_object_list(msgs) or not msgs:
        return False
    last = msgs[-1]
    if not isinstance(last, AIMessage):
        return False
    return str(last.response_metadata.get("finish_reason") or "").lower() == "length"


class ToolsNodeFn(Protocol):
    """Async callable signature for the LangGraph tools node."""

    async def __call__(
        self,
        state: AgentState,
        runtime: Runtime[RuntimeContext],
    ) -> AgentStateUpdate:
        """Execute pending tool calls in ``state`` and return ``ToolMessage`` updates."""
        ...


def _truncated_call_error_message(raw_args: object, excerpt_limit: int) -> str:
    dumped = json.dumps(raw_args, ensure_ascii=False, default=str)
    if len(dumped) > excerpt_limit:
        dumped = dumped[:excerpt_limit] + "... [truncated]"
    return (
        "Tool call arguments were truncated because the model hit the output token limit "
        "(finish_reason=length). Do not retry the same oversized call; split the operation "
        f"into smaller pieces.\n\nPartial arguments:\n{dumped}"
    )


async def _finalize_tool_message(
    rt: RuntimeContext,
    result: ToolMessage,
    *,
    call_id: str,
    called_name: str,
    resolved_name: str,
    repair_note: str | None,
    heal_notes: list[str],
    duration_ms: int,
) -> ToolMessage:
    if result.status == "error":
        err_text = extract_text_from_content(result.content)
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

    to_cfg = rt.services.settings.tool_output
    artifact = message_artifact_dict(result)
    art_meta = parse_tool_artifact(result)
    artifact.pop("_pre_truncated", None)
    artifact.pop("_note", None)
    if art_meta.note:
        heal_notes.append(art_meta.note)

    raw_content = result.content
    truncated = art_meta.truncated
    spill_path = art_meta.output_path

    prefix_parts: list[str] = []
    if repair_note:
        prefix_parts.append(repair_note.rstrip("\n"))
    if heal_notes:
        prefix_parts.append("\n".join(heal_notes))
    prefix = "\n".join(prefix_parts) + "\n" if prefix_parts else ""

    if isinstance(raw_content, str):
        text_out = raw_content
        if not art_meta.pre_truncated:
            trunc = truncate_head(
                text_out,
                max_lines=to_cfg.max_lines,
                max_bytes=to_cfg.max_bytes,
                max_line_length=to_cfg.max_line_length,
            )
            if trunc.truncated:
                truncated = True
                spill_path = await rt.fs.write_spill(resolved_name, text_out)
                text_out = format_head_truncated(trunc, spill_path)
                artifact["truncated"] = True
                if spill_path:
                    artifact["output_path"] = spill_path
        out_content: str | list[str | dict[Any, Any]] = (
            prefix + text_out if prefix else text_out
        )
    else:
        out_content = (
            [{"type": "text", "text": prefix}, *raw_content] if prefix else raw_content
        )

    safe_artifact = _safe_artifact_for_event(artifact)
    full_text = extract_text_from_content(out_content)
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
        truncated=truncated,
        output_path=spill_path,
        duration_ms=duration_ms,
    )
    return ToolMessage(
        content=out_content,
        tool_call_id=call_id,
        name=called_name,
        status="success",
        artifact=safe_artifact,
    )


async def _process_invalid_tool_calls(
    rt: RuntimeContext, ai_msg: AIMessage
) -> list[ToolMessage]:
    to_cfg = rt.services.settings.tool_output
    finish_reason = str(ai_msg.response_metadata.get("finish_reason") or "").lower()
    truncated_by_length = finish_reason == "length"
    out_msgs: list[ToolMessage] = []
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
    return out_msgs


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
        rt = cast("RuntimeContext", request.runtime.context)  # pyright: ignore[reportUnknownMemberType]  # LangGraph ToolCallRequest.runtime is untyped.
        to_cfg = rt.services.settings.tool_output
        call = request.tool_call
        call_id = str(call.get("id") or "")
        called_name = str(call.get("name") or "")
        raw_args: object = call.get("args", {})
        start = monotonic()

        if _is_truncated_by_length(request.state):
            err_msg = _truncated_call_error_message(
                raw_args, to_cfg.input_excerpt_limit
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
            next_call: ToolCall = {
                "name": resolved_name,
                "args": healed_args,
                "id": call.get("id"),
                "type": "tool_call",
            }
            healed_request = request.override(tool=target_tool, tool_call=next_call)
            result = await execute(healed_request)

        duration_ms = int((monotonic() - start) * 1000)
        if not isinstance(result, ToolMessage):
            return result

        return await _finalize_tool_message(
            rt,
            result,
            call_id=call_id,
            called_name=called_name,
            resolved_name=resolved_name,
            repair_note=repair_note,
            heal_notes=heal_notes,
            duration_ms=duration_ms,
        )

    native_tool_node = ToolNode(
        tools_list,
        handle_tool_errors=_handle_error,
        awrap_tool_call=_awrap_tool_call,
    )

    async def _tools_node(
        state: AgentState,
        runtime: Runtime[RuntimeContext],
    ) -> AgentStateUpdate:
        msgs = state["messages"]
        if not msgs or not isinstance(msgs[-1], AIMessage):
            return {}
        ai_msg = msgs[-1]
        out_msgs: list[ToolMessage] = []

        if ai_msg.tool_calls:
            res: object = await native_tool_node.ainvoke(state)
            if is_str_mapping(res):
                res_msgs = res.get("messages")
                if is_object_list(res_msgs):
                    out_msgs.extend(m for m in res_msgs if isinstance(m, ToolMessage))

        if ai_msg.invalid_tool_calls:
            out_msgs.extend(await _process_invalid_tool_calls(runtime.context, ai_msg))

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
    any_end_turn = any(parse_tool_artifact(tm).end_turn for tm in batch)
    if all_ok and any_end_turn:
        return "end_turn"
    return "inbox"
