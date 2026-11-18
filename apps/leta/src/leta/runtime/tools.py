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
from mirage import ContentType, FileStat, Session
from openlet_sdk.config import JSON
from pydantic import Field

from .. import boxes, file_refs, history, hitl, messages, reactions, schedules
from ..agents import json_row, stable
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
    def root(self) -> UUID:
        return cast(UUID, self.agent["leta_id"])


def request_id(runtime: ToolRuntime[Context, State]) -> UUID:
    assert runtime.tool_call_id is not None
    return stable(runtime.context.id, runtime.tool_call_id)


async def session(runtime: ToolRuntime[Context, State]) -> Session:
    return await runtime.context.filesystem.open()


@tool(response_format="content_and_artifact")
async def inbox_send(
    runtime: ToolRuntime[Context, State],
    content: Annotated[str, Field(max_length=32000)] = "",
    to: str | None = None,
    in_reply_to: Annotated[int | None, Field(ge=1)] = None,
    attachments: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=4096)]] | None,
        Field(max_length=20),
    ] = None,
) -> tuple[JSON, dict[str, JSON]]:
    """Send to a box name, permitted teammate name, root, or human user_id; use the inbox's to address for ordinary messages. Optional in_reply_to quotes a specific incoming message: use it only when that reference matters, such as an older request or parallel tasks; then to may be omitted. attachments accepts file paths; mention a file inline with :file[label]{path=path}. Mentions are inline links; only attachments creates file cards. Send text, files, or both, up to 20 distinct files. Files a user cannot read are copied into the private conversation storage."""
    from ..worker import deliver

    ctx = runtime.context
    s, agent = ctx.services, ctx.agent
    if not content.strip() and not attachments:
        raise ValueError("A message requires content or attachments")
    original = (
        await messages.incoming(s.db, ctx.id, in_reply_to)
        if in_reply_to is not None
        else None
    )
    if original and (
        original["source_kind"] not in ("user", "agent", "box")
        or original.get("input_type", "message") != "message"
    ):
        raise ValueError("System events are not reply destinations")
    if to is None and original is None:
        raise ValueError("New messages require to; replies require in_reply_to")
    async with s.db.connection() as conn:
        if original and to is None:
            if original["source_kind"] == "box":
                query, params = (
                    "SELECT representative_agent_id AS id, id AS box_id FROM boxes WHERE id=%s",
                    (original["source_id"],),
                )
            elif original["source_kind"] == "agent":
                query, params = (
                    "SELECT id,box_id FROM agents WHERE id=%s AND leta_id=%s",
                    (original["source_id"], ctx.root),
                )
            else:
                query, params = (
                    "SELECT %s::uuid AS id,NULL::uuid AS box_id",
                    (original["source_id"],),
                )
            recipient = await (await conn.execute(query, params)).fetchone()
        elif ctx.id == ctx.root:
            recipient = await (
                await conn.execute(
                    "SELECT representative_agent_id AS id,id AS box_id FROM boxes WHERE leta_id=%s AND name=%s AND state='active'",
                    (ctx.root, to),
                )
            ).fetchone()
        elif to == "root":
            recipient = {"id": ctx.root, "box_id": None}
        else:
            recipient = await (
                await conn.execute(
                    "SELECT id,box_id FROM agents WHERE leta_id=%s AND box_id=%s AND name=%s",
                    (ctx.root, agent["box_id"], to),
                )
            ).fetchone()
        human = bool(original and original["source_kind"] == "user" and to is None)
        if recipient is None:
            if ctx.id != ctx.root:
                raise ValueError("recipient is outside the communication graph")
            try:
                target = UUID(str(to))
            except ValueError:
                raise LookupError(
                    "recipient not found; use an exact box name or member user_id"
                ) from None
            human = True
        else:
            target = cast(UUID, recipient["id"])
        if original:
            expected = original["source_id"]
            if original["source_kind"] == "box":
                matched = recipient is not None and recipient["box_id"] == expected
            else:
                matched = target == expected
            if not matched:
                raise ValueError("to does not match the sender of in_reply_to")
    if (
        target == ctx.root
        and ctx.id != ctx.root
        and agent["representative_agent_id"] != ctx.id
    ):
        raise ValueError(
            "Only the representative can contact root; send the result through your permitted teammates"
        )
    id = request_id(runtime)
    if human:
        await s.auth.require(
            Actor("user", target),
            "workspace",
            cast(UUID, agent["workspace_id"]),
            "participate",
        )
    attachment_content = ""
    if attachments or file_refs.PATH_PATTERN.search(content):
        vfs = (await session(runtime)).vfs

        async def stat(path: str) -> FileStat:
            return await vfs.stat(file_path(path))

        content, attachment_content = await file_refs.resolve(
            content, attachments or [], stat
        )
    try:
        refs: list[JSON] = await file_refs.validate(
            s,
            cast(UUID, agent["workspace_id"]),
            Actor("agent", ctx.root),
            Actor("user", target) if human else Actor("agent", ctx.root),
            content + "\n" + attachment_content,
            copy_request=id if human else None,
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
        raise ValueError(error.details() or "Could not attach files") from error
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
        ),
        content,
    )
    refs = [
        replacements[f"{storage}/{node}"]
        for _, storage, node in file_refs.references(attachment_content)
    ]
    if human:
        await messages.deliver_user(
            s.db,
            ctx.root,
            target,
            content,
            id,
            cast(UUID, original["conversation_id"])
            if original
            else messages.conversation(ctx.root, "user", target),
            cast(UUID, original["id"]) if original else None,
            refs,
        )
        from .. import events

        await events.changed(s.redis, ctx.root, "messages", id, target)
    else:
        assert recipient is not None
        source_kind = "box" if target == ctx.root and agent["box_id"] else "agent"
        source = cast(UUID, agent["box_id"]) if source_kind == "box" else ctx.id
        endpoint = cast(UUID, recipient["box_id"]) if recipient["box_id"] else source
        conversation = (
            cast(UUID, original["conversation_id"])
            if original
            else messages.conversation(
                ctx.root,
                "box" if recipient["box_id"] or agent["box_id"] else "agent",
                endpoint,
            )
        )
        await deliver(
            s,
            Message(
                id=id,
                recipient_agent_id=target,
                source_kind=source_kind,
                source_id=source,
                conversation_id=conversation,
                content=content,
                file_refs=refs,
                in_reply_to_message_id=cast(UUID, original["id"]) if original else None,
            ),
        )
    result: JSON = {"sent": True}
    return presented(
        "inbox_send", result, {"sent": True, "content": content, "file_refs": refs}
    )


