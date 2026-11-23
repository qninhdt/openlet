import asyncio
import json
import posixpath
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Literal, cast
from uuid import UUID

import grpc
from fastapi import HTTPException
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from langfuse import propagate_attributes
from mirage import ContentType, FileStat, FileType, Session
from openlet_api.platform.v1 import internal_pb2 as platform
from openlet_api.platform.v1 import platform_pb2 as platform_api
from openlet_sdk.config import JSON
from pydantic import AfterValidator, Field, model_validator

from .. import (
    box_views,
    boxes,
    conversations,
    file_refs,
    history,
    hitl,
    reactions,
    schedules,
)
from .. import messages as inbox_messages
from ..agents import Input, json_row, stable
from ..auth import Actor
from ..boxes import BoxCreation, CreateBox, LetiDefinition
from ..config import Services
from ..db import Row
from ..filesystem.letfs import current_operation
from ..filesystem.workspace import Filesystem, scope, shell
from ..filesystem.workspace import path as file_path
from ..jobs.resources import ResourceOperation
from ..messages import Message
from ..output import BYTE_BUDGET, text_page
from ..web import public_url, web_request
from .inbox import State

type Status = Literal[
    "pending", "answered", "accepted", "denied", "cancelled", "expired"
]


def presented(kind: str, content: JSON, data: JSON) -> tuple[JSON, dict[str, JSON]]:
    return content, {"ui": {"version": 1, "kind": kind, "data": data}}


def file_reference(metadata: FileStat) -> dict[str, JSON]:
    return {
        key: metadata.extra[key]
        for key in ("storage_id", "node_id")
        if isinstance(metadata.extra.get(key), str) and metadata.extra[key]
    }


@dataclass
class Context:
    services: Services
    agent: Row
    run_id: UUID
    filesystem: Filesystem

    @property
    def id(self) -> UUID:
        return cast(UUID, self.agent["id"])

    @property
    def leta_id(self) -> UUID:
        return cast(UUID, self.agent["leta_id"])


def request_id(runtime: ToolRuntime[Context, State]) -> UUID:
    assert runtime.tool_call_id is not None
    return stable(runtime.context.id, runtime.tool_call_id)


async def session(runtime: ToolRuntime[Context, State]) -> Session:
    return await runtime.context.filesystem.open()


async def user_id(ctx: Context, handle: str) -> UUID:
    try:
        user = await ctx.services.internal.GetUserByHandle(
            platform.UserHandleRequest(handle=handle), timeout=15
        )
    except grpc.aio.AioRpcError as error:
        if error.code() == grpc.StatusCode.NOT_FOUND:
            raise LookupError("user handle not found") from None
        raise
    return UUID(user.id)


async def inbox_address(ctx: Context, address: str) -> tuple[str, UUID]:
    kind, _, handle = address.partition(":")
    if kind == "user" and handle:
        return kind, await user_id(ctx, handle)
    if kind == "agent" and handle:
        async with ctx.services.db.connection() as conn:
            agent = await (
                await conn.execute(
                    "SELECT id FROM agents WHERE leta_id=%s AND handle=%s",
                    (ctx.leta_id, handle),
                )
            ).fetchone()
        if agent is None:
            raise LookupError("agent handle not found")
        return kind, cast(UUID, agent["id"])
    raise ValueError("Use a user:<handle> or agent:<handle> address")


class WebSource(Input):
    url: Annotated[str, AfterValidator(public_url)]
    title: str = Field(min_length=1, max_length=300)


class StorageSource(Input):
    path: str = Field(min_length=1, max_length=4096)
    page: int | None = Field(default=None, ge=1)
    line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def location(self) -> "StorageSource":
        if self.page is not None and self.line is not None:
            raise ValueError("Use either a page or a line for the source")
        return self


class InboxMessage(Input):
    content: str = Field(default="", max_length=32000)
    attachments: list[Annotated[str, Field(min_length=1, max_length=4096)]] = Field(
        default_factory=list, max_length=20
    )
    sources: list[WebSource | StorageSource] = Field(
        default_factory=list[WebSource | StorageSource], max_length=20
    )

    @model_validator(mode="after")
    def nonempty(self) -> "InboxMessage":
        if not self.content.strip() and not self.attachments:
            raise ValueError("A message requires content or attachments")
        if self.sources:
            markers = set(
                re.findall(r"(?<!\\)\[([1-9][0-9]*)\](?![(:\[])", self.content)
            )
            missing = [
                f"[{index}]"
                for index in range(1, len(self.sources) + 1)
                if str(index) not in markers
            ]
            if missing:
                raise ValueError(
                    f"Add the matching source markers: {', '.join(missing)}"
                )
        return self


async def prepare_outgoing(
    runtime: ToolRuntime[Context, State],
    message: InboxMessage,
    id: UUID,
    target: UUID,
    *,
    human: bool,
    copy_folders: bool,
) -> inbox_messages.Outgoing:
    ctx = runtime.context
    s, agent = ctx.services, ctx.agent
    content = message.content
    attachment_content = ""
    sources: list[JSON] = []
    recipient = Actor("user", target) if human else Actor("agent", ctx.leta_id)
    checked_storage: set[UUID] = set()
    has_attachments = bool(
        message.attachments or file_refs.PATH_PATTERN.search(content)
    )
    vfs = (
        (await session(runtime)).vfs
        if has_attachments
        or any(isinstance(source, StorageSource) for source in message.sources)
        else None
    )

    async def stat(path: str) -> FileStat:
        assert vfs is not None
        return await vfs.stat(file_path(path))

    try:
        for source in message.sources:
            if isinstance(source, WebSource):
                sources.append(
                    {"kind": "web", "url": source.url, "title": source.title}
                )
                continue
            metadata = await stat(source.path)
            storage, node = file_refs.stored_target(metadata, source.path)
            if human and storage not in checked_storage:
                await s.auth.require(recipient, "storage", storage, "read")
                checked_storage.add(storage)
            folder = metadata.type == FileType.DIRECTORY
            if folder and (source.page is not None or source.line is not None):
                raise ValueError("A folder source cannot have a page or line")
            citation: dict[str, JSON] = {
                "kind": "folder" if folder else "file",
                "storage_id": str(storage),
                "node_id": str(node),
                "label": metadata.name,
            }
            if source.page is not None:
                citation["page"] = source.page
            if source.line is not None:
                citation["line"] = source.line
            sources.append(citation)
        if has_attachments:
            content, attachment_content = await file_refs.resolve(
                content, message.attachments, stat
            )
        refs: list[JSON] = await file_refs.validate(
            s,
            cast(UUID, agent["workspace_id"]),
            Actor("agent", ctx.leta_id),
            recipient,
            content + "\n" + attachment_content,
            copy_request=id if human else None,
            copy_folders=copy_folders,
        )
    except HTTPException as error:
        raise PermissionError(str(error.detail)) from error
    except grpc.aio.AioRpcError as error:
        if error.code() not in (
            grpc.StatusCode.NOT_FOUND,
            grpc.StatusCode.PERMISSION_DENIED,
            grpc.StatusCode.INVALID_ARGUMENT,
            grpc.StatusCode.ALREADY_EXISTS,
            grpc.StatusCode.FAILED_PRECONDITION,
            grpc.StatusCode.RESOURCE_EXHAUSTED,
            grpc.StatusCode.ABORTED,
        ):
            raise
        raise ValueError(
            error.details() or "Could not resolve files or folders"
        ) from error
    replacements = {
        f"{storage}/{node}": ref
        for (_, storage, node), ref in zip(
            file_refs.references(content + "\n" + attachment_content), refs, strict=True
        )
        if isinstance(ref, dict)
    }
    content = file_refs.PATTERN.sub(
        lambda match: file_refs.token(
            re.sub(r"\\(.)", r"\1", match[1]),
            str(replacements[match[2]]["storage_id"]),
            str(replacements[match[2]]["node_id"]),
            folder=replacements[match[2]].get("kind") == "folder",
        ),
        content,
    )
    refs = [
        replacements[f"{storage}/{node}"]
        for _, storage, node in file_refs.references(attachment_content)
    ]
    return inbox_messages.Outgoing(id, content, refs, sources)


