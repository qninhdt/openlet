import json
from datetime import datetime, timezone
from typing import Literal, cast
from uuid import UUID

from openlet_sdk.config import JSON

from .agents import json_row
from .db import Pool
from .output import BYTE_BUDGET, page, text_page

ActivityKind = Literal[
    "final_note",
    "tool_call",
    "tool_result",
    "compaction",
    "inbox_input",
    "assistant",
]


async def search(
    db: Pool, agent: UUID, before: int | None = None, query: str = ""
) -> dict[str, JSON]:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT id,agent_id,run_id,seq,kind,created_at,left(payload::text,500) AS preview,left(payload->>'text',500) AS text_preview,
            octet_length(payload::text)>500 AS truncated FROM history WHERE agent_id=%s
            AND (%s::bigint IS NULL OR seq<%s) AND (%s='' OR
            jsonb_to_tsvector('simple'::regconfig,payload,'["string"]'::jsonb) @@ plainto_tsquery('simple',%s))
            ORDER BY seq DESC LIMIT 20""",
                (agent, before, before, query, query),
            )
        ).fetchall()
    return {
        "entries": [json_row(row) for row in rows],
        "next_cursor": str(rows[-1]["seq"]) if len(rows) == 20 else None,
    }


async def read(
    db: Pool, agent: UUID, entry: UUID, start_line: int = 1, limit: int = 200
) -> dict[str, JSON]:
    if start_line < 1:
        raise ValueError("start_line must be positive")
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT * FROM history WHERE agent_id=%s AND id=%s", (agent, entry)
            )
        ).fetchone()
    if row is None:
        raise LookupError("history entry not found")
    payload = cast(dict[str, JSON], row.pop("payload"))
    body = payload.pop("text", None)
    if not isinstance(body, str):
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        payload = {}
    return {
        **json_row(row),
        "payload": payload,
        **page(body, start_line, limit),
    }


def _timestamp(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    return str(value)


def _compact_json(value: object, *, limit: int = 240) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return encoded[: limit - 1] + "…" if len(encoded) > limit else encoded


def _format_json_text(text: str) -> str:
    if "\n" in text or len(text) <= 240:
        return text
    try:
        parsed = json.loads(text)
    except ValueError:
        return text
    if isinstance(parsed, (dict, list)):
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    return text


def _wrap_oversized_lines(text: str) -> str:
    chunk_limit = BYTE_BUDGET // 2
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        raw = line.encode("utf-8")
        if len(raw) <= BYTE_BUDGET:
            lines.append(line)
            continue
        ending = "\n" if line.endswith("\n") else ""
        content = line[:-1] if ending else line
        while content:
            encoded = content.encode("utf-8")
            if len(encoded) <= chunk_limit:
                lines.append(content + ending)
                break
            piece = encoded[:chunk_limit].decode("utf-8", errors="ignore")
            if not piece:
                piece = content[0]
            lines.append(piece + "\n")
            content = content[len(piece) :]
    return "".join(lines)


async def search_tool(
    db: Pool,
    agent: UUID,
    before: int | None = None,
    query: str = "",
    *,
    kind: ActivityKind | None = None,
    tool: str = "",
) -> tuple[str, dict[str, JSON]]:
    query = query.strip()
    tool = tool.strip()
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT id,agent_id,run_id,seq,kind,created_at,
            payload->>'name' AS tool,payload->>'status' AS status,
            left(coalesce(
                nullif(payload->>'text',''),
                nullif(payload->>'reasoning',''),
                nullif(payload->>'content',''),
                nullif((payload->'args')::text,''),
                nullif((payload->'file')::text,''),
                ''
            ),201) AS preview
            FROM history WHERE agent_id=%s AND (%s::bigint IS NULL OR seq<%s)
            AND (%s::text IS NULL OR kind=%s)
            AND (%s='' OR payload->>'name'=%s)
            AND NOT (kind IN ('tool_call','tool_result')
                AND coalesce(payload->>'name','') IN ('activity_search','activity_read'))
            AND (%s='' OR jsonb_to_tsvector('simple'::regconfig,payload,'["string"]'::jsonb)
            @@ plainto_tsquery('simple',%s)) ORDER BY seq DESC LIMIT 21""",
                (agent, before, before, kind, kind, tool, tool, query, query),
            )
        ).fetchall()
    has_more = len(rows) > 20
    page_rows = rows[:20]
    lines: list[str] = []
    for row in page_rows:
        preview = str(row["preview"])
        if len(preview) > 200:
            preview = preview[:199] + "…"
        header = [f"Entry {row['seq']}", str(row["kind"])]
        if row["tool"]:
            header.append(str(row["tool"]))
        if row["status"]:
            header.append(str(row["status"]))
        header.append(_timestamp(row["created_at"]))
        lines.append(" | ".join(header) + f"\n{preview or '(empty)'}")
    next_cursor = str(page_rows[-1]["seq"]) if has_more else None
    if next_cursor:
        lines.append(f"Next cursor: {next_cursor}")
    return "\n\n".join(lines) or "No matching activity entries.", {
        "entries": [
            json_row({**row, "text_preview": row["preview"]}) for row in page_rows
        ],
        "next_cursor": next_cursor,
    }