@tool(response_format="content_and_artifact")
async def inbox_react(
    runtime: ToolRuntime[Context, State],
    message: Annotated[int, Field(ge=1)],
    emoji: str,
    action: Literal["add", "remove"] = "add",
) -> tuple[JSON, dict[str, JSON]]:
    """React to a received user or teammate message using its inbox message number. One emoji per agent per message; add replaces your previous emoji, remove clears it. Feedback is silent and does not wake another agent."""
    ctx = runtime.context
    original = await messages.incoming(ctx.services.db, ctx.id, message)
    result = await reactions.react(
        ctx.services.db,
        ctx.services.auth,
        ctx.root,
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
        ctx.root,
        "reactions",
        cast(UUID, original["id"]),
        UUID(str(result["user_id"])) if result["user_id"] else None,
    )
    return presented("reaction", result, result)


@tool(response_format="content_and_artifact")
async def inbox_list(
    runtime: ToolRuntime[Context, State],
    cursor: str = "",
    unread_only: bool = True,
    source_id: UUID | None = None,
) -> tuple[JSON, dict[str, JSON]]:
    """List inbox notifications grouped by conversation, including silent feedback that does not wake you."""
    ctx = runtime.context
    result, rows = await messages.list_inbox(
        ctx.services.db, ctx.id, int(cursor or 0), unread_only, source_id
    )
    return result, {"ui": messages.input_data(rows, root=True)}


