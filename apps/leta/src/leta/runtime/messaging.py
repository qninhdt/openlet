"""One allowed roster and one inbox delivery path for agent messages."""

from uuid import UUID

from openlet.errors import AppError
from pydantic import Field

from leta.domain import Input, NewMessage, fault
from leta.history import InboxItem
from leta.runtime.state import RuntimeContext
from leta.temporal.bridges import deliver_agent_input
from leta.temporal.types import AgentInput


class InboxQuery(Input):
    from_: str | None = Field(default=None, alias="from")
    unread_only: bool = True
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None


async def messaging_roster(context: RuntimeContext) -> list[dict]:
    request = context.request
    if context.agent["kind"] == "leta":
        roster = [
            {
                "type": "user",
                "id": str(context.root["created_by_user_id"]),
                "name": "owner",
            }
        ]
        after = None
        while True:
            page = await context.store.list_boxes(
                request.leta_id, after=after, limit=200
            )
            roster.extend(
                {"type": "box", "id": str(box["id"]), "name": box["name"]}
                for box in page
                if box["status"] == "active"
            )
            if len(page) < 200:
                return roster
            after = page[-1]["id"]
    box = await context.store.get_box_graph(request.leta_id, context.agent["box_id"])
    peers = set()
    for edge in box["edges"]:
        if request.agent_id in (edge["agent_low_id"], edge["agent_high_id"]):
            peers.update((edge["agent_low_id"], edge["agent_high_id"]))
    peers.discard(request.agent_id)
    roster = [
        {"type": "agent", "id": str(agent["id"]), "name": agent["name"]}
        for agent in box["letis"]
        if agent["id"] in peers and agent["status"] == "active"
    ]
    if box["representative_agent_id"] == request.agent_id:
        roster.append({"type": "box", "id": str(box["id"]), "name": "parent"})
    return roster


async def resolve_recipient(context: RuntimeContext, to: str) -> dict:
    roster = await messaging_roster(context)
    try:
        identity = str(UUID(to))
    except ValueError:
        identity = None
    matches = [item for item in roster if item["id"] == identity]
    if not matches:
        matches = [item for item in roster if item["name"] == to]
    if len(matches) != 1:
        raise ValueError("unknown or ambiguous recipient; use an allowed roster ID")
    return matches[0]


