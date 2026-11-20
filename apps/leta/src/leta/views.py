"""Authorized browser projections; callers own the permission check."""

from datetime import datetime
from typing import cast
from uuid import UUID

from openlet_sdk.config import JSON

from .agents import json_row
from .db import Pool, Row
from .file_refs import plaintext
from .reactions import attach


def profile(row: Row, manage: bool, delete: bool = False) -> dict[str, JSON]:
    return {
        **json_row(
            {
                k: row[k]
                for k in (
                    "id",
                    "workspace_id",
                    "name",
                    "title",
                    "appearance",
                    "description",
                    "state",
                    "paused",
                    "model_id",
                    "reasoning_effort",
                    "created_at",
                )
                if k in row
            }
        ),
        "capabilities": {
            "can_chat": row.get("state") == "active",
            "can_view_activity": manage,
            "can_edit_settings": manage,
            "can_delete": delete,
        },
    }


async def chat_summaries(db: Pool, roots: list[UUID], user: UUID) -> dict[UUID, Row]:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT r.id,last.content AS preview,last.created_at AS updated_at,
                reply.id AS latest_reply_id,reply.created_at AS latest_reply_at,
                (SELECT count(*) FROM user_messages WHERE leta_id=r.id
                    AND recipient_user_id=%s AND read_at IS NULL) AS unread_count
            FROM unnest(%s::uuid[]) r(id)
            LEFT JOIN LATERAL (
                SELECT content,created_at,id FROM (
                    SELECT content,created_at,id FROM user_messages
                        WHERE leta_id=r.id AND recipient_user_id=%s
                    UNION ALL
                    SELECT content,created_at,id FROM agent_messages
                        WHERE recipient_agent_id=r.id AND source_kind='user'
                        AND source_id=%s AND input_type='message'
                ) chat ORDER BY created_at DESC,id DESC LIMIT 1
            ) last ON true
            LEFT JOIN LATERAL (
                SELECT id,created_at FROM user_messages
                WHERE leta_id=r.id AND recipient_user_id=%s
                ORDER BY created_at DESC,id DESC LIMIT 1
            ) reply ON true""",
                (user, roots, user, user, user),
            )
        ).fetchall()
    return {
        cast(UUID, row["id"]): {
            **row,
            "preview": plaintext(cast(str, row["preview"]))[:240]
            if row["preview"] is not None
            else None,
        }
        for row in rows
    }


async def mark_chat_read(db: Pool, root: UUID, user: UUID, through: UUID) -> None:
    async with db.connection() as conn:
        boundary = await (
            await conn.execute(
                "SELECT created_at,id FROM user_messages WHERE leta_id=%s AND recipient_user_id=%s AND id=%s",
                (root, user, through),
            )
        ).fetchone()
        if boundary is None:
            raise LookupError("message not found in your conversation")
        await conn.execute(
            """UPDATE user_messages SET read_at=coalesce(read_at,now())
            WHERE leta_id=%s AND recipient_user_id=%s AND read_at IS NULL
                AND (created_at,id)<=(%s,%s)""",
            (root, user, boundary["created_at"], boundary["id"]),
        )


CHAT = """WITH chat AS (
            SELECT id,content,file_refs,created_at,source_id AS user_id,'user'::text AS role,
                conversation_id,read_at,in_reply_to_message_id AS in_reply_to,
                coalesce(in_reply_to_role,'user') AS in_reply_to_role
            FROM agent_messages WHERE recipient_agent_id=%s AND source_kind='user' AND source_id=%s AND input_type='message'
            UNION ALL
            SELECT id,content,file_refs,created_at,recipient_user_id,'assistant',conversation_id,
                NULL::timestamptz,in_reply_to_message_id,'user'
            FROM user_messages WHERE leta_id=%s AND recipient_user_id=%s
            ) """


async def chat(
    db: Pool,
    root: UUID,
    user: UUID,
    before: datetime | None = None,
    cursor: UUID | None = None,
    role: str = "user",
) -> dict[str, JSON]:
    if (before is None) != (cursor is None):
        raise ValueError("before and cursor must be supplied together")
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                CHAT
                + """ SELECT c.*,CASE WHEN q.id IS NULL THEN NULL ELSE
                jsonb_build_object('id',q.id,'role',q.role,'content',q.content) END AS reply
            FROM chat c LEFT JOIN chat q ON q.id=c.in_reply_to AND q.role=c.in_reply_to_role
            WHERE (%s::timestamptz IS NULL OR (c.created_at,c.id,c.role)<(%s,%s,%s))
            ORDER BY c.created_at DESC,c.id DESC,c.role DESC LIMIT 20""",
                (root, user, root, user, before, before, cursor, role),
            )
        ).fetchall()
    for row in rows:
        reply = cast(dict[str, JSON] | None, row["reply"])
        if reply:
            reply["content"] = plaintext(cast(str, reply["content"]))[:240]
    await attach(db, root, rows)
    return {
        "items": [json_row(row) for row in rows],
        "next_cursor": {
            "before": cast(datetime, rows[-1]["created_at"]).isoformat(),
            "cursor": str(rows[-1]["id"]),
            "role": str(rows[-1]["role"]),
        }
        if len(rows) == 20
        else None,
    }


async def chat_context(
    db: Pool, root: UUID, user: UUID, message: UUID, role: str
) -> dict[str, JSON]:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                CHAT
                + """, target AS (
            SELECT created_at,id,role FROM chat WHERE id=%s AND role=%s
        ), around AS (
            (SELECT c.* FROM chat c,target t WHERE (c.created_at,c.id,c.role)<=(t.created_at,t.id,t.role)
             ORDER BY c.created_at DESC,c.id DESC,c.role DESC LIMIT 16)
            UNION ALL
            (SELECT c.* FROM chat c,target t WHERE (c.created_at,c.id,c.role)>(t.created_at,t.id,t.role)
             ORDER BY c.created_at,c.id,c.role LIMIT 15)
        ) SELECT c.*,CASE WHEN q.id IS NULL THEN NULL ELSE
            jsonb_build_object('id',q.id,'role',q.role,'content',q.content) END AS reply
        FROM around c LEFT JOIN chat q ON q.id=c.in_reply_to AND q.role=c.in_reply_to_role
        ORDER BY c.created_at,c.id,c.role""",
                (root, user, root, user, message, role),
            )
        ).fetchall()
    if not rows:
        raise LookupError("message not found in your conversation")
    await attach(db, root, rows)
    return {"items": [json_row(row) for row in rows], "next_cursor": None}


async def requests(
    db: Pool,
    workspace: UUID,
    user: UUID,
    root: UUID | None = None,
    status: str | None = None,
    before: datetime | None = None,
    cursor: UUID | None = None,
) -> dict[str, JSON]:
    if (before is None) != (cursor is None):
        raise ValueError("before and cursor must be supplied together")
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT h.*,a.leta_id,a.name AS requester_name,l.workspace_id FROM hitl_requests h
            JOIN agents a ON a.id=h.requester_agent_id JOIN letas l ON l.id=a.leta_id
            WHERE h.recipient_user_id=%s AND l.workspace_id=%s AND (%s::uuid IS NULL OR a.leta_id=%s)
            AND (%s::text IS NULL OR h.status=%s)
            AND (%s::timestamptz IS NULL OR (h.created_at,h.id)<(%s,%s))
            ORDER BY h.created_at DESC,h.id DESC LIMIT 20""",
                (user, workspace, root, root, status, status, before, before, cursor),
            )
        ).fetchall()
        count = await (
            await conn.execute(
                """SELECT count(*) AS count FROM hitl_requests h JOIN agents a ON a.id=h.requester_agent_id
            JOIN letas l ON l.id=a.leta_id WHERE h.recipient_user_id=%s AND l.workspace_id=%s
            AND (%s::uuid IS NULL OR a.leta_id=%s) AND h.status='pending'""",
                (user, workspace, root, root),
            )
        ).fetchone()
    return {
        "items": [json_row(row) for row in rows],
        "pending_count": cast(int, count["count"]) if count else 0,
        "next_cursor": {
            "before": cast(datetime, rows[-1]["created_at"]).isoformat(),
            "cursor": str(rows[-1]["id"]),
        }
        if len(rows) == 20
        else None,
    }