@tool(response_format="content_and_artifact")
async def inbox_send(
    runtime: ToolRuntime[Context, State],
    messages: Annotated[list[InboxMessage], Field(min_length=1, max_length=5)],
    to: str | None = None,
    in_reply_to: Annotated[int | None, Field(ge=1)] = None,
    task_label: Annotated[str | None, Field(max_length=255)] = None,
    copy_folders: bool = False,
) -> tuple[JSON, dict[str, JSON]]:
    """Send messages to user:<handle> or agent:<handle>. Cite sources with [1], [2], ... mapped to that message's sources in order. Attach file or folder paths or use :file[label]{path=path} for inline links. in_reply_to quotes a received message in the first message. Use task_label for assignments. Set copy_folders only when authorized to share an inaccessible folder's entire contents."""
    from ..worker import deliver

    ctx = runtime.context
    s, agent = ctx.services, ctx.agent
    original = (
        await inbox_messages.incoming(s.db, ctx.id, in_reply_to)
        if in_reply_to is not None
        else None
    )
    if original and (
        original["source_kind"] not in ("user", "agent")
        or original["input_type"] != "message"
    ):
        raise ValueError("System events are not reply destinations")
    if to is not None:
        kind, target = await inbox_address(ctx, to)
    elif original:
        kind, target = str(original["source_kind"]), cast(UUID, original["source_id"])
    else:
        raise ValueError("Provide to or in_reply_to")
    if original and (
        kind != original["source_kind"] or target != original["source_id"]
    ):
        raise ValueError("to does not match the sender of in_reply_to")
    human = kind == "user"
    if human and ctx.id != ctx.leta_id:
        raise ValueError("Only Leta can message users")
    if not human:
        async with s.db.connection() as conn:
            recipient = await (
                await conn.execute(
                    "SELECT id,leta_id,box_id FROM agents WHERE id=%s",
                    (target,),
                )
            ).fetchone()
            if recipient is None or not await inbox_messages.can_contact(
                conn, agent, recipient
            ):
                raise ValueError("recipient is outside the communication graph")
    id = request_id(runtime)
    if human:
        await s.auth.require(
            Actor("user", target),
            "workspace",
            cast(UUID, agent["workspace_id"]),
            "participate",
        )
    # Messages from one transaction share a timestamp. Keep their UUID order stable across retries.
    first_id = id.int & ~0xFF if len(messages) > 1 else id.int
    outgoing = [
        await prepare_outgoing(
            runtime,
            message,
            UUID(int=first_id + index),
            target,
            human=human,
            copy_folders=copy_folders,
        )
        for index, message in enumerate(messages)
    ]
    reply = cast(UUID, original["id"]) if original else None
    if human:
        await conversations.storage(s, ctx.leta_id, target)
        await inbox_messages.deliver_user(
            s.db,
            ctx.leta_id,
            target,
            cast(UUID, original["conversation_id"])
            if original
            else inbox_messages.conversation(ctx.leta_id, "user", target),
            reply,
            outgoing,
        )
        ctx.filesystem.discovered = 0
        from .. import events

        await events.changed(s.redis, ctx.leta_id, "messages", outgoing[0].id, target)
    else:
        conversation = (
            cast(UUID, original["conversation_id"])
            if original
            else inbox_messages.agent_conversation(ctx.id, target)
        )
        await deliver(
            s,
            [
                Message(
                    id=message.id,
                    recipient_agent_id=target,
                    source_kind="agent",
                    source_id=ctx.id,
                    conversation_id=conversation,
                    content=message.content,
                    file_refs=message.file_refs,
                    sources=message.sources,
                    task_label=task_label if index == 0 else None,
                    in_reply_to_message_id=reply if index == 0 else None,
                )
                for index, message in enumerate(outgoing)
            ],
        )
    return presented(
        "inbox_send",
        {"sent": len(outgoing)},
        {
            "messages": [
                {
                    "content": message.content,
                    "file_refs": message.file_refs,
                    "sources": message.sources,
                }
                for message in outgoing
            ],
            "recipient": {"kind": kind, "id": str(target)},
        },
    )


@tool(response_format="content_and_artifact")
async def inbox_react(
    runtime: ToolRuntime[Context, State],
    source: str,
    message: Annotated[int, Field(ge=1)],
    emoji: str,
    action: Literal["add", "remove"] = "add",
) -> tuple[JSON, dict[str, JSON]]:
    """React to a received user or teammate message using its sender address and inbox message number. One emoji per agent per message; add replaces your previous emoji, remove clears it. Feedback is silent and does not wake another agent."""
    ctx = runtime.context
    kind, sender = await inbox_address(ctx, source)
    original = await inbox_messages.incoming(ctx.services.db, ctx.id, message)
    if original["source_kind"] != kind or original["source_id"] != sender:
        raise LookupError("Message number does not belong to that conversation")
    result = await reactions.react(
        ctx.services.db,
        ctx.services.auth,
        ctx.leta_id,
        cast(UUID, original["id"]),
        "incoming",
        Actor("agent", ctx.id),
        reactions.React(
            request_id=request_id(runtime), emoji=emoji if action == "add" else None
        ),
    )
    from .. import events

    await events.changed(
        ctx.services.redis,
        ctx.leta_id,
        "reactions",
        cast(UUID, original["id"]),
        UUID(str(result["user_id"])) if result["user_id"] else None,
    )
    return presented("reaction", {"sent": True}, result)