@tool(response_format="content_and_artifact")
async def inbox_read(
    runtime: ToolRuntime[Context, State],
    message: Annotated[int, Field(ge=1)],
    cursor: str = "",
    unread_only: bool = True,
) -> tuple[str, dict[str, JSON]]:
    """Read up to 20 unread messages in the conversation containing message, oldest first, and mark them read. message selects the conversation, not a starting position; cursor continues after a sequence. unread_only=false also rereads previously read messages."""
    ctx = runtime.context
    text, rows = await messages.read(
        ctx.services.db,
        ctx.id,
        message,
        int(cursor or 0),
        unread_only,
    )
    from .. import events

    for user in {
        cast(UUID, row["source_id"]) for row in rows if row["source_kind"] == "user"
    }:
        async with ctx.services.db.connection() as conn:
            await conn.execute(
                "UPDATE agent_messages SET processing_run_id=%s WHERE recipient_agent_id=%s AND source_kind='user' AND source_id=%s AND id=ANY(%s)",
                (ctx.run_id, ctx.id, user, [row["id"] for row in rows]),
            )
        await events.changed(ctx.services.redis, ctx.root, "messages", ctx.id, user)
    return text, {"ui": messages.input_data(rows, root=False)}


@tool(response_format="content_and_artifact")
async def workspace_get(
    runtime: ToolRuntime[Context, State], cursor: UUID | None = None
) -> tuple[JSON, dict[str, JSON]]:
    """Get your identity, home and allowed messaging recipients."""
    ctx = runtime.context
    async with ctx.services.db.connection() as conn:
        if ctx.agent["box_id"] is None:
            rows = await (
                await conn.execute(
                    "SELECT id,name,description FROM boxes WHERE leta_id=%s AND state='active' AND (%s::uuid IS NULL OR id>%s) ORDER BY id LIMIT 20",
                    (ctx.root, cursor, cursor),
                )
            ).fetchall()
        else:
            rows = await (
                await conn.execute(
                    """SELECT a.id,a.name,a.description FROM agents a JOIN box_edges e ON
                (e.agent_low_id=%s AND e.agent_high_id=a.id) OR (e.agent_high_id=%s AND e.agent_low_id=a.id)
                WHERE e.box_id=%s AND (%s::uuid IS NULL OR a.id>%s) ORDER BY a.id LIMIT 20""",
                    (ctx.id, ctx.id, ctx.agent["box_id"], cursor, cursor),
                )
            ).fetchall()
            box = await (
                await conn.execute(
                    "SELECT representative_agent_id FROM boxes WHERE id=%s",
                    (ctx.agent["box_id"],),
                )
            ).fetchone()
            if box and box["representative_agent_id"] == ctx.id and cursor is None:
                rows.insert(
                    0, {"id": ctx.root, "name": "root", "description": "Root agent"}
                )
    result: JSON = {
        **(
            {"workdir": f"~/.boxes/{ctx.agent['box_name']}/"}
            if ctx.agent["box_id"]
            else {}
        ),
        "name": str(ctx.agent["name"]),
        "home": "~",
        "recipients": [
            {"name": str(row["name"]), "description": str(row["description"])}
            for row in rows
        ],
        **({"next_cursor": str(rows[-1]["id"])} if len(rows) >= 20 else {}),
    }
    return presented("workspace_get", result, result)


@tool(response_format="content_and_artifact")
async def workspace_member_list(
    runtime: ToolRuntime[Context, State], cursor: str = ""
) -> tuple[JSON, dict[str, JSON]]:
    """Find current workspace members and user IDs for HITL."""
    ctx = runtime.context
    result = await ctx.services.auth.members(
        ctx.services.internal, cast(UUID, ctx.agent["workspace_id"]), cursor
    )
    if not result.get("next_cursor"):
        result.pop("next_cursor", None)
    return presented("workspace_member_list", result, result)