async def read_entry(
    db: Pool,
    agent: UUID,
    seq: int,
    start_line: int = 1,
    limit: int | None = None,
) -> tuple[str, dict[str, JSON]]:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT id,run_id,seq,kind,created_at,payload FROM history WHERE agent_id=%s AND seq=%s",
                (agent, seq),
            )
        ).fetchone()
        if row is None:
            raise LookupError("activity entry not found")
        kind = str(row["kind"])
        payload = cast(dict[str, JSON], row["payload"])
        tool_call_id = (
            payload["tool_call_id"]
            if isinstance(payload.get("tool_call_id"), str)
            else None
        )
        paired = None
        if kind in ("tool_call", "tool_result") and tool_call_id:
            counterpart = "tool_result" if kind == "tool_call" else "tool_call"
            paired = await (
                await conn.execute(
                    """SELECT seq,payload FROM history
                    WHERE agent_id=%s AND run_id=%s AND kind=%s AND payload->>'tool_call_id'=%s
                    ORDER BY seq LIMIT 1""",
                    (agent, row["run_id"], counterpart, tool_call_id),
                )
            ).fetchone()
    raw_name, raw_status = payload.get("name"), payload.get("status")
    tool_name = raw_name if isinstance(raw_name, str) else None
    status = raw_status if isinstance(raw_status, str) else None
    sections: list[str] = []
    if kind in ("assistant", "final_note"):
        reasoning = payload.get("reasoning")
        text = payload.get("text")
        if isinstance(reasoning, str) and reasoning:
            sections.append(f"Reasoning:\n{reasoning}")
        if isinstance(text, str) and text:
            label = "Note" if kind == "final_note" else "Text"
            sections.append(f"{label}:\n{text}")
        if not sections:
            sections.append("(empty)")
    elif kind == "tool_call":
        if paired is not None:
            paired_payload = cast(dict[str, JSON], paired["payload"])
            paired_status = paired_payload.get("status") or "unknown"
            sections.append(f"Result entry: {paired['seq']} | status={paired_status}")
        else:
            sections.append("Result entry: (none recorded)")
        args = payload.get("args")
        sections.append(
            "Args:\n"
            + json.dumps(args if args is not None else {}, ensure_ascii=False, indent=2)
        )
    elif kind == "tool_result":
        if paired is not None:
            paired_payload = cast(dict[str, JSON], paired["payload"])
            paired_name = paired_payload.get("name") or tool_name or "tool"
            paired_args = _compact_json(paired_payload.get("args", {}))
            sections.append(
                f"Call entry: {paired['seq']} | {paired_name}({paired_args})"
            )
        file_info = payload.get("file")
        if isinstance(file_info, dict):
            sections.append(
                f"File: {file_info.get('path', '')} ({file_info.get('kind', 'file')})"
            )
        raw_text = payload.get("text")
        if isinstance(raw_text, str) and raw_text:
            sections.append("Output:\n" + _format_json_text(raw_text))
        else:
            extra = {
                k: v
                for k, v in payload.items()
                if k not in ("tool_call_id", "name", "status", "file", "text")
            }
            sections.append(
                "Payload:\n" + json.dumps(extra, ensure_ascii=False, indent=2)
                if extra
                else "Output:\n(empty output)"
            )
    else:
        raw = payload.get("text") or payload.get("content")
        sections.append(
            _format_json_text(raw)
            if isinstance(raw, str) and raw
            else json.dumps(payload, ensure_ascii=False, indent=2)
        )
    header = [f"Entry {seq}", kind]
    if tool_name:
        header.append(tool_name)
    if status:
        header.append(status)
    header.append(_timestamp(row["created_at"]))
    body_page = text_page(_wrap_oversized_lines("\n".join(sections)), start_line, limit)
    text = " | ".join(header) + "\n" + body_page
    data: dict[str, JSON] = {
        "entry": seq,
        "kind": kind,
        "tool": tool_name,
        "status": status,
        "created_at": _timestamp(row["created_at"]),
        "paired_entry": cast(JSON, paired["seq"]) if paired is not None else None,
        "content": body_page,
        "start_line": start_line,
    }
    return text, data
