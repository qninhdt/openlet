import json
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from openlet_sdk.config import JSON
from opentelemetry import metrics
from pydantic import Field

from .agents import Input, gate, get_agent, stable
from .auth import Actor, Authorization
from .db import Pool, Row
from .hitl import render as render_hitl

inbox_count = metrics.get_meter("openlet.leta").create_counter(
    "openlet.leta.inbox.messages"
)


class Message(Input):
    id: UUID
    recipient_agent_id: UUID
    source_kind: Literal["user", "agent", "box", "hitl", "schedule"]
    source_id: UUID
    conversation_id: UUID
    in_reply_to_message_id: UUID | None = None
    scheduled_at: datetime | None = None
    content: str = Field(min_length=1, max_length=32000)


class SendMessage(Input):
    message_id: UUID
    content: str = Field(min_length=1, max_length=32000)
    in_reply_to: UUID | None = None


async def admit(db: Pool, auth: Authorization, message: Message) -> dict[str, JSON]:
    recipient = await get_agent(db, message.recipient_agent_id)
    if message.source_kind == "user":
        if recipient["box_id"] is not None:
            raise ValueError("human messages must address root")
        await auth.require(
            Actor("user", message.source_id),
            "agent",
            cast(UUID, recipient["leta_id"]),
            "use",
        )
    async with db.connection() as conn, conn.transaction():
        await gate(
            conn,
            cast(UUID, recipient["leta_id"]),
            cast(UUID | None, recipient["box_id"]),
        )
        saved = await (
            await conn.execute(
                "SELECT * FROM agent_messages WHERE id=%s", (message.id,)
            )
        ).fetchone()
        if saved is not None:
            for key, value in message.model_dump().items():
                if saved[key] != value:
                    raise ValueError("message ID was already used with different input")
            return {"id": str(message.id), "seq": cast(int, saved["seq"])}
        if message.source_kind in ("agent", "box"):
            if message.source_kind == "box":
                source = await (
                    await conn.execute(
                        "SELECT representative_agent_id FROM boxes WHERE id=%s AND state='active'",
                        (message.source_id,),
                    )
                ).fetchone()
                if source is None:
                    raise ValueError("source box is inactive")
                sender_id = cast(UUID, source["representative_agent_id"])
            else:
                sender_id = message.source_id
            sender = await (
                await conn.execute(
                    "SELECT id,leta_id,box_id FROM agents WHERE id=%s", (sender_id,)
                )
            ).fetchone()
            if sender is None:
                raise LookupError("sender not found")
            if sender["leta_id"] != recipient["leta_id"]:
                raise ValueError("cross-Leta delivery is not allowed")
            if sender["box_id"] is not None and sender["box_id"] != recipient["box_id"]:
                await gate(
                    conn, cast(UUID, sender["leta_id"]), cast(UUID, sender["box_id"])
                )
            if sender["box_id"] is None:
                edge = await (
                    await conn.execute(
                        "SELECT 1 FROM boxes WHERE id=%s AND representative_agent_id=%s",
                        (recipient["box_id"], message.recipient_agent_id),
                    )
                ).fetchone()
            elif recipient["box_id"] is None:
                edge = await (
                    await conn.execute(
                        "SELECT 1 FROM boxes WHERE id=%s AND representative_agent_id=%s",
                        (sender["box_id"], sender_id),
                    )
                ).fetchone()
            elif sender["box_id"] == recipient["box_id"]:
                low, high = sorted((sender_id, message.recipient_agent_id))
                edge = await (
                    await conn.execute(
                        "SELECT 1 FROM box_edges WHERE box_id=%s AND agent_low_id=%s AND agent_high_id=%s",
                        (sender["box_id"], low, high),
                    )
                ).fetchone()
            else:
                edge = None
            if edge is None:
                raise ValueError("recipient is outside the communication graph")
        if message.source_kind == "schedule":
            row = await (
                await conn.execute(
                    "SELECT 1 FROM schedules WHERE id=%s AND deleted_at IS NULL AND NOT paused",
                    (message.source_id,),
                )
            ).fetchone()
            if row is None:
                return {"skipped": True}
        if message.in_reply_to_message_id:
            original = await (
                await conn.execute(
                    "SELECT conversation_id FROM agent_messages WHERE id=%s",
                    (message.in_reply_to_message_id,),
                )
            ).fetchone()
            if (
                original is None
                or original["conversation_id"] != message.conversation_id
            ):
                raise ValueError("reply must belong to this conversation")
        counter = await (
            await conn.execute(
                "UPDATE agents SET inbox_seq=inbox_seq+1 WHERE id=%s RETURNING inbox_seq",
                (message.recipient_agent_id,),
            )
        ).fetchone()
        assert counter is not None
        await conn.execute(
            """INSERT INTO agent_messages(id,recipient_agent_id,seq,source_kind,source_id,conversation_id,
            in_reply_to_message_id,scheduled_at,content) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                message.id,
                message.recipient_agent_id,
                counter["inbox_seq"],
                message.source_kind,
                message.source_id,
                message.conversation_id,
                message.in_reply_to_message_id,
                message.scheduled_at,
                message.content,
            ),
        )
    inbox_count.add(
        1,
        {
            "direction": "accepted",
            "agent_role": "leti" if recipient["box_id"] else "root",
        },
    )
    return {"id": str(message.id), "seq": cast(int, counter["inbox_seq"])}


async def has_pending(db: Pool, agent_id: UUID, after: int) -> bool:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT EXISTS(SELECT 1 FROM agent_messages WHERE recipient_agent_id=%s AND seq>%s) AS pending",
                (agent_id, after),
            )
        ).fetchone()
    assert row is not None
    return bool(row["pending"])


async def pending(
    db: Pool, agent_id: UUID, after: int, *, root: bool = False
) -> list[Row]:
    # Keep a character beyond a trailing space so rendering still detects truncation.
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT m.seq,m.source_kind,m.source_id,m.conversation_id,m.scheduled_at,m.created_at,
                CASE WHEN %s AND m.source_kind NOT IN ('hitl','schedule')
                    THEN left(trim(regexp_replace(m.content,'[[:space:]]+',' ','g')),122)
                    ELSE m.content END AS content,
                coalesce(a.name,b.name) AS source_name,
                h.title AS request_title,h.type AS request_type,h.payload AS request_payload,
                sc.title AS schedule_title
                FROM agent_messages m
                LEFT JOIN agents a ON m.source_kind='agent' AND a.id=m.source_id
                LEFT JOIN boxes b ON m.source_kind='box' AND b.id=m.source_id
                LEFT JOIN hitl_requests h ON m.source_kind='hitl' AND h.id=m.source_id
                LEFT JOIN schedules sc ON m.source_kind='schedule' AND sc.id=m.source_id
                WHERE m.recipient_agent_id=%s AND m.seq>%s ORDER BY m.seq LIMIT 20""",
                (root, agent_id, after),
            )
        ).fetchall()
    size = 0
    result: list[Row] = []
    for row in rows:
        size += len(input_batch([row], root=root).encode())
        if result and size > 32000:
            break
        result.append(row)
    return result


