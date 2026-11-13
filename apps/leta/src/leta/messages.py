from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from openlet_sdk.config import JSON
from pydantic import Field

from .agents import Input, gate, get_agent, stable
from .auth import Actor, Authorization
from .db import Pool, Row


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
            sender = await get_agent(db, sender_id)
            await gate(
                conn, cast(UUID, sender["leta_id"]), cast(UUID | None, sender["box_id"])
            )
            if sender["leta_id"] != recipient["leta_id"]:
                raise ValueError("cross-Leta delivery is not allowed")
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
        return {"id": str(message.id), "seq": cast(int, counter["inbox_seq"])}


async def pending(db: Pool, agent_id: UUID, after: int) -> list[Row]:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT m.*,coalesce(a.name,b.name) AS source_name
            FROM agent_messages m LEFT JOIN agents a ON m.source_kind='agent' AND a.id=m.source_id
            LEFT JOIN boxes b ON m.source_kind='box' AND b.id=m.source_id
            WHERE recipient_agent_id=%s AND seq>%s ORDER BY seq LIMIT 20""",
                (agent_id, after),
            )
        ).fetchall()
    size = 0
    result: list[Row] = []
    for row in rows:
        size += len(str(row["content"]).encode())
        if result and size > 32000:
            break
        result.append(row)
    return result


def input_batch(rows: list[Row], *, root: bool) -> dict[str, JSON]:
    items: list[JSON] = []
    conversations: set[str] = set()
    for row in rows:
        source: dict[str, JSON] = {
            "kind": str(row["source_kind"]),
            "id": str(row["source_id"]),
        }
        if row.get("source_name"):
            source["name"] = str(row["source_name"])
        if root:
            conversation = str(row["conversation_id"])
            if conversation in conversations:
                continue
            conversations.add(conversation)
            items.append(
                {
                    "conversation_id": conversation,
                    "source": source,
                    "preview": str(row["content"])[:240],
                }
            )
        else:
            item: dict[str, JSON] = {
                "message_id": str(row["id"]),
                "source": source,
                "content": str(row["content"]),
                "created_at": cast(datetime, row["created_at"]).isoformat(),
            }
            if row["in_reply_to_message_id"]:
                item["in_reply_to"] = str(row["in_reply_to_message_id"])
            if row["scheduled_at"]:
                item["scheduled_at"] = cast(datetime, row["scheduled_at"]).isoformat()
            items.append(item)
    return {"notifications" if root else "messages": items}


async def read(
    db: Pool, agent: UUID, conversation: UUID, after: int = 0, unread: bool = True
) -> dict[str, JSON]:
    async with db.connection() as conn, conn.transaction():
        rows = await (
            await conn.execute(
                """SELECT * FROM agent_messages WHERE recipient_agent_id=%s AND conversation_id=%s
            AND seq>%s AND (NOT %s OR read_at IS NULL) ORDER BY seq LIMIT 20 FOR UPDATE""",
                (agent, conversation, after, unread),
            )
        ).fetchall()
        await conn.execute(
            "UPDATE agent_messages SET read_at=coalesce(read_at,now()) WHERE id=ANY(%s)",
            ([r["id"] for r in rows],),
        )
    return {
        "messages": input_batch(rows, root=False)["messages"],
        "next_cursor": str(rows[-1]["seq"]) if len(rows) == 20 else None,
    }


async def list_inbox(
    db: Pool,
    agent: UUID,
    after: int = 0,
    unread: bool = True,
    source: UUID | None = None,
) -> dict[str, JSON]:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT DISTINCT ON (conversation_id) * FROM agent_messages WHERE recipient_agent_id=%s
            AND seq>%s AND (NOT %s OR read_at IS NULL) AND (%s::uuid IS NULL OR source_id=%s)
            ORDER BY conversation_id,seq LIMIT 20""",
                (agent, after, unread, source, source),
            )
        ).fetchall()
    return input_batch(rows, root=True)


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
                    "reply must belong to the addressed human conversation"
                )
        await conn.execute(
            """INSERT INTO user_messages(id,leta_id,recipient_user_id,conversation_id,in_reply_to_message_id,content)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
            (id, sender, user, conversation, reply, content),
        )
    return {"id": str(id)}


def conversation(root: UUID, kind: str, source: UUID) -> UUID:
    return stable(root, f"{kind}/{source}")