@tool(response_format="content_and_artifact")
async def inbox_list(
    runtime: ToolRuntime[Context, State],
    cursor: str = "",
    unread_only: bool = True,
) -> tuple[JSON, dict[str, JSON]]:
    """List inbox notifications grouped by conversation, including silent feedback that does not wake you."""
    ctx = runtime.context
    rows = await inbox_messages.list_inbox(
        ctx.services.db, ctx.id, int(cursor or 0), unread_only
    )
    await inbox_messages.name_users(ctx.services.internal, rows)
    result = (
        inbox_messages.input_batch(rows, root=True)
        or "No messages matching this inbox filter."
    )
    if len(rows) == 20:
        result += f"\nNext cursor: {rows[-1]['seq']}"
    return result, {"ui": inbox_messages.input_data(rows, root=True)}


@tool(response_format="content_and_artifact")
async def inbox_read(
    runtime: ToolRuntime[Context, State],
    source: str,
    cursor: str = "",
    unread_only: bool = True,
) -> tuple[str, dict[str, JSON]]:
    """Read up to 20 messages from the conversation with user:<handle> or agent:<handle>. By default, read only unread messages. Use the returned cursor for the next page."""
    ctx = runtime.context
    kind, sender = await inbox_address(ctx, source)
    rows = await inbox_messages.read(
        ctx.services.db, ctx.id, sender, kind, int(cursor or 0), unread_only
    )
    await inbox_messages.name_users(ctx.services.internal, rows)
    if rows:
        async with ctx.services.db.connection() as conn:
            await conn.execute(
                "UPDATE agent_messages SET processing_run_id=coalesce(processing_run_id,%s) WHERE id=ANY(%s)",
                (ctx.run_id, [row["id"] for row in rows]),
            )
        if kind == "user":
            from .. import events

            await events.changed(
                ctx.services.redis, ctx.leta_id, "messages", ctx.id, sender
            )
    text = (
        inbox_messages.input_batch(rows, root=False)
        or "No messages matching this conversation and filter."
    )
    if len(rows) == 20:
        text += f"\nNext cursor: {rows[-1]['seq']}"
    return text, {"ui": inbox_messages.input_data(rows, root=False)}


@tool(response_format="content_and_artifact")
async def get_context(
    runtime: ToolRuntime[Context, State],
) -> tuple[JSON, dict[str, JSON]]:
    """Get the current workspace snapshot, including members, chats and their paths, accessible storage, and brief summaries of open HITL requests, schedules, and active Boxes. Call once at the start of a fresh Leta thread and once after context compaction. Reuse the snapshot for subsequent work."""
    ctx = runtime.context
    s = ctx.services
    workspace_id = cast(UUID, ctx.agent["workspace_id"])
    workspace = await s.internal.GetWorkspaceInfo(
        platform_api.WorkspaceRequest(workspace_id=str(workspace_id)), timeout=15
    )
    members: list[dict[str, JSON]] = []
    cursor = ""
    while True:
        page = await s.auth.members(s.internal, workspace_id, cursor)
        members.extend(cast(list[dict[str, JSON]], page["items"]))
        if not page["next_cursor"]:
            break
        cursor = str(page["next_cursor"])
    await ctx.filesystem.discover()
    async with s.db.connection() as conn:
        owners = (
            [ctx.id]
            if ctx.id != ctx.leta_id
            else [
                row["id"]
                for row in await (
                    await conn.execute(
                        "SELECT id FROM agents WHERE leta_id=%s", (ctx.leta_id,)
                    )
                ).fetchall()
            ]
        )
        requests = await (
            await conn.execute(
                "SELECT id,title,type FROM hitl_requests WHERE requester_agent_id=ANY(%s) AND status='pending' ORDER BY created_at LIMIT 20",
                (owners,),
            )
        ).fetchall()
        alarms = await (
            await conn.execute(
                "SELECT id,title,type,paused FROM schedules WHERE creator_agent_id=ANY(%s) AND deleted_at IS NULL ORDER BY created_at LIMIT 20",
                (owners,),
            )
        ).fetchall()
        teams = await (
            await conn.execute(
                "SELECT name,handle FROM boxes WHERE leta_id=%s AND state='active' ORDER BY created_at LIMIT 20",
                (ctx.leta_id,),
            )
        ).fetchall()
    bindings = ctx.filesystem.bindings
    people: list[JSON] = []
    for member in members:
        handle = member["handle"]
        person = {key: member[key] for key in ("name", "handle", "role")}
        if f"/chat/{handle}" in bindings:
            person["chat_path"] = f"/chat/{handle}"
        if (personal := bindings.get(f"/user/{handle}")) is not None:
            person["personal_path"] = f"/user/{handle}"
            person["personal_access"] = (
                "read-write" if personal.writable else "read-only"
            )
        people.append(person)
    result: dict[str, JSON] = {
        "workspace": {
            "name": workspace.name,
            "shared_path": "/shared" if "/shared" in bindings else None,
        },
        "members": people,
        "open_hitl": [json_row(row) for row in requests],
        "schedules": [json_row(row) for row in alarms],
        "boxes": [json_row(row) for row in teams],
    }
    return presented("get_context", result, result)


@tool(response_format="content_and_artifact")
async def agent_status(
    runtime: ToolRuntime[Context, State],
    target: str,
    activity_limit: Annotated[int, Field(ge=0, le=5)] = 2,
) -> tuple[JSON, dict[str, JSON]]:
    """Inspect one agent:<handle> for runtime state, latest run inputs, and recorded work. An input shows what reached the run. Ask the Leader to confirm commitments."""
    ctx = runtime.context
    if not target.startswith("agent:"):
        raise ValueError("Use an agent:<handle> address")
    _, id = await inbox_address(ctx, target)
    async with ctx.services.db.connection() as conn:
        agent = await (
            await conn.execute(
                "SELECT id,leta_id,box_id FROM agents WHERE id=%s",
                (id,),
            )
        ).fetchone()
        if (
            agent is None
            or (ctx.id == ctx.leta_id and agent["box_id"] is None)
            or (
                ctx.id != ctx.leta_id
                and not await inbox_messages.can_contact(conn, ctx.agent, agent)
            )
        ):
            raise LookupError("agent is outside your status scope")
        result = await box_views.status(conn, id, activity_limit)
    return presented("agent_status", result, result)