def input_batch(rows: list[Row], *, root: bool) -> str:
    latest = {row["conversation_id"]: row["seq"] for row in rows}
    items: list[str] = []
    for row in rows:
        kind = row["source_kind"]
        if kind == "hitl":
            event = cast(dict[str, JSON], json.loads(str(row["content"])))
            items.append(
                render_hitl(
                    {
                        **event,
                        "id": str(row["source_id"]),
                        "title": str(row.get("request_title") or "Human decision"),
                        "type": str(row.get("request_type") or "ask"),
                        "payload": cast(JSON, row.get("request_payload") or {}),
                    }
                )
            )
        elif kind == "schedule":
            items.append(
                f"Scheduled task: {row.get('schedule_title') or 'Scheduled instruction'} | schedule={row['source_id']}"
                f"\nScheduled for: {row['scheduled_at']}\n{row['content']}"
            )
        else:
            if root and latest[row["conversation_id"]] != row["seq"]:
                continue
            sender = str(row.get("source_name") or ("User" if kind == "user" else kind))
            if kind == "box":
                sender = "box " + sender
            body = str(row["content"])
            if root:
                body = " ".join(body.split())
                if len(body) > 120:
                    body = body[:119] + "…"
                items.append(
                    f"New inbox message from {sender} | message={row['seq']}\nPreview: {body}"
                )
            else:
                items.append(f"From {sender} | message={row['seq']}\n{body}")
    return "\n\n---\n\n".join(items)


async def incoming(db: Pool, agent: UUID, seq: int) -> Row:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT * FROM agent_messages WHERE recipient_agent_id=%s AND seq=%s",
                (agent, seq),
            )
        ).fetchone()
    if row is None:
        raise LookupError(
            "incoming message not found; use a message number from your inbox"
        )
    return row


