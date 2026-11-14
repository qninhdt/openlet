import asyncio
import shlex
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Literal, cast
from uuid import UUID

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from langfuse import propagate_attributes
from mirage import ContentType, Session
from openlet_sdk.config import JSON
from pydantic import Field

from .. import boxes, history, hitl, messages, schedules
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
from .inbox import State

type Status = Literal[
    "pending", "answered", "accepted", "denied", "cancelled", "expired"
]


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


@tool
async def inbox_send(
    runtime: ToolRuntime[Context, State],
    to: UUID,
    content: str,
    in_reply_to: UUID | None = None,
) -> JSON:
    """Send a message to an allowed recipient; final activity text does not deliver."""
    from ..worker import deliver

    ctx = runtime.context
    s, agent = ctx.services, ctx.agent
    target = to
    id = request_id(runtime)
    async with s.db.connection() as conn:
        recipient = await (
            await conn.execute(
                """SELECT a.id,a.box_id FROM agents a WHERE a.leta_id=%s AND
            (a.id=%s OR a.id=(SELECT representative_agent_id FROM boxes WHERE id=%s AND leta_id=%s))""",
                (ctx.root, target, target, ctx.root),
            )
        ).fetchone()
    if recipient is None:
        if ctx.id != ctx.root:
            raise ValueError("recipient is outside the communication graph")
        await s.auth.require(
            Actor("user", target),
            "workspace",
            cast(UUID, agent["workspace_id"]),
            "participate",
        )
        return await messages.deliver_user(
            s.db,
            ctx.root,
            target,
            content,
            id,
            messages.conversation(ctx.root, "user", target),
            in_reply_to,
        )
    target = cast(UUID, recipient["id"])
    source_kind = "box" if target == ctx.root and agent["box_id"] else "agent"
    source = cast(UUID, agent["box_id"]) if source_kind == "box" else ctx.id
    if in_reply_to:
        async with s.db.connection() as conn:
            original = await (
                await conn.execute(
                    "SELECT conversation_id FROM agent_messages WHERE id=%s AND recipient_agent_id=%s",
                    (in_reply_to, ctx.id),
                )
            ).fetchone()
        if original is None:
            raise ValueError("reply message not found in your inbox")
        conversation = cast(UUID, original["conversation_id"])
    else:
        endpoint = cast(UUID, recipient["box_id"]) if recipient["box_id"] else source
        conversation = messages.conversation(
            ctx.root,
            "box" if recipient["box_id"] or agent["box_id"] else "agent",
            endpoint,
        )
    return await deliver(
        s,
        Message(
            id=id,
            recipient_agent_id=target,
            source_kind=source_kind,
            source_id=source,
            conversation_id=conversation,
            content=content,
            in_reply_to_message_id=in_reply_to,
        ),
    )


@tool
async def inbox_list(
    runtime: ToolRuntime[Context, State],
    cursor: str = "",
    unread_only: bool = True,
    source_id: UUID | None = None,
) -> JSON:
    """List inbox notifications grouped by conversation."""
    ctx = runtime.context
    return await messages.list_inbox(
        ctx.services.db, ctx.id, int(cursor or 0), unread_only, source_id
    )


@tool
async def inbox_read(
    runtime: ToolRuntime[Context, State],
    conversation_id: UUID,
    cursor: str = "",
    unread_only: bool = True,
) -> JSON:
    """Read messages and mark returned items read; unread_only=false includes previously read messages."""
    ctx = runtime.context
    return await messages.read(
        ctx.services.db, ctx.id, conversation_id, int(cursor or 0), unread_only
    )


@tool
async def workspace_get(
    runtime: ToolRuntime[Context, State], cursor: UUID | None = None
) -> JSON:
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
                    0, {"id": ctx.root, "name": "Leta", "description": "Root agent"}
                )
    return {
        "id": str(ctx.id),
        "name": str(ctx.agent["name"]),
        "home": "~",
        "recipients": [json_row(row) for row in rows],
        "next_cursor": str(rows[-1]["id"]) if len(rows) >= 20 else None,
    }


@tool
async def workspace_member_list(
    runtime: ToolRuntime[Context, State], cursor: str = ""
) -> JSON:
    """Find current workspace members and user IDs for HITL."""
    ctx = runtime.context
    return await ctx.services.auth.members(
        ctx.services.internal, cast(UUID, ctx.agent["workspace_id"]), cursor
    )


