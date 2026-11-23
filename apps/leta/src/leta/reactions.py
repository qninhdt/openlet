"""One reaction per actor and delivery; user feedback is a durable silent input."""

from typing import Literal, cast
from uuid import UUID

import regex
from openlet_sdk.config import JSON
from pydantic import field_validator

from . import messages
from .agents import Input, gate, get_agent, stable
from .auth import Actor, Authorization
from .db import Pool


class React(Input):
    request_id: UUID
    emoji: str | None

    @field_validator("emoji")
    @classmethod
    def valid_emoji(cls, value: str | None) -> str | None:
        if value is not None and (
            len(value) > 64
            or not regex.fullmatch(r"\X", value)
            or not regex.search(
                r"\p{Extended_Pictographic}|\p{Regional_Indicator}|[#*0-9]\ufe0f?\u20e3",
                value,
            )
        ):
            raise ValueError("emoji must be one complete Unicode emoji")
        return value


async def react(
    db: Pool,
    auth: Authorization,
    root: UUID,
    message: UUID,
    kind: Literal["incoming", "outgoing"],
    actor: Actor,
    change: React,
) -> dict[str, JSON]:
    from .db import receipt, save_receipt

    agent = await get_agent(db, root if actor.kind == "user" else actor.id)
    if actor.kind == "user":
        await auth.require(actor, "agent", root, "use")
    if agent["leta_id"] != root:
        raise PermissionError("reaction is outside this Leta")
    async with db.connection() as conn, conn.transaction():
        await gate(conn, root, cast(UUID | None, agent["box_id"]))
        method = f"reaction:{root}:{kind}:{message}"
        saved = await receipt(
            conn, f"{actor.kind}:{actor.id}", method, change.request_id, change
        )
        if saved is not None:
            return cast(dict[str, JSON], saved)
        if kind == "outgoing":
            original = await (
                await conn.execute(
                    "SELECT *,recipient_user_id AS user_id FROM user_messages WHERE leta_id=%s AND id=%s",
                    (root, message),
                )
            ).fetchone()
            if (
                actor.kind != "user"
                or original is None
                or original["user_id"] != actor.id
            ):
                raise LookupError("message not found in your conversation")
            recipient = agent
        else:
            original = await (
                await conn.execute(
                    "SELECT *,source_id AS user_id FROM agent_messages WHERE id=%s AND input_type='message' AND source_kind IN ('user','agent')",
                    (message,),
                )
            ).fetchone()
            if original is None:
                raise LookupError("message not found")
            if actor.kind == "user":
                if (
                    original["recipient_agent_id"] != root
                    or original["source_kind"] != "user"
                    or original["source_id"] != actor.id
                ):
                    raise LookupError("message not found in your conversation")
            elif original["recipient_agent_id"] != actor.id:
                raise PermissionError("agent can react only to received messages")
            recipient = None
            if actor.kind == "agent" and original["source_kind"] == "user":
                await auth.require(
                    Actor("user", cast(UUID, original["source_id"])),
                    "workspace",
                    cast(UUID, agent["workspace_id"]),
                    "participate",
                )
            if actor.kind == "agent" and original["source_kind"] == "agent":
                target = cast(UUID, original["source_id"])
                recipient = await (
                    await conn.execute(
                        "SELECT id,leta_id,box_id FROM agents WHERE id=%s", (target,)
                    )
                ).fetchone()
                if recipient is None:
                    raise LookupError("source agent not found")
        previous = await (
            await conn.execute(
                "SELECT emoji FROM message_reactions WHERE leta_id=%s AND message_kind=%s AND message_id=%s AND actor_kind=%s AND actor_id=%s",
                (root, kind, message, actor.kind, actor.id),
            )
        ).fetchone()
        old = str(previous["emoji"]) if previous else None
        user = cast(
            UUID | None,
            original["user_id"]
            if kind == "outgoing" or original["source_kind"] == "user"
            else None,
        )
        result: dict[str, JSON] = {
            "message_id": str(message),
            "kind": kind,
            "emoji": change.emoji,
            "user_id": str(user) if user else None,
            "content": str(original["content"])[:240],
        }
        if old != change.emoji:
            if change.emoji is None:
                await conn.execute(
                    "DELETE FROM message_reactions WHERE leta_id=%s AND message_kind=%s AND message_id=%s AND actor_kind=%s AND actor_id=%s",
                    (root, kind, message, actor.kind, actor.id),
                )
            else:
                await conn.execute(
                    """INSERT INTO message_reactions(leta_id,message_kind,message_id,actor_kind,actor_id,emoji)
                    VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(leta_id,message_kind,message_id,actor_kind,actor_id)
                    DO UPDATE SET emoji=excluded.emoji,updated_at=now()""",
                    (root, kind, message, actor.kind, actor.id, change.emoji),
                )
            if recipient is not None:
                payload: dict[str, JSON] = {
                    "actor": {"kind": actor.kind, "id": str(actor.id)},
                    "target": {
                        "message_id": str(message),
                        "kind": kind,
                        "content": str(original["content"])[:240],
                    },
                    "previous_emoji": old,
                    "emoji": change.emoji,
                }
                notification = messages.Message(
                    id=stable(
                        change.request_id,
                        f"reaction/{root}/{kind}/{message}/{actor.id}",
                    ),
                    recipient_agent_id=cast(UUID, recipient["id"]),
                    source_kind="user" if actor.kind == "user" else "agent",
                    source_id=actor.id,
                    conversation_id=cast(UUID, original["conversation_id"]),
                    content=f"Reacted {change.emoji or '(removed)'}: {str(original['content'])[:240]}",
                    silent=True,
                    input_type="reaction",
                    input_payload=payload,
                )
                await messages.admit_in(conn, notification, recipient)
        await save_receipt(
            conn, f"{actor.kind}:{actor.id}", method, change.request_id, change, result
        )
    return result


async def attach(db: Pool, root: UUID, items: list[dict[str, object]]) -> None:
    if not items:
        return
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT message_id,message_kind,actor_kind,actor_id,emoji FROM message_reactions WHERE leta_id=(SELECT leta_id FROM agents WHERE id=%s) AND message_id=ANY(%s) ORDER BY updated_at,actor_id",
                (root, [UUID(str(item["id"])) for item in items]),
            )
        ).fetchall()
    for item in items:
        kind = (
            "outgoing"
            if item.get("role") == "assistant" or item.get("direction") == "out"
            else "incoming"
        )
        item["reactions"] = [
            {
                "actor_kind": r["actor_kind"],
                "actor_id": str(r["actor_id"]),
                "emoji": r["emoji"],
            }
            for r in rows
            if str(r["message_id"]) == str(item["id"]) and r["message_kind"] == kind
        ]