@tool(response_format="content_and_artifact")
async def box_create(
    runtime: ToolRuntime[Context, State],
    name: str,
    letis: list[LetiDefinition],
    leader: str,
    description: str = "",
    workflow: str = "",
    additional_links: list[tuple[str, str]] | None = None,
) -> tuple[JSON, dict[str, JSON]]:
    """Create a Box. Its Leader can contact every member. Declare optional additional links between non-Leader members by name. Address the returned Leader handle to start work."""
    from ..worker import operation

    ctx = runtime.context
    id = request_id(runtime)
    result = await operation(
        ctx.services,
        ResourceOperation(
            id=id,
            request_id=id,
            action="create",
            box=BoxCreation(
                leta_id=ctx.leta_id,
                box_id=id,
                request_id=id,
                request=CreateBox(
                    name=name,
                    description=description,
                    letis=letis,
                    leader=leader,
                    workflow=workflow,
                    additional_links=additional_links or [],
                ),
            ),
            bridge_queue=ctx.services.config["dependencies"]["temporal"]["queues"][
                "leta_bridge"
            ],
        ),
        wait=True,
    )
    await ctx.filesystem.changed(str(result["home"]))
    content = {key: value for key, value in result.items() if key != "id"}
    return presented("box_create", content, content)


@tool(response_format="content_and_artifact")
async def box_list(
    runtime: ToolRuntime[Context, State], cursor: UUID | None = None
) -> tuple[JSON, dict[str, JSON]]:
    """List Boxes by name, handle, lifecycle state, and team size."""
    ctx = runtime.context
    result = await boxes.list_boxes(ctx.services.db, ctx.leta_id, cursor)
    lines = [
        f"{item['name']} ({item['handle']}) | {item['state']} | {item['agent_count']} members\n{item['description']}"
        for item in cast(list[dict[str, JSON]], result["boxes"])
    ]
    if result.get("next_cursor"):
        lines.append(f"Next cursor: {result['next_cursor']}")
    return presented("box_list", "\n\n".join(lines) or "No boxes.", result)


@tool(response_format="content_and_artifact")
async def box_get(
    runtime: ToolRuntime[Context, State], box: str, include_prompts: bool = False
) -> tuple[JSON, dict[str, JSON]]:
    """Get Box configuration and roster by Box handle. Include standing instructions on request."""
    ctx = runtime.context
    identity = await boxes.by_handle(ctx.services.db, ctx.leta_id, box)
    result = await boxes.get(
        ctx.services.db, ctx.leta_id, cast(UUID, identity["id"]), include_prompts
    )
    members = cast(list[dict[str, JSON]], result["letis"])
    by_id = {
        member["id"]: member for member in members if isinstance(member["id"], str)
    }
    leader = by_id[str(result["leader_agent_id"])]
    roster: list[JSON] = [
        {
            key: member[key]
            for key in ("name", "title", "handle", "description", "system_prompt")
            if key in member
        }
        for member in members
    ]
    content: dict[str, JSON] = {
        "name": result["name"],
        "handle": box,
        "description": result["description"],
        "home": f"~/.boxes/{box}/",
        "leader": {"name": leader["name"], "handle": leader["handle"]},
        "letis": roster,
        "workflow": result["workflow"],
        "additional_links": [
            [
                by_id[str(link[key])]["handle"]
                for key in ("agent_low_id", "agent_high_id")
            ]
            for link in cast(list[dict[str, JSON]], result["additional_links"])
        ],
    }
    return presented("box_get", content, content)


@tool(response_format="content_and_artifact")
async def box_delete(
    runtime: ToolRuntime[Context, State], box: str
) -> tuple[JSON, dict[str, JSON]]:
    """Stop a box, remove its schedules/pending requests and trash its work directory. Files elsewhere in shared home remain."""
    from ..worker import operation

    ctx = runtime.context
    identity = await boxes.by_handle(ctx.services.db, ctx.leta_id, box)
    await operation(
        ctx.services,
        ResourceOperation(
            id=cast(UUID, identity["id"]),
            request_id=request_id(runtime),
            action="delete_box",
            bridge_queue=ctx.services.config["dependencies"]["temporal"]["queues"][
                "leta_bridge"
            ],
        ),
        wait=True,
    )

    await ctx.filesystem.changed(f"~/.boxes/{box}")
    result: JSON = {"box": box, "state": "archived"}
    return presented("box_delete", result, result)


@tool(response_format="content_and_artifact")
async def hitl_ask(
    runtime: ToolRuntime[Context, State],
    user_handle: str,
    questions: Annotated[list[hitl.Question], Field(min_length=1, max_length=10)],
    title: str = "",
) -> tuple[JSON, dict[str, JSON]]:
    """Ask any current workspace member; the answer arrives later in your inbox."""
    ctx = runtime.context
    from ..worker import submit_hitl

    recipient_user_id = await user_id(ctx, user_handle)

    result = await submit_hitl(
        ctx.services,
        hitl.OpenRequest(
            id=request_id(runtime),
            requester_agent_id=ctx.id,
            recipient_user_id=recipient_user_id,
            type="ask",
            title=title or questions[0].text[:255],
            payload=hitl.form(questions),
        ),
    )
    result: JSON = {"request_id": result["id"], "status": result["status"]}
    return presented(
        "hitl_ask",
        result,
        {
            **cast(dict[str, JSON], result),
            "title": title or questions[0].text[:255],
            "recipient_user_id": str(recipient_user_id),
            "payload": hitl.form(questions),
        },
    )


@tool(response_format="content_and_artifact")
async def hitl_request(
    runtime: ToolRuntime[Context, State],
    user_handle: str,
    role: Literal["viewer", "editor"] = "viewer",
    reason: str = "",
) -> tuple[JSON, dict[str, JSON]]:
    """Ask a workspace member for access to their Personal storage, shared by Leta and its Leti. Wait for the grant outcome."""
    ctx = runtime.context
    from ..worker import submit_hitl

    recipient = await user_id(ctx, user_handle)

    result = await submit_hitl(
        ctx.services,
        hitl.OpenRequest(
            id=request_id(runtime),
            requester_agent_id=ctx.id,
            recipient_user_id=recipient,
            type="approval",
            title="Storage access request",
            payload={"role": role, "reason": reason},
        ),
    )
    if result["status"] == "already_granted":
        result: JSON = {"status": "already_granted", "access": role}
        return presented(
            "hitl_request",
            result,
            {
                **cast(dict[str, JSON], result),
                "title": "Storage access request",
                "recipient_user_id": str(recipient),
                "payload": {"role": role, "reason": reason},
            },
        )
    result: JSON = {"request_id": result["id"], "status": result["status"]}
    return presented(
        "hitl_request",
        result,
        {
            **cast(dict[str, JSON], result),
            "title": "Storage access request",
            "recipient_user_id": str(recipient),
            "payload": {"role": role, "reason": reason},
        },
    )