async def activity(
    db: Pool, agent: UUID, before: int | None = None, after: int | None = None
) -> dict[str, JSON]:
    if before is not None and after is not None:
        raise ValueError("before and after are mutually exclusive")
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT id,agent_id,run_id,seq,kind,created_at,
            CASE WHEN kind='tool_result' AND payload->>'name' IN ('websearch','webfetch') AND payload->>'status'='success'
                    THEN false
                ELSE octet_length(payload::text)>8192 END AS has_details,
            CASE WHEN kind='tool_result' AND payload->>'name' IN ('websearch','webfetch') AND payload->>'status'='success'
                    THEN payload - 'text'
                WHEN octet_length(payload::text)<=8192 THEN payload
                ELSE jsonb_build_object('text',left(payload->>'text',400),'reasoning',left(payload->>'reasoning',400),'name',payload->'name','tool_call_id',payload->'tool_call_id') END AS payload
            FROM history WHERE agent_id=%s AND (%s::bigint IS NULL OR seq<%s)
            AND (%s::bigint IS NULL OR seq>%s) ORDER BY """
                + ("seq ASC" if after is not None else "seq DESC")
                + " LIMIT 20",
                (agent, before, before, after, after),
            )
        ).fetchall()
    await activity_reactions(db, agent, rows)
    return {
        "items": [json_row(row) for row in rows],
        "next_cursor": str(rows[-1]["seq"]) if len(rows) == 20 else None,
    }


async def activity_reactions(db: Pool, agent: UUID, rows: list[Row]) -> None:
    inputs: list[dict[str, object]] = []
    for row in rows:
        payload = cast(dict[str, JSON], row["payload"])
        ui = payload.get("ui")
        items = (
            ui.get("items")
            if isinstance(ui, dict) and ui.get("kind") in ("messages", "inbox_batch")
            else None
        )
        if isinstance(items, list):
            for item in items:
                if (
                    isinstance(item, dict)
                    and item.get("id")
                    and item.get("input_type", "message") == "message"
                ):
                    inputs.append(cast(dict[str, object], item))
    await attach(db, agent, inputs)


async def activity_entry(db: Pool, agent: UUID, entry: UUID) -> dict[str, JSON]:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT * FROM history WHERE agent_id=%s AND id=%s AND octet_length(payload::text)<=262144",
                (agent, entry),
            )
        ).fetchone()
    if row is None:
        raise LookupError(
            "activity entry not found or too large; use paginated history"
        )
    await activity_reactions(db, agent, [row])
    return json_row(row)


# Both directions use one conversation identity; inspecting it must not mark it read.
INBOX = """WITH inbox AS (
    SELECT m.id,m.conversation_id,m.source_kind,m.source_id,m.content,m.created_at,m.read_at,
        'in'::text AS direction,coalesce(a.name,b.name,h.title,sc.title) AS source_name,
        h.type AS request_type,h.payload AS request_payload,m.schedule_title,m.scheduled_at,m.input_type,m.silent,m.input_payload,m.file_refs
    FROM agent_messages m
    LEFT JOIN agents a ON m.source_kind='agent' AND a.id=m.source_id
    LEFT JOIN boxes b ON m.source_kind='box' AND b.id=m.source_id
    LEFT JOIN hitl_requests h ON m.source_kind='hitl' AND h.id=m.source_id
    LEFT JOIN schedules sc ON m.source_kind='schedule' AND sc.id=m.source_id
    WHERE m.recipient_agent_id=%s
    UNION ALL
    SELECT id,conversation_id,'user',recipient_user_id,content,created_at,NULL::timestamptz,
        'out',NULL,NULL,NULL::jsonb,NULL,NULL::timestamptz,'message',false,NULL::jsonb,file_refs FROM user_messages WHERE leta_id=%s
    UNION ALL
    SELECT m.id,m.conversation_id,
        CASE WHEN sender.box_id IS NULL AND target.box_id IS NOT NULL THEN 'box' ELSE 'agent' END,
        CASE WHEN sender.box_id IS NULL AND target.box_id IS NOT NULL THEN target.box_id ELSE target.id END,
        m.content,m.created_at,NULL::timestamptz,'out',coalesce(b.name,target.name),
        NULL,NULL::jsonb,NULL,NULL::timestamptz,m.input_type,m.silent,m.input_payload,m.file_refs
    FROM agents sender LEFT JOIN boxes own ON own.id=sender.box_id
    JOIN agent_messages m ON (m.source_kind='agent' AND m.source_id=sender.id)
        OR (m.source_kind='box' AND m.source_id=own.id AND own.representative_agent_id=sender.id)
    JOIN agents target ON target.id=m.recipient_agent_id
    LEFT JOIN boxes b ON b.id=target.box_id AND sender.box_id IS NULL
    WHERE sender.id=%s
) """


async def inbox(
    db: Pool,
    agent: UUID,
    query: str = "",
    kind: str | None = None,
    unread: bool = False,
    before: datetime | None = None,
    cursor: UUID | None = None,
) -> dict[str, JSON]:
    if (before is None) != (cursor is None):
        raise ValueError("before and cursor must be supplied together")
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                INBOX
                + """, grouped AS (
            SELECT DISTINCT ON (conversation_id) id,conversation_id,source_kind,source_id,
                left(content,180) AS content,created_at,source_name,direction,input_type,silent,input_payload,
                count(*) FILTER (WHERE direction='in' AND read_at IS NULL AND NOT silent) OVER (PARTITION BY conversation_id) AS unread_count
            FROM inbox ORDER BY conversation_id,created_at DESC,id DESC,direction DESC)
            SELECT * FROM grouped WHERE (%s='' OR strpos(lower(coalesce(source_name,'')||' '||content),lower(%s))>0)
            AND (%s::text IS NULL OR source_kind=%s) AND (NOT %s OR unread_count>0)
            AND (%s::timestamptz IS NULL OR (created_at,conversation_id)<(%s,%s))
            ORDER BY created_at DESC,conversation_id DESC LIMIT 20""",
                (
                    agent,
                    agent,
                    agent,
                    query,
                    query,
                    kind,
                    kind,
                    unread,
                    before,
                    before,
                    cursor,
                ),
            )
        ).fetchall()
    return {
        "items": [json_row(row) for row in rows],
        "next_cursor": {
            "before": cast(datetime, rows[-1]["created_at"]).isoformat(),
            "cursor": str(rows[-1]["conversation_id"]),
        }
        if len(rows) == 20
        else None,
    }


async def conversation(
    db: Pool,
    agent: UUID,
    conversation: UUID,
    before: datetime | None = None,
    cursor: UUID | None = None,
    direction: str = "in",
) -> dict[str, JSON]:
    if (before is None) != (cursor is None):
        raise ValueError("before and cursor must be supplied together")
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                INBOX
                + """SELECT * FROM inbox WHERE conversation_id=%s
            AND (%s::timestamptz IS NULL OR (created_at,id,direction)<(%s,%s,%s))
            ORDER BY created_at DESC,id DESC,direction DESC LIMIT 20""",
                (agent, agent, agent, conversation, before, before, cursor, direction),
            )
        ).fetchall()
    await attach(db, agent, rows)
    return {
        "items": [json_row(row) for row in rows],
        "next_cursor": {
            "before": cast(datetime, rows[-1]["created_at"]).isoformat(),
            "cursor": str(rows[-1]["id"]),
            "direction": str(rows[-1]["direction"]),
        }
        if len(rows) == 20
        else None,
    }
