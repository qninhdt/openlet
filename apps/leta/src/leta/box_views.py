"""Read-only topology and runtime summaries, after filtering authorized Leta IDs."""

from typing import cast
from uuid import UUID

from openlet_sdk.config import JSON

from .agents import json_row
from .db import Pool


async def graph(db: Pool, roots: list[UUID]) -> dict[str, JSON]:
    async with db.connection() as conn:
        agents = await (
            await conn.execute(
                """SELECT a.id,a.leta_id,a.box_id,a.name,a.title,a.appearance,a.description,
                a.model_id,a.reasoning_effort,l.paused,l.state,b.state AS box_state,
                r.id AS run_id,r.started_at,r.finished_at,r.heartbeat_at,r.status AS run_status,
                CASE WHEN l.paused THEN 'paused'
                    WHEN l.state<>'active' OR (b.id IS NOT NULL AND b.state<>'active') THEN 'inactive'
                    WHEN r.status='running' AND r.heartbeat_at>now()-interval '15 seconds' THEN 'working'
                    WHEN r.status='running' THEN 'unknown'
                    WHEN r.status='paused' THEN 'paused'
                    WHEN EXISTS(SELECT 1 FROM agent_messages m WHERE m.recipient_agent_id=a.id
                        AND m.read_at IS NULL AND NOT m.silent) THEN 'queued'
                    WHEN r.status='failed' THEN 'error' ELSE 'idle' END AS status,
                h.kind AS activity_kind,h.payload->>'name' AS tool_name
            FROM agents a JOIN letas l ON l.id=a.leta_id LEFT JOIN boxes b ON b.id=a.box_id
            LEFT JOIN LATERAL (SELECT * FROM runs WHERE agent_id=a.id ORDER BY started_at DESC,id DESC LIMIT 1) r ON true
            LEFT JOIN LATERAL (SELECT kind,payload FROM history WHERE agent_id=a.id AND run_id=r.id ORDER BY seq DESC LIMIT 1) h ON true
            WHERE a.leta_id=ANY(%s) AND (b.id IS NULL OR b.state<>'archived') ORDER BY a.created_at,a.id""",
                (roots,),
            )
        ).fetchall()
        boxes = await (
            await conn.execute(
                "SELECT * FROM boxes WHERE leta_id=ANY(%s) AND state<>'archived' ORDER BY created_at,id",
                (roots,),
            )
        ).fetchall()
        edges = await (
            await conn.execute(
                """SELECT e.* FROM box_edges e JOIN boxes b ON b.id=e.box_id
            WHERE b.leta_id=ANY(%s) AND b.state<>'archived'""",
                (roots,),
            )
        ).fetchall()
        schedules = await (
            await conn.execute(
                """SELECT sc.*,a.leta_id,
                (SELECT max(created_at) FROM agent_messages m WHERE m.source_kind='schedule' AND m.source_id=sc.id
                    AND m.recipient_agent_id=sc.target_agent_id) AS last_delivered_at
            FROM schedules sc JOIN agents a ON a.id=sc.creator_agent_id
            LEFT JOIN agents t ON t.id=sc.target_agent_id LEFT JOIN boxes b ON b.id=t.box_id
            WHERE a.leta_id=ANY(%s) AND sc.deleted_at IS NULL AND (b.id IS NULL OR b.state<>'archived')
            ORDER BY sc.created_at,sc.id""",
                (roots,),
            )
        ).fetchall()
    return {
        "agents": [json_row(row) for row in agents],
        "boxes": [json_row(row) for row in boxes],
        "edges": [json_row(row) for row in edges],
        "schedules": [json_row(row) for row in schedules],
        "roots": cast(list[JSON], [str(id) for id in roots]),
    }