async def own_hitl(ctx: Context, id: UUID) -> dict[str, JSON]:
    return await hitl.get(
        ctx.services.db,
        id,
        root=ctx.leta_id,
        requester=ctx.id if ctx.agent["box_id"] is not None else None,
    )


@tool(response_format="content_and_artifact")
async def hitl_get(
    runtime: ToolRuntime[Context, State], request_id: UUID
) -> tuple[JSON, dict[str, JSON]]:
    """Get a human request, its form, decision and grant outcome."""
    result = await own_hitl(runtime.context, request_id)
    return presented("hitl_get", hitl.render(result), result)


@tool(response_format="content_and_artifact")
async def hitl_cancel(
    runtime: ToolRuntime[Context, State], request_id: UUID, reason: str = ""
) -> tuple[JSON, dict[str, JSON]]:
    """Cancel a pending human request; does not revoke granted access."""
    ctx = runtime.context
    await own_hitl(ctx, request_id)
    result = await ctx.services.temporal.get_workflow_handle(  # pyright: ignore[reportUnknownMemberType]  # Temporal has an untyped overload for args.
        f"hitl/{request_id}"
    ).execute_update(
        "decide",
        hitl.Decision(
            request_id=request_id,
            actor=Actor("agent", ctx.id),
            status="cancelled",
            response={"reason": reason},
            resolved_at=datetime.now(timezone.utc),
        ),
        result_type=dict[str, JSON],
    )
    public: JSON = {"request_id": str(request_id), "status": result["status"]}
    return presented("hitl_cancel", public, public)