async def send_message(
    context: RuntimeContext,
    message_id: UUID,
    to: str,
    content: str,
    in_reply_to: str | None = None,
) -> dict:
    if not content.strip():
        raise ValueError("message content must not be blank")
    # A committed send remains successful after a rename or recipient archive.
    try:
        saved = await context.store.get_message(context.request.leta_id, message_id)
    except AppError as error:
        if error.kind != "missing":
            raise
    else:
        if saved["sender_agent_id"] != context.request.agent_id or (
            saved["content"] != content
            or saved["in_reply_to_message_id"]
            != (UUID(in_reply_to) if in_reply_to else None)
        ):
            raise fault("STATE_CONFLICT", "message identity has different content")
        if saved["recipient_user_id"] is not None:
            target = {
                "type": "user",
                "id": str(saved["recipient_user_id"]),
                "name": "owner",
            }
        elif saved["reply_to"] and saved["reply_to"]["type"] == "box":
            box = await context.store.get_box(
                context.request.leta_id, UUID(saved["reply_to"]["id"])
            )
            target = {
                "type": "box",
                "id": str(box["id"]),
                "name": box["name"] if context.agent["kind"] == "leta" else "parent",
            }
        else:
            recipient = await context.store.get_agent(
                context.request.leta_id, saved["recipient_agent_id"]
            )
            target = {
                "type": "agent",
                "id": str(recipient["id"]),
                "name": recipient["name"],
            }
        try:
            identity = str(UUID(to))
        except ValueError:
            identity = None
        if target["id"] != identity and target["name"] != to:
            raise fault("STATE_CONFLICT", "message identity has a different recipient")
        return {"message_id": str(message_id), "to": target, "status": "sent"}
    target = await resolve_recipient(context, to)
    request, agent = context.request, context.agent
    recipient_agent_id = recipient_user_id = None
    source = {"type": "agent", "id": str(request.agent_id), "label": agent["name"]}
    reply_to = {"type": "agent", "id": request.agent_id}
    if target["type"] == "user":
        recipient_user_id = UUID(target["id"])
        conversation = f"user:{recipient_user_id}"
    elif target["type"] == "box":
        box = await context.store.get_box(request.leta_id, UUID(target["id"]))
        conversation = f"box:{box['id']}"
        reply_to = {"type": "box", "id": box["id"]}
        if agent["kind"] == "leta":
            recipient_agent_id = box["representative_agent_id"]
        else:
            recipient_agent_id = request.leta_id
            source = {"type": "box", "id": str(box["id"]), "label": box["name"]}
    else:
        recipient_agent_id = UUID(target["id"])
        pair = sorted((str(request.agent_id), target["id"]))
        conversation = f"agents:{pair[0]}:{pair[1]}"
    prior_id = UUID(in_reply_to) if in_reply_to else None
    if prior_id:
        prior = await context.store.get_message(request.leta_id, prior_id)
        if prior["recipient_agent_id"] != request.agent_id:
            raise fault(
                "FORBIDDEN", "cannot reply to another agent's input", "forbidden"
            )
        conversation = prior["conversation_key"]
    value = NewMessage(
        id=message_id,
        leta_id=request.leta_id,
        sender_agent_id=request.agent_id,
        recipient_agent_id=recipient_agent_id,
        recipient_user_id=recipient_user_id,
        source=source,
        reply_to=reply_to,
        conversation_key=conversation,
        in_reply_to_message_id=prior_id,
        content=content,
    )
    if recipient_agent_id:
        await deliver_agent_input(context.temporal, AgentInput(message=value))
    else:
        await context.store.receive(value)
        if context.events is not None:
            await context.events.publisher.emit(
                {
                    "type": "CUSTOM",
                    "name": "resource",
                    "value": {
                        "kind": "message",
                        "id": str(message_id),
                        "status": None,
                        "refresh": f"/v1/letas/{request.leta_id}/messages",
                    },
                }
            )
    return {"message_id": str(message_id), "to": target, "status": "sent"}


def inbox_cursor(context, limit, cursor):
    if context.agent["kind"] != "leta":
        raise fault("FORBIDDEN", "Leti has no inbox tools", "forbidden")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if cursor is not None and (
        not cursor.isascii() or not cursor.isdecimal() or int(cursor) < 1
    ):
        raise ValueError("invalid inbox cursor")
    return int(cursor) if cursor else None


async def list_inbox(context, from_=None, unread_only=True, limit=20, cursor=None):
    before = inbox_cursor(context, limit, cursor)
    if from_ is not None:
        candidates = [
            item for item in await messaging_roster(context) if item["name"] == from_
        ]
        if len(candidates) > 1:
            raise ValueError("ambiguous source; use its ID")
        if candidates:
            from_ = candidates[0]["id"]
    found = await context.store.list_inbox_groups(
        context.request.leta_id,
        source_id=from_,
        unread_only=unread_only,
        before=before,
        limit=limit,
    )
    page = found[:limit]
    return {
        "items": [
            {
                "conversation_id": row["conversation_key"],
                "source": {
                    "type": row["source_type"],
                    "id": row["source_id"],
                    "label": row["source_label"],
                },
                "reply_to": row["reply_to"],
                "message_count": row["message_count"],
                "unread_count": row["unread_count"],
                "preview": row["preview"],
            }
            for row in page
        ],
        "next_cursor": str(page[-1]["latest_seq"]) if len(found) > limit else None,
    }


async def read_inbox(context, conversation_id, unread_only=True, limit=20, cursor=None):
    after = inbox_cursor(context, limit, cursor)
    found = await context.store.list_inbox(
        context.request.leta_id,
        context.request.agent_id,
        conversation=conversation_id,
        unread_only=unread_only,
        after=after or 0,
        limit=limit,
        lookahead=True,
    )
    page = found[:limit]
    return {
        "items": [InboxItem.from_row(row).model_dump(mode="json") for row in page],
        "next_cursor": str(page[-1]["seq"]) if len(found) > limit else None,
    }
