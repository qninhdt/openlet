from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from leta.domain import NewMessage, TimeCursor, fault
from leta.http.common import API, Limit, cursor_scope, page, read_cursor, time_position
from leta.http.models import MessageView, Page, SendMessage, message_view
from leta.store import message_values, same
from leta.temporal.bridges import deliver_agent_input
from leta.temporal.types import AgentInput

router = APIRouter()


def owner_message(row, leta_id, user_id):
    return (
        row["recipient_agent_id"] == leta_id
        and row["source_type"] == "owner"
        and row["source_id"] == str(user_id)
    ) or (row["sender_agent_id"] == leta_id and row["recipient_user_id"] == user_id)


@router.post(
    "/v1/letas/{leta_id}/messages", status_code=201, response_model=MessageView
)
async def send(leta_id: UUID, body: SendMessage, context: API):
    await context.root(leta_id, manage=True)
    if not body.content.strip():
        raise fault("VALIDATION", "message content must not be blank", "invalid")
    if body.in_reply_to:
        prior = await context.store.get_message(leta_id, body.in_reply_to)
        if (
            prior["sender_agent_id"] != leta_id
            or prior["recipient_user_id"] != context.actor.id
        ):
            raise fault("NOT_FOUND", "owner message not found", "missing")
    message = NewMessage(
        id=body.id,
        leta_id=leta_id,
        recipient_agent_id=leta_id,
        source={"type": "owner", "id": str(context.actor.id), "label": "owner"},
        reply_to={"type": "user", "id": context.actor.id},
        conversation_key=f"user:{context.actor.id}",
        content=body.content,
        in_reply_to_message_id=body.in_reply_to,
    )
    result = await context.execute(
        deliver_agent_input(context.temporal, AgentInput(message=message)),
        resource_id=body.id,
    )
    if isinstance(result, JSONResponse):
        return result
    row = await context.store.get_message(leta_id, body.id)
    same(row, message_values(message))
    return message_view(row)


@router.get("/v1/letas/{leta_id}/messages", response_model=Page[MessageView])
async def messages(
    leta_id: UUID, context: API, limit: Limit = 20, cursor: str | None = None
):
    await context.root(leta_id)
    scope = cursor_scope("messages", leta_id, context.actor.id)
    found = await context.store.api_messages(
        leta_id,
        context.actor.id,
        after=read_cursor(cursor, scope, TimeCursor),
        limit=limit + 1,
    )
    output = page(found, limit, scope, time_position)
    output["items"] = [message_view(row) for row in found[:limit]]
    return output


@router.get("/v1/letas/{leta_id}/messages/{message_id}", response_model=MessageView)
async def message(leta_id: UUID, message_id: UUID, context: API):
    await context.root(leta_id)
    row = await context.store.get_message(leta_id, message_id)
    if not owner_message(row, leta_id, context.actor.id):
        raise fault("NOT_FOUND", "owner message not found", "missing")
    return message_view(row)


@router.get("/v1/letas/{leta_id}/inbox", response_model=Page[MessageView])
async def inbox(
    leta_id: UUID,
    context: API,
    agent_id: UUID | None = None,
    conversation: str | None = None,
    unread_only: bool = False,
    limit: Limit = 20,
    cursor: str | None = None,
):
    await context.root(leta_id)
    agent_id = agent_id or leta_id
    await context.store.get_agent(leta_id, agent_id)
    scope = cursor_scope("inbox", leta_id, agent_id, conversation, unread_only)
    after = read_cursor(cursor, scope, int)
    if after is not None and after < 0:
        raise fault("VALIDATION", "invalid inbox cursor", "invalid")
    found = await context.store.list_inbox(
        leta_id,
        agent_id,
        after=after or 0,
        conversation=conversation,
        unread_only=unread_only,
        limit=limit,
        lookahead=True,
    )
    output = page(found, limit, scope, lambda row: row["seq"])
    output["items"] = [message_view(row) for row in found[:limit]]
    return output
