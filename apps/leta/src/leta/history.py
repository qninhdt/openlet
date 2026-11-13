import json
from typing import cast
from uuid import UUID

from openlet_sdk.config import JSON

from .agents import json_row
from .db import Pool


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
    db: Pool, agent: UUID, entry: UUID, start_line: int = 1
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
    body = json.dumps(
        cast(JSON, row.pop("payload")), ensure_ascii=False, indent=2
    ).splitlines()
    lines = body[start_line - 1 : start_line + 199]
    return {
        **json_row(row),
        "content": "\n".join(lines),
        "next_start_line": (
            start_line + len(lines) if start_line + len(lines) <= len(body) else None
        ),
    }