@tool(response_format="content_and_artifact")
async def box_create(
    runtime: ToolRuntime[Context, State],
    name: str,
    letis: list[LetiDefinition],
    edges: list[tuple[str, str]],
    representative: str,
    description: str = "",
) -> tuple[JSON, dict[str, JSON]]:
    """Create a fixed team with shared home. Give each Leti a name and a role title (titles may repeat). Edges are bidirectional; list each pair once. Send work to the box with inbox_send."""
    from ..worker import operation

    ctx = runtime.context
    id = request_id(runtime)
    creation = BoxCreation(
        leta_id=ctx.root,
        box_id=id,
        request_id=id,
        request=CreateBox(
            name=name,
            description=description,
            letis=letis,
            edges=edges,
            representative=representative,
        ),
    )
    await operation(
        ctx.services,
        ResourceOperation(
            id=id,
            request_id=id,
            action="create",
            box=creation,
            bridge_queue=ctx.services.config["dependencies"]["temporal"]["queues"][
                "leta_bridge"
            ],
        ),
        wait=True,
    )
    await ctx.filesystem.changed(f"~/.boxes/{name}")
    result = f"Box: {name}\nState: active\nWork directory: ~/.boxes/{name}/\nRepresentative: {representative}"
    return presented(
        "box_create",
        result,
        {
            "name": name,
            "state": "active",
            "home": f"~/.boxes/{name}/",
            "representative": representative,
            "letis": [item.model_dump(mode="json") for item in letis],
            "edges": [list(edge) for edge in edges],
        },
    )


@tool(response_format="content_and_artifact")
async def box_list(
    runtime: ToolRuntime[Context, State], cursor: UUID | None = None
) -> tuple[JSON, dict[str, JSON]]:
    """List boxes and work counts."""
    ctx = runtime.context
    result = await boxes.list_boxes(ctx.services.db, ctx.root, cursor)
    lines = [
        f"{item['name']} | {item['state']} | {item['agent_count']} members\n{item['description']}"
        for item in cast(list[dict[str, JSON]], result["boxes"])
    ]
    if result.get("next_cursor"):
        lines.append(f"Next cursor: {result['next_cursor']}")
    return presented("box_list", "\n\n".join(lines) or "No boxes.", result)


@tool(response_format="content_and_artifact")
async def box_get(
    runtime: ToolRuntime[Context, State], box: str, include_prompts: bool = False
) -> tuple[JSON, dict[str, JSON]]:
    """Get box members, links and representative; prompts are opt-in."""
    ctx = runtime.context
    result = await boxes.get(ctx.services.db, ctx.root, box, include_prompts)
    members = cast(list[dict[str, JSON]], result["letis"])
    names = {str(member["id"]): str(member["name"]) for member in members}
    lines = [
        f"Box: {result['name']} | {result['state']}",
        str(result["description"]),
        f"Work directory: ~/.boxes/{result['name']}/",
        f"Representative: {names[str(result['representative_agent_id'])]}",
        "Members:",
    ]
    for member in members:
        lines.append(f"- {member['name']}: {member['description']}")
        if include_prompts:
            lines.append(str(member["system_prompt"]))
    lines.append("Links:")
    for edge in cast(list[dict[str, JSON]], result["edges"]):
        lines.append(
            f"- {names[str(edge['agent_low_id'])]} ↔ {names[str(edge['agent_high_id'])]}"
        )
    return presented("box_get", "\n".join(lines), result)


@tool(response_format="content_and_artifact")
async def box_delete(
    runtime: ToolRuntime[Context, State], box: str
) -> tuple[JSON, dict[str, JSON]]:
    """Stop a box, remove its schedules/pending requests and trash its work directory. Files elsewhere in shared home remain."""
    from ..worker import operation

    ctx = runtime.context
    identity = await boxes.named(ctx.services.db, ctx.root, box)
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
    recipient_user_id: UUID,
    questions: Annotated[list[hitl.Question], Field(min_length=1, max_length=10)],
    title: str = "",
) -> tuple[JSON, dict[str, JSON]]:
    """Ask any current workspace member; the answer arrives later in your inbox."""
    ctx = runtime.context
    from ..worker import submit_hitl

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
    user_id: UUID,
    role: Literal["viewer", "editor"] = "viewer",
    reason: str = "",
) -> tuple[JSON, dict[str, JSON]]:
    """Ask a workspace member for access to their Personal storage, shared by root and its Leti. Wait for the grant outcome."""
    ctx = runtime.context
    from ..worker import submit_hitl

    result = await submit_hitl(
        ctx.services,
        hitl.OpenRequest(
            id=request_id(runtime),
            requester_agent_id=ctx.id,
            recipient_user_id=user_id,
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
                "recipient_user_id": str(user_id),
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
            "recipient_user_id": str(user_id),
            "payload": {"role": role, "reason": reason},
        },
    )