async def list_hitl(
    ctx: Context, status: Status | None, cursor: UUID | None, box_id: UUID | None = None
) -> tuple[JSON, dict[str, JSON]]:
    async with ctx.services.db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT h.id,h.recipient_user_id,h.title,h.status,h.outcome
            FROM hitl_requests h JOIN agents a ON a.id=h.requester_agent_id
            WHERE a.leta_id=%s AND (%s::uuid IS NULL OR a.id=%s) AND (%s::text IS NULL OR h.status=%s)
            AND (%s::uuid IS NULL OR a.box_id=%s) AND (%s::uuid IS NULL OR h.id>%s) ORDER BY h.id LIMIT 20""",
                (
                    ctx.leta_id,
                    ctx.id if ctx.agent["box_id"] else None,
                    ctx.id,
                    status,
                    status,
                    box_id,
                    box_id,
                    cursor,
                    cursor,
                ),
            )
        ).fetchall()
    lines: list[str] = []
    titles = [row["title"] for row in rows]
    for row in rows:
        line = f"{row['id']} | {row['title']} | {row['status']}"
        if titles.count(row["title"]) > 1:
            line += f" | to: {row['recipient_user_id']}"
        if row["outcome"]:
            outcome = cast(dict[str, JSON], row["outcome"])
            line += f" | access: {outcome['status']}"
            if outcome.get("reason"):
                line += f" ({outcome['reason']})"
        lines.append(line)
    if len(rows) == 20:
        lines.append(f"Next cursor: {rows[-1]['id']}")
    content = "\n".join(lines) or (
        "No pending requests."
        if status == "pending"
        else "No requests matching this filter."
    )
    return presented("hitl_list", content, {"items": [json_row(row) for row in rows]})


@tool("hitl_list", response_format="content_and_artifact")
async def leta_hitl_list(
    runtime: ToolRuntime[Context, State],
    status: Status | None = None,
    cursor: UUID | None = None,
    box: str | None = None,
) -> tuple[JSON, dict[str, JSON]]:
    """List human requests across Leta and its Boxes. Filter by Box handle if needed."""
    result = await list_hitl(
        runtime.context,
        status,
        cursor,
        cast(
            UUID,
            (
                await boxes.by_handle(
                    runtime.context.services.db, runtime.context.leta_id, box
                )
            )["id"],
        )
        if box
        else None,
    )
    return result


@tool("hitl_list", response_format="content_and_artifact")
async def leti_hitl_list(
    runtime: ToolRuntime[Context, State],
    status: Status | None = None,
    cursor: UUID | None = None,
) -> tuple[JSON, dict[str, JSON]]:
    """List your human requests; use hitl_get for details."""
    result = await list_hitl(runtime.context, status, cursor)
    return result


async def change_schedule(
    runtime: ToolRuntime[Context, State], change: schedules.Change, target: str
) -> JSON:
    from ..worker import submit_schedule

    result = await submit_schedule(runtime.context.services, change)
    if change.action == "delete":
        return {"schedule_id": str(change.schedule_id), "deleted": True}
    return {
        "schedule_id": result["id"],
        "target": target,
        "type": result["type"],
        "spec": result["spec"],
        "paused": result["paused"],
    }


async def own_schedule(ctx: Context, id: UUID) -> dict[str, JSON]:
    return await schedules.get(
        ctx.services.db,
        id,
        root=ctx.leta_id,
        creator=ctx.id if ctx.agent["box_id"] is not None else None,
    )


@tool("schedule_create", response_format="content_and_artifact")
async def leta_schedule_create(
    runtime: ToolRuntime[Context, State],
    content: str,
    title: str = "",
    at: datetime | None = None,
    after_seconds: int | None = None,
    every_seconds: int | None = None,
    calendar: schedules.CalendarValues | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    timezone: str = "UTC",
    target_box: str | None = None,
) -> tuple[JSON, dict[str, JSON]]:
    """Schedule an inbox instruction for yourself or a box. Choose exactly one: at, after_seconds, every_seconds, calendar."""
    ctx = runtime.context
    id = request_id(runtime)
    target = ctx.id
    if target_box:
        box = await boxes.by_handle(ctx.services.db, ctx.leta_id, target_box)
        target = UUID(str(box["leader_agent_id"]))
    result = await change_schedule(
        runtime,
        schedules.Change(
            request_id=id,
            schedule_id=id,
            creator_agent_id=ctx.id,
            target_agent_id=target,
            action="create",
            content=content,
            title=title,
            at=at,
            after_seconds=after_seconds,
            every_seconds=every_seconds,
            calendar=calendar,
            starts_at=starts_at,
            ends_at=ends_at,
            timezone=timezone,
        ),
        target_box or "Leta",
    )
    return presented(
        "schedule_create",
        result,
        {**cast(dict[str, JSON], result), "title": title, "content": content},
    )


@tool("schedule_create", response_format="content_and_artifact")
async def leti_schedule_create(
    runtime: ToolRuntime[Context, State],
    content: str,
    title: str = "",
    at: datetime | None = None,
    after_seconds: int | None = None,
    every_seconds: int | None = None,
    calendar: schedules.CalendarValues | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    timezone: str = "UTC",
) -> tuple[JSON, dict[str, JSON]]:
    """Schedule an inbox instruction for yourself. Choose exactly one: at, after_seconds, every_seconds, calendar."""
    ctx = runtime.context
    id = request_id(runtime)
    result = await change_schedule(
        runtime,
        schedules.Change(
            request_id=id,
            schedule_id=id,
            creator_agent_id=ctx.id,
            target_agent_id=ctx.id,
            action="create",
            content=content,
            title=title,
            at=at,
            after_seconds=after_seconds,
            every_seconds=every_seconds,
            calendar=calendar,
            starts_at=starts_at,
            ends_at=ends_at,
            timezone=timezone,
        ),
        str(ctx.agent["box_handle"])
        + ("" if ctx.id == ctx.agent["leader_agent_id"] else f"/{ctx.agent['name']}"),
    )
    return presented(
        "schedule_create",
        result,
        {**cast(dict[str, JSON], result), "title": title, "content": content},
    )


@tool(response_format="content_and_artifact")
async def schedule_update(
    runtime: ToolRuntime[Context, State],
    schedule_id: UUID,
    title: str | None = None,
    content: str | None = None,
    paused: bool | None = None,
    at: datetime | None = None,
    after_seconds: int | None = None,
    every_seconds: int | None = None,
    calendar: schedules.CalendarValues | None = None,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    timezone: str = "UTC",
) -> tuple[JSON, dict[str, JSON]]:
    """Update only supplied fields. At most one timing selector; recipient stays fixed. ends_at=null clears the cutoff."""
    ctx = runtime.context
    old = await own_schedule(ctx, schedule_id)
    message = runtime.state["messages"][-1]
    assert isinstance(message, AIMessage)
    call = next(
        call for call in message.tool_calls if call["id"] == runtime.tool_call_id
    )
    result = await change_schedule(
        runtime,
        schedules.Change(
            request_id=request_id(runtime),
            schedule_id=schedule_id,
            creator_agent_id=UUID(str(old["creator_agent_id"])),
            target_agent_id=UUID(str(old["target_agent_id"])),
            action="update",
            title=title,
            content=content,
            paused=paused,
            at=at,
            after_seconds=after_seconds,
            every_seconds=every_seconds,
            calendar=calendar,
            starts_at=starts_at,
            ends_at=ends_at,
            timezone=timezone,
            supplied=set(call["args"]),
        ),
        str(old["target"]),
    )
    return presented(
        "schedule_update",
        result,
        {
            **cast(dict[str, JSON], result),
            "title": title if title is not None else old["title"],
            "content": content if content is not None else old["content"],
            "previous_spec": old["spec"],
        },
    )


@tool(response_format="content_and_artifact")
async def schedule_delete(
    runtime: ToolRuntime[Context, State], schedule_id: UUID
) -> tuple[JSON, dict[str, JSON]]:
    """Stop future scheduled instructions; already-delivered work remains."""
    old = await own_schedule(runtime.context, schedule_id)
    result = await change_schedule(
        runtime,
        schedules.Change(
            request_id=request_id(runtime),
            schedule_id=schedule_id,
            creator_agent_id=UUID(str(old["creator_agent_id"])),
            target_agent_id=UUID(str(old["target_agent_id"])),
            action="delete",
        ),
        str(old["target"]),
    )
    return presented(
        "schedule_delete",
        result,
        {**cast(dict[str, JSON], result), "title": old["title"]},
    )


@tool(response_format="content_and_artifact")
async def schedule_get(
    runtime: ToolRuntime[Context, State], schedule_id: UUID
) -> tuple[JSON, dict[str, JSON]]:
    """Get a schedule instruction, timing and upcoming forecasts."""
    value = await own_schedule(runtime.context, schedule_id)
    result: JSON = {
        **{
            key: value[key]
            for key in (
                "id",
                "title",
                "content",
                "type",
                "spec",
                "paused",
                "deleted_at",
            )
            if value.get(key) is not None
        },
        "target": value["target"],
        **await schedules.upcoming(runtime.context.services.temporal, value),
    }
    return presented("schedule_get", result, result)


async def list_schedules(
    ctx: Context, cursor: UUID | None, box_id: UUID | None = None
) -> tuple[JSON, dict[str, JSON]]:
    async with ctx.services.db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT sc.id,sc.title,sc.type,sc.spec,sc.paused,sc.deleted_at,CASE WHEN target.id=b.leader_agent_id THEN b.name ELSE target.name END AS target_name FROM schedules sc JOIN agents a ON a.id=sc.creator_agent_id
            JOIN agents target ON target.id=sc.target_agent_id LEFT JOIN boxes b ON b.id=target.box_id WHERE a.leta_id=%s AND (%s::uuid IS NULL OR a.id=%s)
            AND (%s::uuid IS NULL OR target.box_id=%s) AND (%s::uuid IS NULL OR sc.id>%s) ORDER BY sc.id LIMIT 20""",
                (
                    ctx.leta_id,
                    ctx.id if ctx.agent["box_id"] else None,
                    ctx.id,
                    box_id,
                    box_id,
                    cursor,
                    cursor,
                ),
            )
        ).fetchall()
    lines = [
        f"{row['id']} | {row['title']} | {row['target_name']} | "
        f"{'deleted' if row['deleted_at'] else 'paused' if row['paused'] else 'active'} | {row['type']}: "
        + json.dumps(row["spec"], ensure_ascii=False, separators=(",", ":"))
        for row in rows
    ]
    if len(rows) == 20:
        lines.append(f"Next cursor: {rows[-1]['id']}")
    return presented(
        "schedule_list",
        "\n".join(lines) or "No schedules matching this filter.",
        {"items": [json_row(row) for row in rows]},
    )


