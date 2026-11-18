import json
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from openlet_sdk.config import JSON
from opentelemetry import metrics
from pydantic import Field, model_validator

from .agents import Input, gate, get_agent, json_row, stable
from .auth import Actor, Authorization
from .db import Connection, Pool, Row
from .hitl import render as render_hitl

inbox_count = metrics.get_meter("openlet.leta").create_counter(
    "openlet.leta.inbox.messages"
)
PREVIEW_CHARS = 120


class Message(Input):
    id: UUID
    recipient_agent_id: UUID
    source_kind: Literal["user", "agent", "box", "hitl", "schedule"]
    source_id: UUID
    conversation_id: UUID
    in_reply_to_message_id: UUID | None = None
    in_reply_to_role: Literal["user", "assistant"] | None = None
    scheduled_at: datetime | None = None
    schedule_title: str | None = None
    content: str = Field(max_length=32000)
    file_refs: list[JSON] = Field(default_factory=list[JSON], max_length=20)
    silent: bool = False
    input_type: Literal["message", "reaction"] = "message"
    input_payload: dict[str, JSON] | None = None

    @model_validator(mode="after")
    def nonempty(self) -> Message:
        if not self.content.strip() and not self.file_refs:
            raise ValueError("A message requires content or attachments")
        return self


class SendMessage(Input):
    message_id: UUID
    content: str = Field(min_length=1, max_length=32000)
    in_reply_to: UUID | None = None
    in_reply_to_role: Literal["user", "assistant"] | None = None

    @model_validator(mode="after")
    def reply(self) -> SendMessage:
        if self.in_reply_to_role is not None and self.in_reply_to is None:
            raise ValueError("reply role requires an original message")
        return self


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
        return await admit_in(conn, message, recipient)