@tool
async def box_create(
    runtime: ToolRuntime[Context, State],
    name: str,
    letis: list[LetiDefinition],
    edges: list[tuple[str, str]],
    representative: str,
    description: str = "",
) -> JSON:
    """Create a fixed team with shared home. Send tasks separately with inbox_send."""
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
    return await operation(
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


@tool
async def box_list(
    runtime: ToolRuntime[Context, State], cursor: UUID | None = None
) -> JSON:
    """List boxes and work counts."""
    ctx = runtime.context
    return await boxes.list_boxes(ctx.services.db, ctx.root, cursor)


@tool
async def box_get(
    runtime: ToolRuntime[Context, State], box: str, include_prompts: bool = False
) -> JSON:
    """Get box members, links and representative; prompts are opt-in."""
    ctx = runtime.context
    return await boxes.get(ctx.services.db, ctx.root, box, include_prompts)


@tool
async def box_delete(runtime: ToolRuntime[Context, State], box_id: UUID) -> JSON:
    """Stop Leti, remove affected schedules/pending requests and trash shared home. Root storage grants remain."""
    from ..worker import operation

    ctx = runtime.context
    return await operation(
        ctx.services,
        ResourceOperation(
            id=box_id,
            request_id=request_id(runtime),
            action="delete_box",
            bridge_queue=ctx.services.config["dependencies"]["temporal"]["queues"][
                "leta_bridge"
            ],
        ),
        wait=True,
    )


@tool
async def hitl_ask(
    runtime: ToolRuntime[Context, State],
    recipient_user_id: UUID,
    questions: Annotated[list[hitl.Question], Field(min_length=1, max_length=10)],
    title: str = "",
) -> JSON:
    """Ask any current workspace member; the answer arrives later in your inbox."""
    ctx = runtime.context
    from ..worker import submit_hitl

    return await submit_hitl(
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


@tool
async def hitl_request(
    runtime: ToolRuntime[Context, State],
    user_id: UUID,
    role: Literal["viewer", "editor"] = "viewer",
    reason: str = "",
) -> JSON:
    """Ask a workspace member for access to their Personal storage, shared by root and its Leti. Wait for the grant outcome."""
    ctx = runtime.context
    from ..worker import submit_hitl

    return await submit_hitl(
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


async def own_hitl(ctx: Context, id: UUID) -> dict[str, JSON]:
    return await hitl.get(
        ctx.services.db,
        id,
        root=ctx.root,
        requester=ctx.id if ctx.agent["box_id"] is not None else None,
    )


@tool
async def hitl_get(runtime: ToolRuntime[Context, State], request_id: UUID) -> JSON:
    """Get a human request, its form, decision and grant outcome."""
    return await own_hitl(runtime.context, request_id)


@tool
async def hitl_cancel(
    runtime: ToolRuntime[Context, State], request_id: UUID, reason: str = ""
) -> JSON:
    """Cancel a pending human request; does not revoke granted access."""
    ctx = runtime.context
    await own_hitl(ctx, request_id)
    return await ctx.services.temporal.get_workflow_handle(  # pyright: ignore[reportUnknownMemberType]  # Temporal has an untyped overload for args.
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


async def list_hitl(
    ctx: Context, status: Status | None, cursor: UUID | None, box_id: UUID | None = None
) -> JSON:
    async with ctx.services.db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT h.id,h.requester_agent_id,h.type,h.title,h.status,h.outcome,h.created_at
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
    return {
        "requests": [json_row(row) for row in rows],
        "next_cursor": str(rows[-1]["id"]) if len(rows) == 20 else None,
    }


@tool("hitl_list")
async def root_hitl_list(
    runtime: ToolRuntime[Context, State],
    status: Status | None = None,
    cursor: UUID | None = None,
    box_id: UUID | None = None,
) -> JSON:
    """List human requests across root and boxes; box_id filters by requester box."""
    return await list_hitl(runtime.context, status, cursor, box_id)


@tool("hitl_list")
async def leti_hitl_list(
    runtime: ToolRuntime[Context, State],
    status: Status | None = None,
    cursor: UUID | None = None,
) -> JSON:
    """List your human requests; use hitl_get for details."""
    return await list_hitl(runtime.context, status, cursor)


async def change_schedule(
    runtime: ToolRuntime[Context, State], change: schedules.Change
) -> JSON:
    from ..worker import submit_schedule

    return await submit_schedule(runtime.context.services, change)


async def own_schedule(ctx: Context, id: UUID) -> dict[str, JSON]:
    return await schedules.get(
        ctx.services.db,
        id,
        root=ctx.root,
        creator=ctx.id if ctx.agent["box_id"] is not None else None,
    )


@tool("schedule_create")
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
    target_box_id: UUID | None = None,
) -> JSON:
    """Schedule an inbox instruction for yourself or a box. Choose exactly one: at, after_seconds, every_seconds, calendar."""
    ctx = runtime.context
    id = request_id(runtime)
    target = ctx.id
    if target_box_id:
        box = await boxes.identity(ctx.services.db, ctx.root, target_box_id)
        target = UUID(str(box["representative_agent_id"]))
    return await change_schedule(
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
    )


@tool("schedule_create")
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
) -> JSON:
    """Schedule an inbox instruction for yourself. Choose exactly one: at, after_seconds, every_seconds, calendar."""
    ctx = runtime.context
    id = request_id(runtime)
    return await change_schedule(
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
    )


@tool
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
) -> JSON:
    """Update only supplied fields. At most one timing selector; recipient stays fixed. ends_at=null clears the cutoff."""
    ctx = runtime.context
    old = await own_schedule(ctx, schedule_id)
    message = runtime.state["messages"][-1]
    assert isinstance(message, AIMessage)
    call = next(
        call for call in message.tool_calls if call["id"] == runtime.tool_call_id
    )
    return await change_schedule(
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
    )


@tool
async def schedule_delete(
    runtime: ToolRuntime[Context, State], schedule_id: UUID
) -> JSON:
    """Stop future scheduled instructions; already-delivered work remains."""
    old = await own_schedule(runtime.context, schedule_id)
    return await change_schedule(
        runtime,
        schedules.Change(
            request_id=request_id(runtime),
            schedule_id=schedule_id,
            creator_agent_id=UUID(str(old["creator_agent_id"])),
            target_agent_id=UUID(str(old["target_agent_id"])),
            action="delete",
        ),
    )


@tool
async def schedule_get(runtime: ToolRuntime[Context, State], schedule_id: UUID) -> JSON:
    """Get a schedule instruction, timing and upcoming forecasts."""
    value = await own_schedule(runtime.context, schedule_id)
    return {
        **value,
        **await schedules.upcoming(runtime.context.services.temporal, value),
    }


async def list_schedules(
    ctx: Context, cursor: UUID | None, box_id: UUID | None = None
) -> JSON:
    async with ctx.services.db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT sc.* FROM schedules sc JOIN agents a ON a.id=sc.creator_agent_id
            JOIN agents target ON target.id=sc.target_agent_id WHERE a.leta_id=%s AND (%s::uuid IS NULL OR a.id=%s)
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
    return {
        "schedules": [json_row(row) for row in rows],
        "next_cursor": str(rows[-1]["id"]) if len(rows) == 20 else None,
    }


@tool("schedule_list")
async def root_schedule_list(
    runtime: ToolRuntime[Context, State],
    cursor: UUID | None = None,
    box_id: UUID | None = None,
) -> JSON:
    """List root and box schedules; box_id filters by target box."""
    return await list_schedules(runtime.context, cursor, box_id)


@tool("schedule_list")
async def leti_schedule_list(
    runtime: ToolRuntime[Context, State], cursor: UUID | None = None
) -> JSON:
    """List your schedules."""
    return await list_schedules(runtime.context, cursor)


@tool
async def history_search(
    runtime: ToolRuntime[Context, State], query: str = "", cursor: str = ""
) -> JSON:
    """Search your activity history by words; omit query for recent previews."""
    ctx = runtime.context
    return await history.search(
        ctx.services.db, ctx.id, int(cursor) if cursor else None, query
    )


@tool
async def history_read(
    runtime: ToolRuntime[Context, State],
    entry_id: UUID,
    start_line: Annotated[int, Field(ge=1)] = 1,
) -> JSON:
    """Read a history entry; follow next_start_line for more."""
    ctx = runtime.context
    return await history.read(ctx.services.db, ctx.id, entry_id, start_line)


@tool
async def file_list(
    runtime: ToolRuntime[Context, State],
    path: str = "~",
    cursor: str = "",
    depth: Annotated[int, Field(ge=1, le=10)] = 1,
) -> JSON:
    """List files and directories; /mnt lists accessible storages and whether each is writable."""
    vfs = (await session(runtime)).vfs
    if file_path(path) == "/mnt":
        return {
            "items": [
                {"path": f"/mnt/{name}", "kind": "directory", "writable": write}
                for name, (_, write) in runtime.context.filesystem.bindings.items()
            ],
            "next_cursor": None,
            "truncated": False,
        }
    result, _ = await vfs.dispatch("list_page", scope(path), cursor=cursor, depth=depth)
    return cast(JSON, result)


@tool(response_format="content_and_artifact")
async def file_read(
    runtime: ToolRuntime[Context, State],
    path: str,
    start_line: Annotated[int, Field(ge=1)] = 1,
) -> tuple[JSON, str | None]:
    """Read a text window, image preview or uploaded-document artifacts; follow returned continuations."""
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
            return cast(JSON, result), path
        return cast(JSON, result), None
    data = await vfs.read(file_path(path))
    lines = data.decode().splitlines()
    text = "\n".join(
        f"{i + 1}: {text}"
        for i, text in enumerate(
            lines[start_line - 1 : start_line + 199], start_line - 1
        )
    )
    return {
        "content": text[:16000],
        "next_start_line": start_line + 200 if len(lines) >= start_line + 200 else None,
        "truncated": len(text) > 16000,
    }, None


@tool
async def file_write(
    runtime: ToolRuntime[Context, State],
    path: str,
    content: str,
    overwrite: bool = False,
) -> JSON:
    """Create text; overwrite=true replaces the entire file. Use file_edit for partial changes."""
    token = current_operation.set(request_id(runtime))
    try:
        await (await session(runtime)).vfs.dispatch(
            "write_text", scope(path), content=content, overwrite=overwrite
        )
    finally:
        current_operation.reset(token)
    return {"path": path}


@tool
async def file_edit(
    runtime: ToolRuntime[Context, State],
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
) -> JSON:
    """Replace literal text; exactly one match unless replace_all=true. Empty new_text deletes the match."""
    token = current_operation.set(request_id(runtime))
    try:
        await (await session(runtime)).vfs.dispatch(
            "edit_text",
            scope(path),
            old_text=old_text,
            new_text=new_text,
            replace_all=replace_all,
        )
    finally:
        current_operation.reset(token)
    return {"path": path}


@tool
async def file_semantic_search(
    runtime: ToolRuntime[Context, State],
    query: str,
    paths: Annotated[list[str] | None, Field(max_length=5)] = None,
) -> JSON:
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
        return {
            "results": list(
                await asyncio.gather(*(search(item) for item in paths or ["~"]))
            )
        }


@tool
async def exec_shell(
    runtime: ToolRuntime[Context, State], command: str, cwd: str = "~"
) -> JSON:
    """Run supported shell commands and pipelines over workspace files; no host programs or network."""
    return await shell(await session(runtime), command, cwd=file_path(cwd))


@tool
async def exec_python(runtime: ToolRuntime[Context, State], code: str) -> JSON:
    """Run Python calculations and file transformations using the supported modules in your instructions; no packages, network or state across calls. Use relative paths instead of Path.home(); compile() is unavailable."""
    return await shell(
        await session(runtime), f"python -c {shlex.quote(code)}", runtime="monty"
    )


def tools(*, root: bool) -> list[BaseTool]:
    shared = [
        inbox_send,
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
        exec_shell,
        exec_python,
        file_semantic_search,
    ]
    if root:
        return [
            *shared,
            root_hitl_list,
            root_schedule_create,
            root_schedule_list,
            inbox_list,
            inbox_read,
            box_create,
            box_list,
            box_get,
            box_delete,
        ]
    return [*shared, leti_hitl_list, leti_schedule_create, leti_schedule_list]