@tool("schedule_list", response_format="content_and_artifact")
async def leta_schedule_list(
    runtime: ToolRuntime[Context, State],
    cursor: UUID | None = None,
    box: str | None = None,
) -> tuple[JSON, dict[str, JSON]]:
    """List Leta and Box schedules. Filter by Box handle if needed."""
    return await list_schedules(
        runtime.context,
        cursor,
        cast(
            UUID,
            (
                await boxes.by_handle(
                    runtime.context.services.db, runtime.context.leta_id, box
                )
            )["id"],
        )
        if box
        else None,
    )


@tool("schedule_list", response_format="content_and_artifact")
async def leti_schedule_list(
    runtime: ToolRuntime[Context, State], cursor: UUID | None = None
) -> tuple[JSON, dict[str, JSON]]:
    """List your schedules."""
    return await list_schedules(runtime.context, cursor)


@tool(response_format="content_and_artifact")
async def history_search(
    runtime: ToolRuntime[Context, State], query: str = "", cursor: str = ""
) -> tuple[JSON, dict[str, JSON]]:
    """Search activity using a few distinctive literal keywords; all terms must match. History lookup calls/results are excluded. Omit query for recent previews."""
    ctx = runtime.context
    text, data = await history.search_tool(
        ctx.services.db, ctx.id, int(cursor) if cursor else None, query
    )
    return presented("history_search", text, data)


@tool(response_format="content_and_artifact")
async def history_read(
    runtime: ToolRuntime[Context, State],
    entry: Annotated[int, Field(ge=1)],
    start_line: Annotated[int, Field(ge=1)] = 1,
    limit: Annotated[int | None, Field(ge=1, le=2000)] = None,
) -> tuple[JSON, dict[str, JSON]]:
    """Read an activity entry by its number from history_search; follow continuations when needed."""
    ctx = runtime.context
    text = await history.read_text(ctx.services.db, ctx.id, entry, start_line, limit)

    return presented(
        "history_read",
        text,
        {"content": text, "entry": entry, "start_line": start_line},
    )


@tool(response_format="content_and_artifact")
async def file_list(
    runtime: ToolRuntime[Context, State],
    path: str = "~",
    cursor: str = "",
    depth: Annotated[int, Field(ge=1, le=10)] = 1,
) -> tuple[JSON, dict[str, JSON]]:
    """List files and directories with optional pagination and depth."""
    vfs = (await session(runtime)).vfs
    result, _ = await vfs.dispatch("list_page", scope(path), cursor=cursor, depth=depth)
    return presented(
        "file_list",
        directory_text(path, cast(dict[str, JSON], result)),
        cast(JSON, result),
    )


def directory_text(base: str, result: dict[str, JSON]) -> str:
    lines = [f"Directory: {base}"]
    for item in cast(list[dict[str, JSON]], result["items"]):
        child = posixpath.relpath(str(item["path"]), file_path(base))
        image = str(item.get("media_type") or "").startswith("image/")
        if child == ".":
            if image:
                lines[0] = f"Image: {base} [read with file_read]"
            continue
        suffix = (
            " [image; read with file_read]"
            if image
            else "/ [document artifacts]"
            if item.get("artifacts")
            else "/"
            if item["kind"] == "directory"
            else ""
        )
        lines.append(child + suffix)
    if not result["items"]:
        lines.append("(empty)")
    if result.get("next_cursor"):
        lines.append(f"Next cursor: {result['next_cursor']}")
    elif result.get("truncated"):
        lines.append(
            "Listing incomplete. Narrow the path or depth to inspect the remaining entries."
        )
    return "\n".join(lines)


@tool(response_format="content_and_artifact")
async def file_read(
    runtime: ToolRuntime[Context, State],
    path: str,
    start_line: Annotated[int, Field(ge=1)] = 1,
    limit: Annotated[int | None, Field(ge=1, le=2000)] = None,
) -> tuple[JSON, dict[str, JSON]]:
    """Read file text, an image, or an uploaded document's extracted files. For text, start_line and limit select lines; omitted limit reads up to the output cap. Follow the continuation when more content is needed."""
    vfs = (await session(runtime)).vfs
    metadata = await vfs.stat(file_path(path))
    media = str(metadata.extra.get("media_type", ""))
    if media and not (
        media.startswith("text/") or metadata.content == ContentType.TEXT
    ):
        result, _ = await vfs.dispatch(
            "preview", scope(path), image=media.startswith("image/")
        )
        if media.startswith("image/"):
            return presented(
                "file_read",
                cast(JSON, result),
                {
                    "path": path,
                    "content": f"Image: {path}",
                    **file_reference(metadata),
                },
            )
        return presented(
            "file_list",
            directory_text(path, cast(dict[str, JSON], result)),
            cast(JSON, result),
        )
    data = await vfs.read(file_path(path))
    page = text_page(data.decode(), start_line, limit)
    return presented(
        "file_read",
        page,
        {
            "path": path,
            "content": page,
            "start_line": start_line,
            **file_reference(metadata),
        },
    )


@tool(response_format="content_and_artifact")
async def file_write(
    runtime: ToolRuntime[Context, State],
    path: str,
    content: str,
    overwrite: bool = False,
) -> tuple[JSON, dict[str, JSON]]:
    """Create text; overwrite=true replaces the entire file. Use file_edit for partial changes."""
    token = current_operation.set(request_id(runtime))
    try:
        metadata, _ = await (await session(runtime)).vfs.dispatch(
            "write_text", scope(path), content=content, overwrite=overwrite
        )
    finally:
        current_operation.reset(token)
    result: JSON = {"path": path}
    return presented("file_write", result, {**result, **file_reference(metadata)})


@tool(response_format="content_and_artifact")
async def file_edit(
    runtime: ToolRuntime[Context, State],
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
) -> tuple[JSON, dict[str, JSON]]:
    """Replace literal text; exactly one match unless replace_all=true. Empty new_text deletes the match."""
    token = current_operation.set(request_id(runtime))
    try:
        metadata, _ = await (await session(runtime)).vfs.dispatch(
            "edit_text",
            scope(path),
            old_text=old_text,
            new_text=new_text,
            replace_all=replace_all,
        )
    finally:
        current_operation.reset(token)
    result: JSON = {"path": path}
    return presented("file_edit", result, {**result, **file_reference(metadata)})