async def own_hitl(ctx: Context, id: UUID) -> dict[str, JSON]:
    return await hitl.get(
        ctx.services.db,
        id,
        root=ctx.root,
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
                    ctx.root,
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
async def root_hitl_list(
    runtime: ToolRuntime[Context, State],
    status: Status | None = None,
    cursor: UUID | None = None,
    box: str | None = None,
) -> tuple[JSON, dict[str, JSON]]:
    """List human requests across root and boxes; box filters by requester box."""
    result = await list_hitl(
        runtime.context,
        status,
        cursor,
        cast(
            UUID,
            (await boxes.named(runtime.context.services.db, runtime.context.root, box))[
                "id"
            ],
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
        root=ctx.root,
        creator=ctx.id if ctx.agent["box_id"] is not None else None,
    )


@tool("schedule_create", response_format="content_and_artifact")
async def root_schedule_create(
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
        box = await boxes.named(ctx.services.db, ctx.root, target_box)
        target = UUID(str(box["representative_agent_id"]))
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
        target_box or "root",
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
        str(ctx.agent["box_name"])
        + (
            ""
            if ctx.id == ctx.agent["representative_agent_id"]
            else f"/{ctx.agent['name']}"
        ),
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
                """SELECT sc.id,sc.title,sc.type,sc.spec,sc.paused,sc.deleted_at,CASE WHEN target.id=b.representative_agent_id THEN b.name WHEN target.box_id IS NOT NULL THEN b.name||'/'||target.name ELSE 'root' END AS target_name FROM schedules sc JOIN agents a ON a.id=sc.creator_agent_id
            JOIN agents target ON target.id=sc.target_agent_id LEFT JOIN boxes b ON b.id=target.box_id WHERE a.leta_id=%s AND (%s::uuid IS NULL OR a.id=%s)
            AND (%s::uuid IS NULL OR target.box_id=%s) AND (%s::uuid IS NULL OR sc.id>%s) ORDER BY sc.id LIMIT 20""",
                (
                    ctx.root,
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
async def root_schedule_list(
    runtime: ToolRuntime[Context, State],
    cursor: UUID | None = None,
    box: str | None = None,
) -> tuple[JSON, dict[str, JSON]]:
    """List root and box schedules; box filters by target box."""
    return await list_schedules(
        runtime.context,
        cursor,
        cast(
            UUID,
            (await boxes.named(runtime.context.services.db, runtime.context.root, box))[
                "id"
            ],
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
    """List files and directories; /mnt lists accessible personal, shared and conversation storages with their identity and write access."""
    if file_path(path) == "/mnt":
        runtime.context.filesystem.discovered = 0
    vfs = (await session(runtime)).vfs
    if file_path(path) == "/mnt":
        content = (
            "\n\n".join(
                f"{binding.name} — {'read/write' if binding.writable else 'read-only'}\n  /mnt/{id}"
                for id, binding in runtime.context.filesystem.bindings.items()
            )
            or "No accessible external storages."
        )
        return presented(
            "file_list",
            content,
            {
                "items": [
                    {"path": f"/mnt/{id}", "kind": "directory", "name": binding.name}
                    for id, binding in runtime.context.filesystem.bindings.items()
                ]
            },
        )
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
            "leta_id": str(ctx.root),
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
    """Run supported shell commands and Python over workspace files; use curl or wget for HTTP requests. Use cwd for the working directory. Output is capped; read the saved output when needed. No host programs."""
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


def tools(*, root: bool) -> list[BaseTool]:
    shared = [
        inbox_send,
        inbox_react,
        inbox_read,
        inbox_list,
        workspace_get,
        workspace_member_list,
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
    if root:
        catalog = [
            *shared,
            root_hitl_list,
            root_schedule_create,
            root_schedule_list,
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
