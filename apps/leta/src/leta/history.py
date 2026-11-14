import json
from typing import cast
from uuid import UUID

from openlet_sdk.config import JSON

from .agents import json_row
from .db import Pool
from .output import page, text_page


async def search(
    db: Pool, agent: UUID, before: int | None = None, query: str = ""
) -> dict[str, JSON]:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT id,agent_id,run_id,seq,kind,created_at,left(payload::text,500) AS preview,
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


async def search_text(db: Pool, agent: UUID, before: int | None, query: str) -> str:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT seq,kind,created_at,payload->>'name' AS tool,
            left(coalesce(payload->>'text',payload->>'content',(payload->'args')::text,''),201) AS preview
            FROM history WHERE agent_id=%s AND (%s::bigint IS NULL OR seq<%s)
            AND (%s='' OR jsonb_to_tsvector('simple'::regconfig,payload,'["string"]'::jsonb)
            @@ plainto_tsquery('simple',%s)) ORDER BY seq DESC LIMIT 20""",
                (agent, before, before, query, query),
            )
        ).fetchall()
    lines: list[str] = []
    for row in rows:
        preview = str(row["preview"])
        if len(preview) > 200:
            preview = preview[:199] + "…"
        lines.append(
            f"Entry {row['seq']} | {row['kind']}"
            + (f" | {row['tool']}" if row["tool"] else "")
            + f" | {row['created_at']}\n{preview}"
        )
    if len(rows) == 20:
        lines.append(f"Next cursor: {rows[-1]['seq']}")
    return "\n\n".join(lines) or "No matching activity entries."


async def read_text(
    db: Pool, agent: UUID, seq: int, start_line: int, limit: int | None
) -> str:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT seq,kind,created_at,payload FROM history WHERE agent_id=%s AND seq=%s",
                (agent, seq),
            )
        ).fetchone()
    if row is None:
        raise LookupError("history entry not found")
    payload = cast(dict[str, JSON], row["payload"])
    body = payload.get("text") or payload.get("content")
    if not isinstance(body, str):
        body = json.dumps(payload, ensure_ascii=False, indent=2)
    return f"Entry {seq} | {row['kind']} | {row['created_at']}\n" + text_page(
        body, start_line, limit
    )