async def read(
    db: Pool, agent: UUID, message: int, after: int = 0, unread: bool = True
) -> str:
    async with db.connection() as conn, conn.transaction():
        rows = await (
            await conn.execute(
                """SELECT m.*,coalesce(a.name,b.name) AS source_name,
                h.title AS request_title,h.type AS request_type,h.payload AS request_payload,sc.title AS schedule_title
                FROM (SELECT recipient_agent_id,conversation_id FROM agent_messages
                    WHERE recipient_agent_id=%s AND seq=%s) original
            LEFT JOIN LATERAL (
                SELECT * FROM agent_messages
                WHERE recipient_agent_id=original.recipient_agent_id AND conversation_id=original.conversation_id
                AND seq>%s AND (NOT %s OR read_at IS NULL)
                ORDER BY seq LIMIT 20 FOR UPDATE
            ) m ON true
            LEFT JOIN agents a ON m.source_kind='agent' AND a.id=m.source_id
            LEFT JOIN boxes b ON m.source_kind='box' AND b.id=m.source_id
            LEFT JOIN hitl_requests h ON m.source_kind='hitl' AND h.id=m.source_id
            LEFT JOIN schedules sc ON m.source_kind='schedule' AND sc.id=m.source_id
            ORDER BY m.seq""",
                (agent, message, after, unread),
            )
        ).fetchall()
        if not rows:
            raise LookupError(
                "incoming message not found; use a message number from your inbox"
            )
        rows = [row for row in rows if row["id"] is not None]
        await conn.execute(
            "UPDATE agent_messages SET read_at=coalesce(read_at,now()) WHERE id=ANY(%s)",
            ([r["id"] for r in rows],),
        )
    body = (
        input_batch(rows, root=False)
        or "No messages matching this conversation and filter."
    )
    if len(rows) == 20:
        body += f"\nNext cursor: {rows[-1]['seq']}"
    return body


async def list_inbox(
    db: Pool,
    agent: UUID,
    after: int = 0,
    unread: bool = True,
    source: UUID | None = None,
) -> str:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT n.*,coalesce(a.name,b.name) AS source_name,
                h.title AS request_title,h.type AS request_type,h.payload AS request_payload,sc.title AS schedule_title
                FROM (
                SELECT DISTINCT ON (conversation_id) * FROM agent_messages
                WHERE recipient_agent_id=%s AND seq>%s AND (NOT %s OR read_at IS NULL)
                AND (%s::uuid IS NULL OR source_id=%s)
                ORDER BY conversation_id,seq DESC
            ) n LEFT JOIN agents a ON n.source_kind='agent' AND a.id=n.source_id
            LEFT JOIN boxes b ON n.source_kind='box' AND b.id=n.source_id
            LEFT JOIN hitl_requests h ON n.source_kind='hitl' AND h.id=n.source_id
            LEFT JOIN schedules sc ON n.source_kind='schedule' AND sc.id=n.source_id
            ORDER BY n.seq LIMIT 20""",
                (agent, after, unread, source, source),
            )
        ).fetchall()
    body = input_batch(rows, root=True) or "No messages matching this inbox filter."
    if len(rows) == 20:
        body += f"\nNext cursor: {rows[-1]['seq']}"
    return body


async def deliver_user(
    db: Pool,
    sender: UUID,
    user: UUID,
    content: str,
    id: UUID,
    conversation: UUID,
    reply: UUID | None,
) -> dict[str, JSON]:
    async with db.connection() as conn, conn.transaction():
        await gate(conn, sender)
        if reply:
            original = await (
                await conn.execute(
                    "SELECT 1 FROM agent_messages WHERE id=%s AND recipient_agent_id=%s AND source_kind='user' AND source_id=%s AND conversation_id=%s",
                    (reply, sender, user, conversation),
                )
            ).fetchone()
            if original is None:
                raise ValueError(
                    "in_reply_to must be a message ID from this user's inbox_read results, "
                    "not a conversation ID or another sender's message; omit it for a new message"
                )
        await conn.execute(
            """INSERT INTO user_messages(id,leta_id,recipient_user_id,conversation_id,in_reply_to_message_id,content)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
            (id, sender, user, conversation, reply, content),
        )
    return {"id": str(id)}


def conversation(root: UUID, kind: str, source: UUID) -> UUID:
    return stable(root, f"{kind}/{source}")