async def admit_in(
    conn: Connection, message: Message, recipient: Row
) -> dict[str, JSON]:
    await gate(
        conn,
        cast(UUID, recipient["leta_id"]),
        cast(UUID | None, recipient["box_id"]),
    )
    saved = await (
        await conn.execute("SELECT * FROM agent_messages WHERE id=%s", (message.id,))
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
        if message.source_kind == "user" and message.in_reply_to_role == "assistant":
            original = await (
                await conn.execute(
                    "SELECT conversation_id FROM user_messages WHERE id=%s AND leta_id=%s AND recipient_user_id=%s",
                    (
                        message.in_reply_to_message_id,
                        message.recipient_agent_id,
                        message.source_id,
                    ),
                )
            ).fetchone()
        else:
            original = await (
                await conn.execute(
                    "SELECT conversation_id FROM agent_messages WHERE id=%s AND (%s!='user' OR (recipient_agent_id=%s AND source_kind='user' AND source_id=%s))",
                    (
                        message.in_reply_to_message_id,
                        message.source_kind,
                        message.recipient_agent_id,
                        message.source_id,
                    ),
                )
            ).fetchone()
        if original is None or original["conversation_id"] != message.conversation_id:
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
        in_reply_to_message_id,in_reply_to_role,scheduled_at,schedule_title,content,silent,input_type,input_payload,file_refs) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb)""",
        (
            message.id,
            message.recipient_agent_id,
            counter["inbox_seq"],
            message.source_kind,
            message.source_id,
            message.conversation_id,
            message.in_reply_to_message_id,
            message.in_reply_to_role,
            message.scheduled_at,
            message.schedule_title,
            message.content,
            message.silent,
            message.input_type,
            json.dumps(message.input_payload)
            if message.input_payload is not None
            else None,
            json.dumps(message.file_refs),
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
                "SELECT EXISTS(SELECT 1 FROM agent_messages WHERE recipient_agent_id=%s AND seq>%s AND NOT silent) AS pending",
                (agent_id, after),
            )
        ).fetchone()
    assert row is not None
    return bool(row["pending"])


async def pending(
    db: Pool, agent_id: UUID, after: int, *, root: bool = False, silent_after: int = 0
) -> list[Row]:
    # One extra original character distinguishes a preview from a complete message.
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """WITH normal AS (
                    SELECT seq FROM agent_messages WHERE recipient_agent_id=%s AND seq>%s AND NOT silent ORDER BY seq LIMIT 20
                ), quiet AS (
                    SELECT seq FROM agent_messages WHERE recipient_agent_id=%s AND silent AND seq>%s AND read_at IS NULL
                    AND seq <= (SELECT max(seq) FROM normal) ORDER BY seq LIMIT 20
                ) SELECT m.id,m.seq,m.source_kind,m.source_id,m.conversation_id,m.scheduled_at,m.created_at,m.read_at,
                m.silent,m.input_type,m.input_payload,
                CASE WHEN %s AND m.input_type='message' AND m.source_kind NOT IN ('hitl','schedule')
                    THEN left(m.content,%s)
                    ELSE m.content END AS content,
                coalesce(a.name,b.name) AS source_name,
                CASE WHEN a.id=a.leta_id THEN 'root' ELSE coalesce(a.name,b.name,m.source_id::text) END AS reply_to,
                h.title AS request_title,h.type AS request_type,h.payload AS request_payload,
                m.schedule_title,m.file_refs
                FROM agent_messages m
                LEFT JOIN agents a ON m.source_kind='agent' AND a.id=m.source_id
                LEFT JOIN boxes b ON m.source_kind='box' AND b.id=m.source_id
                LEFT JOIN hitl_requests h ON m.source_kind='hitl' AND h.id=m.source_id
                LEFT JOIN schedules sc ON m.source_kind='schedule' AND sc.id=m.source_id
                WHERE m.recipient_agent_id=%s AND m.seq IN (SELECT seq FROM normal UNION ALL SELECT seq FROM quiet) ORDER BY m.seq""",
                (
                    agent_id,
                    after,
                    agent_id,
                    silent_after,
                    root,
                    PREVIEW_CHARS + 1,
                    agent_id,
                ),
            )
        ).fetchall()
    # Each cursor advances only through a contiguous prefix of its own delivery class.
    # Reserve the budget for normal input so a silent backlog never creates a model-only turn.
    result: list[Row] = []
    size = 0
    for silent in (False, True):
        for row in (r for r in rows if bool(r["silent"]) == silent):
            cost = len(input_batch([row], root=root).encode())
            if result and size + cost > 32000:
                break
            size += cost
            result.append(row)
    result.sort(key=lambda r: int(str(r["seq"])))
    await mark_presented(db, agent_id, result, root=root)
    return result


def is_preview(row: Row, *, root: bool) -> bool:
    return (
        root
        and row.get("input_type", "message") == "message"
        and row["source_kind"] not in ("hitl", "schedule")
        and len(str(row["content"])) > PREVIEW_CHARS
    )


async def mark_presented(db: Pool, agent: UUID, rows: list[Row], *, root: bool) -> None:
    ids = [
        row["id"]
        for row in rows
        if not row.get("silent")
        and row.get("read_at") is None
        and not is_preview(row, root=root)
    ]
    if ids:
        async with db.connection() as conn:
            await conn.execute(
                "UPDATE agent_messages SET read_at=now() WHERE recipient_agent_id=%s AND id=ANY(%s) AND read_at IS NULL",
                (agent, ids),
            )


def reaction_key(row: Row) -> tuple[str, str, str, str]:
    payload = cast(dict[str, JSON], row.get("input_payload") or {})
    target = cast(dict[str, JSON], payload.get("target") or {})
    return (
        str(row.get("source_kind")),
        str(row.get("source_id")),
        str(target.get("kind")),
        str(target.get("message_id")),
    )


def input_batch(rows: list[Row], *, root: bool) -> str:
    latest_reaction = {
        reaction_key(row): row["seq"]
        for row in rows
        if row.get("input_type") == "reaction"
    }
    items: list[str] = []
    for row in rows:
        kind = row["source_kind"]
        if row.get("input_type") == "reaction":
            if latest_reaction[reaction_key(row)] != row["seq"]:
                continue
            event = cast(dict[str, JSON], row.get("input_payload") or {})
            target = cast(dict[str, JSON], event.get("target") or {})
            items.append(
                f"Reaction from {row.get('source_name') or kind} | message={row['seq']} (silent)"
                f"\nTarget: {target.get('message_id')}\nEmoji: {event.get('emoji') or 'removed'}"
                f"\nQuote: {target.get('content', '')}"
            )
        elif kind == "hitl":
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
            sender = str(row.get("source_name") or ("User" if kind == "user" else kind))
            if kind == "box":
                sender = "box " + sender
            body = str(row["content"])
            attached = [
                ref
                for ref in cast(list[JSON], row.get("file_refs") or [])
                if isinstance(ref, dict)
            ]
            if attached:
                from .file_refs import token

                body += "\nAttached files:\n" + "\n".join(
                    token(
                        str(ref["label"]), str(ref["storage_id"]), str(ref["node_id"])
                    )
                    for ref in attached
                )
            header = f"{sender} | message={row['seq']} | to={row['reply_to']}"
            if is_preview(row, root=root):
                body = " ".join(body.split())[: PREVIEW_CHARS - 1] + "…"
                items.append(
                    f"New inbox message from {header}\nPreview: {body}\n[truncated; use inbox_read before acting]"
                )
            else:
                items.append(f"From {header}\nFull message:\n{body}")
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
) -> tuple[str, list[Row]]:
    async with db.connection() as conn, conn.transaction():
        rows = await (
            await conn.execute(
                """SELECT m.*,coalesce(a.name,b.name) AS source_name,
                CASE WHEN a.id=a.leta_id THEN 'root' ELSE coalesce(a.name,b.name,m.source_id::text) END AS reply_to,
                h.title AS request_title,h.type AS request_type,h.payload AS request_payload,m.schedule_title,m.file_refs
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
    return body, rows


