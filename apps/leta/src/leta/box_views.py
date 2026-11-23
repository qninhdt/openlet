"""Read-only topology and runtime summaries, after filtering authorized Leta IDs."""

from typing import LiteralString, cast
from uuid import UUID

from openlet_sdk.config import JSON

from .agents import json_row
from .db import Connection, Pool

RUNTIME_STATUS: LiteralString = """CASE WHEN l.paused THEN 'paused'
                    WHEN l.state<>'active' OR (b.id IS NOT NULL AND b.state<>'active') THEN 'inactive'
                    WHEN r.status='running' AND r.heartbeat_at>now()-interval '15 seconds' THEN 'working'
                    WHEN r.status='running' THEN 'unknown'
                    WHEN r.status='paused' THEN 'paused'
                    WHEN EXISTS(SELECT 1 FROM agent_messages m WHERE m.recipient_agent_id=a.id
                        AND m.read_at IS NULL AND NOT m.silent) THEN 'queued'
                    WHEN r.status='failed' THEN 'error' ELSE 'idle' END AS status"""


async def graph(db: Pool, roots: list[UUID]) -> dict[str, JSON]:
    async with db.connection() as conn:
        agents = await (
            await conn.execute(
                """SELECT a.id,a.leta_id,a.box_id,a.name,a.title,a.handle,a.appearance,a.description,
                a.model_id,a.reasoning_effort,l.paused,l.state,b.state AS box_state,
                r.id AS run_id,r.started_at,r.finished_at,r.heartbeat_at,r.status AS run_status,
                """
                + RUNTIME_STATUS
                + """,
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
        links = await (
            await conn.execute(
                """SELECT e.* FROM box_links e JOIN boxes b ON b.id=e.box_id
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
        "additional_links": [json_row(row) for row in links],
        "schedules": [json_row(row) for row in schedules],
        "letas": cast(list[JSON], [str(id) for id in roots]),
    }


async def status(conn: Connection, id: UUID, activity_limit: int) -> dict[str, JSON]:
    observation = await (
        await conn.execute(
            """SELECT a.name,a.title,a.handle,coalesce(b.leader_agent_id=a.id,false) AS is_leader,
                now() AS observed_at,r.id AS run_id,r.status AS run_status,
                r.started_at,r.finished_at,r.error_code,
                """
            + RUNTIME_STATUS
            + """
            FROM agents a JOIN letas l ON l.id=a.leta_id LEFT JOIN boxes b ON b.id=a.box_id
            LEFT JOIN LATERAL (SELECT * FROM runs WHERE agent_id=a.id ORDER BY started_at DESC,id DESC LIMIT 1) r ON true
            WHERE a.id=%s""",
            (id,),
        )
    ).fetchone()
    if observation is None:
        raise LookupError("agent not found")
    run = observation.pop("run_id")
    result: dict[str, JSON] = json_row(observation)
    result["assignment_inputs"] = []
    result["recent_activity"] = []
    if run is None:
        return result
    assignments = await (
        await conn.execute(
            """SELECT a.handle AS sender,m.task_label,m.seq AS message,left(m.content,800) AS preview
            FROM agent_messages m JOIN agents a ON a.id=m.source_id
            WHERE m.recipient_agent_id=%s AND m.processing_run_id=%s AND m.source_kind='agent'
            AND m.input_type='message' ORDER BY m.seq DESC LIMIT 10""",
            (id, run),
        )
    ).fetchall()
    activity = await (
        await conn.execute(
            """SELECT h.created_at,h.payload->>'name' AS tool,left(h.payload->>'args',500) AS arguments,
                result.payload->>'status' AS status,
                left(result.payload->>'text',500) AS result
            FROM history h LEFT JOIN LATERAL (
                SELECT payload FROM history r WHERE r.agent_id=h.agent_id
                AND r.kind='tool_result' AND r.payload->>'tool_call_id'=h.payload->>'tool_call_id'
                AND r.seq>h.seq ORDER BY r.seq LIMIT 1
            ) result ON true
            WHERE h.agent_id=%s AND h.run_id=%s AND h.kind='tool_call' ORDER BY h.seq DESC LIMIT %s""",
            (id, run, activity_limit),
        )
    ).fetchall()
    result["assignment_inputs"] = [json_row(row) for row in reversed(assignments)]
    result["recent_activity"] = [json_row(row) for row in reversed(activity)]
    return result