@tool(response_format="content_and_artifact")
async def file_semantic_search(
    runtime: ToolRuntime[Context, State],
    query: str,
    paths: Annotated[list[str] | None, Field(max_length=5)] = None,
) -> tuple[JSON, dict[str, JSON]]:
    """Find passages by meaning; use shell search for exact text."""
    vfs = (await session(runtime)).vfs

    async def search(item: str) -> JSON:
        result, _ = await vfs.dispatch("semantic_search", scope(item), query=query)
        return cast(JSON, result)

    ctx = runtime.context
    with propagate_attributes(
        session_id=str(ctx.id),
        metadata={
            "workspace_id": str(ctx.agent["workspace_id"]),
            "agent_id": str(ctx.id),
            "leta_id": str(ctx.leta_id),
            "run_id": str(ctx.run_id),
            **({"box_id": str(ctx.agent["box_id"])} if ctx.agent["box_id"] else {}),
        },
        as_baggage=True,
    ):
        results = await asyncio.gather(*(search(item) for item in paths or ["~"]))
    groups: list[str] = []
    # Reserve all source paths and omission notices before allocating excerpts.
    used = 0
    for value in results:
        result = cast(dict[str, JSON], value)
        base = str(result["path"])
        used += len(f"Search scope: {base}\n\n".encode())
        for hit in cast(list[dict[str, JSON]], result["hits"]):
            used += len(
                (
                    posixpath.relpath(str(hit["path"]), base)
                    + " [excerpt omitted; read source]\n\n"
                ).encode()
            )
    for value in results:
        result = cast(dict[str, JSON], value)
        base = str(result["path"])
        lines = [f"Search scope: {base}"]
        for hit in cast(list[dict[str, JSON]], result["hits"]):
            name = posixpath.relpath(str(hit["path"]), base)
            excerpt = str(hit["text"])
            if len(excerpt) > 1024:
                excerpt = excerpt[:1024] + " [excerpt truncated]"
            size = len(excerpt.encode())
            if used + size <= BYTE_BUDGET:
                lines.append(name + "\n" + excerpt)
                used += size
            else:
                lines.append(name + " [excerpt omitted; read source]")
        groups.append(
            "\n\n".join(lines) if result["hits"] else f"No matches in {base}."
        )
    return presented("file_semantic_search", "\n\n".join(groups), {"groups": results})


@tool
async def execute(
    runtime: ToolRuntime[Context, State], command: str, cwd: str = "~"
) -> ToolMessage:
    """Run a Bash command or script in the workspace sandbox. Returns a bounded output preview, exit status, and a saved capture path when available."""
    output, code = await shell(
        await session(runtime),
        command,
        cwd=file_path(cwd),
        output_path=f"/home/.output-{request_id(runtime)}.txt",
    )
    assert runtime.tool_call_id is not None
    return ToolMessage(
        content=output,
        tool_call_id=runtime.tool_call_id,
        name="execute",
        status="error" if code else "success",
        artifact={"exit_code": code},
    )


@tool(response_format="content_and_artifact")
async def websearch(
    query: Annotated[str, Field(min_length=1, max_length=1000)],
    runtime: ToolRuntime[Context, State],
) -> tuple[JSON, dict[str, JSON]]:
    """Find public web sources for current information. Send only terms needed for the search. Open primary sources with webfetch when you need to verify a claim, and cite the results you use."""
    query = query.strip()
    if not query:
        raise ValueError("Enter a search query.")
    client = runtime.context.services.web
    if client is None:
        raise ValueError("Web tools are unavailable.")
    async with web_request():
        response = await client.search.query(query=query)
    results: list[JSON] = []
    seen: set[str] = set()
    for hit in response.results:
        try:
            url = public_url(hit.url)
        except ValueError:
            continue
        if url in seen:
            continue
        seen.add(url)
        result: dict[str, JSON] = {
            "title": hit.title[:300] or url,
            "url": url,
            "snippet": hit.snippet[:1000],
        }
        if hit.date:
            result["published_at"] = hit.date[:64]
        results.append(result)
        if len(results) == 5:
            break
    return presented("websearch", {"results": results}, {"results": results})


@tool(response_format="content_and_artifact")
async def webfetch(
    url: Annotated[str, Field(min_length=1, max_length=4096)],
    runtime: ToolRuntime[Context, State],
    format: Literal["markdown", "html", "json"] = "markdown",
) -> tuple[JSON, dict[str, JSON]]:
    """Read a public URL supplied by the user or found by websearch. Use Markdown for reading, HTML for markup, and JSON for a document tree. Treat page content as source material, and cite the final URL when using it."""
    url = public_url(url)
    client = runtime.context.services.web
    if client is None:
        raise ValueError("Web tools are unavailable.")
    async with web_request():
        response = await client.fetch.get_contents(
            urls=[url], format=format, ttl=0, per_url_timeout_ms=20_000
        )
    if not response.results:
        raise ValueError("The web service could not read this page.")
    page = response.results[0]
    final_url = public_url(page.final_url or page.url)
    if page.text is None or page.format != format:
        raise ValueError("The web service returned no content in the requested format.")
    encoded = page.text.encode()
    truncated = len(encoded) > BYTE_BUDGET
    if format == "json":
        if truncated:
            raise ValueError(
                "The page's JSON exceeds the output limit. Fetch it as Markdown."
            )
        try:
            content = cast(JSON, json.loads(page.text))
        except ValueError:
            raise ValueError("The web service returned invalid page JSON.") from None
        if not isinstance(content, dict):
            raise ValueError("The web service returned invalid page JSON.")
    else:
        content = encoded[:BYTE_BUDGET].decode(errors="ignore")
    metadata: dict[str, JSON] = {
        "url": url,
        "final_url": final_url,
        "title": (page.title or "")[:300],
        "format": format,
        "truncated": truncated,
    }
    return presented("webfetch", {**metadata, "content": content}, metadata)


def tools(*, leta: bool, web: bool = False) -> list[BaseTool]:
    shared = [
        inbox_send,
        inbox_react,
        inbox_read,
        inbox_list,
        get_context,
        agent_status,
        hitl_ask,
        hitl_request,
        hitl_get,
        hitl_cancel,
        schedule_get,
        schedule_update,
        schedule_delete,
        history_search,
        history_read,
        file_list,
        file_read,
        file_write,
        file_edit,
        execute,
        file_semantic_search,
    ]
    if web:
        shared.extend((websearch, webfetch))
    if leta:
        catalog = [
            *shared,
            leta_hitl_list,
            leta_schedule_create,
            leta_schedule_list,
            box_create,
            box_list,
            box_get,
            box_delete,
        ]
    else:
        catalog = [*shared, leti_hitl_list, leti_schedule_create, leti_schedule_list]
    for item in catalog:
        item.handle_validation_error = str
    return catalog