def input_data(rows: list[Row], *, root: bool) -> dict[str, JSON]:
    latest_reaction = {
        reaction_key(row): row["seq"]
        for row in rows
        if row.get("input_type") == "reaction"
    }
    items: list[JSON] = []
    for row in rows:
        kind = str(row["source_kind"])
        preview = is_preview(row, root=root)
        item = json_row(
            {
                key: row[key]
                for key in (
                    "id",
                    "seq",
                    "source_kind",
                    "source_id",
                    "conversation_id",
                    "source_name",
                    "scheduled_at",
                    "created_at",
                    "request_title",
                    "request_type",
                    "request_payload",
                    "schedule_title",
                    "silent",
                    "input_type",
                    "input_payload",
                    "file_refs",
                )
                if key in row
            }
        )
        item.update(
            {
                "content": " ".join(str(row["content"]).split())[: PREVIEW_CHARS - 1]
                + "…"
                if preview
                else str(row["content"]),
                "preview": preview,
                "presented": True,
            }
        )
        if row.get("input_type") == "reaction":
            item["presented"] = latest_reaction[reaction_key(row)] == row["seq"]
        if kind == "hitl":
            item["decision"] = cast(JSON, json.loads(str(row["content"])))
        items.append(item)
    return {"version": 1, "kind": "inbox_batch" if root else "messages", "items": items}


async def list_inbox(
    db: Pool,
    agent: UUID,
    after: int = 0,
    unread: bool = True,
    source: UUID | None = None,
) -> tuple[str, list[Row]]:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT n.*,coalesce(a.name,b.name) AS source_name,
                CASE WHEN a.id=a.leta_id THEN 'root' ELSE coalesce(a.name,b.name,n.source_id::text) END AS reply_to,
                h.title AS request_title,h.type AS request_type,h.payload AS request_payload,n.schedule_title
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
    await mark_presented(db, agent, rows, root=True)
    if len(rows) == 20:
        body += f"\nNext cursor: {rows[-1]['seq']}"
    return body, rows


async def deliver_user(
    db: Pool,
    sender: UUID,
    user: UUID,
    content: str,
    id: UUID,
    conversation: UUID,
    reply: UUID | None,
    file_refs: list[JSON] | None = None,
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
            """INSERT INTO user_messages(id,leta_id,recipient_user_id,conversation_id,in_reply_to_message_id,content,file_refs)
            VALUES(%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT(id) DO NOTHING""",
            (
                id,
                sender,
                user,
                conversation,
                reply,
                content,
                json.dumps(file_refs or []),
            ),
        )
    return {"id": str(id)}


def conversation(root: UUID, kind: str, source: UUID) -> UUID:
    return stable(root, f"{kind}/{source}")
