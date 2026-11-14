import asyncio
import json
import posixpath
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Literal, cast
from uuid import UUID

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from langfuse import propagate_attributes
from mirage import ContentType, Session
from openlet_sdk.config import JSON
from pydantic import Field

from .. import boxes, history, hitl, messages, schedules
from ..agents import stable
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
    content: str,
    to: str | None = None,
    in_reply_to: Annotated[int | None, Field(ge=1)] = None,
) -> JSON:
    """Send a message to a box name, permitted teammate name, root, or human user_id. To reply, use an incoming message number; to can then be omitted."""
    from ..worker import deliver

    ctx = runtime.context
    s, agent = ctx.services, ctx.agent
    original = (
        await messages.incoming(s.db, ctx.id, in_reply_to)
        if in_reply_to is not None
        else None
    )
    if original and original["source_kind"] not in ("user", "agent", "box"):
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
        )
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
                in_reply_to_message_id=cast(UUID, original["id"]) if original else None,
            ),
        )
    return {"sent": True}


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
    message: Annotated[int, Field(ge=1)],
    cursor: str = "",
    unread_only: bool = True,
) -> JSON:
    """Read the conversation identified by an incoming message number and mark returned items read. unread_only=false includes previously read messages."""
    ctx = runtime.context
    original = await messages.incoming(ctx.services.db, ctx.id, message)
    return await messages.read(
        ctx.services.db,
        ctx.id,
        cast(UUID, original["conversation_id"]),
        int(cursor or 0),
        unread_only,
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
                    0, {"id": ctx.root, "name": "root", "description": "Root agent"}
                )
    return {
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


@tool
async def workspace_member_list(
    runtime: ToolRuntime[Context, State], cursor: str = ""
) -> JSON:
    """Find current workspace members and user IDs for HITL."""
    ctx = runtime.context
    result = await ctx.services.auth.members(
        ctx.services.internal, cast(UUID, ctx.agent["workspace_id"]), cursor
    )
    if not result.get("next_cursor"):
        result.pop("next_cursor", None)
    return result


@tool
async def box_create(
    runtime: ToolRuntime[Context, State],
    name: str,
    letis: list[LetiDefinition],
    edges: list[tuple[str, str]],
    representative: str,
    description: str = "",
) -> JSON:
    """Create a fixed team with shared home. Edges are bidirectional; list each pair once. Send work to the box with inbox_send."""
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
    return f"Box: {name}\nState: active\nWork directory: ~/.boxes/{name}/\nRepresentative: {representative}"


@tool
async def box_list(
    runtime: ToolRuntime[Context, State], cursor: UUID | None = None
) -> JSON:
    """List boxes and work counts."""
    ctx = runtime.context
    result = await boxes.list_boxes(ctx.services.db, ctx.root, cursor)
    lines = [
        f"{item['name']} | {item['state']} | {item['agent_count']} members\n{item['description']}"
        for item in cast(list[dict[str, JSON]], result["boxes"])
    ]
    if result.get("next_cursor"):
        lines.append(f"Next cursor: {result['next_cursor']}")
    return "\n\n".join(lines) or "No boxes."


@tool
async def box_get(
    runtime: ToolRuntime[Context, State], box: str, include_prompts: bool = False
) -> JSON:
    """Get box members, links and representative; prompts are opt-in."""
    ctx = runtime.context
    identity = await boxes.named(ctx.services.db, ctx.root, box)
    result = await boxes.get(
        ctx.services.db, ctx.root, str(identity["id"]), include_prompts
    )
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
    return "\n".join(lines)


@tool
async def box_delete(runtime: ToolRuntime[Context, State], box: str) -> JSON:
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
    return {"box": box, "state": "archived"}


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
    return {"request_id": result["id"], "status": result["status"]}


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
        return {"status": "already_granted", "access": role}
    return {"request_id": result["id"], "status": result["status"]}


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
    return hitl.render(await own_hitl(runtime.context, request_id))


@tool
async def hitl_cancel(
    runtime: ToolRuntime[Context, State], request_id: UUID, reason: str = ""
) -> JSON:
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
    return {"request_id": str(request_id), "status": result["status"]}


async def list_hitl(
    ctx: Context, status: Status | None, cursor: UUID | None, box_id: UUID | None = None
) -> JSON:
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
    return "\n".join(lines) or (
        "No pending requests."
        if status == "pending"
        else "No requests matching this filter."
    )


@tool("hitl_list")
async def root_hitl_list(
    runtime: ToolRuntime[Context, State],
    status: Status | None = None,
    cursor: UUID | None = None,
    box: str | None = None,
) -> JSON:
    """List human requests across root and boxes; box filters by requester box."""
    return await list_hitl(
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

    result = await submit_schedule(runtime.context.services, change)
    if change.action == "delete":
        return {"schedule_id": str(change.schedule_id), "deleted": True}
    return {
        "schedule_id": result["id"],
        "target": await schedule_target(
            runtime.context, UUID(str(result["target_agent_id"]))
        ),
        "type": result["type"],
        "spec": result["spec"],
        "paused": result["paused"],
    }


async def schedule_target(ctx: Context, target: UUID) -> str:
    if target == ctx.root:
        return "root"
    async with ctx.services.db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT CASE WHEN a.id=b.representative_agent_id THEN b.name ELSE b.name||'/'||a.name END AS name FROM agents a JOIN boxes b ON b.id=a.box_id WHERE a.id=%s AND a.leta_id=%s",
                (target, ctx.root),
            )
        ).fetchone()
    assert row is not None
    return str(row["name"])


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
    target_box: str | None = None,
) -> JSON:
    """Schedule an inbox instruction for yourself or a box. Choose exactly one: at, after_seconds, every_seconds, calendar."""
    ctx = runtime.context
    id = request_id(runtime)
    target = ctx.id
    if target_box:
        box = await boxes.named(ctx.services.db, ctx.root, target_box)
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
        "target": await schedule_target(
            runtime.context, UUID(str(value["target_agent_id"]))
        ),
        **await schedules.upcoming(runtime.context.services.temporal, value),
    }


async def list_schedules(
    ctx: Context, cursor: UUID | None, box_id: UUID | None = None
) -> JSON:
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
    return "\n".join(lines) or "No schedules matching this filter."


@tool("schedule_list")
async def root_schedule_list(
    runtime: ToolRuntime[Context, State],
    cursor: UUID | None = None,
    box: str | None = None,
) -> JSON:
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
    return await history.search_text(
        ctx.services.db, ctx.id, int(cursor) if cursor else None, query
    )


@tool
async def history_read(
    runtime: ToolRuntime[Context, State],
    entry: Annotated[int, Field(ge=1)],
    start_line: Annotated[int, Field(ge=1)] = 1,
    limit: Annotated[int | None, Field(ge=1, le=2000)] = None,
) -> str:
    """Read an activity entry by its number from history_search; follow continuations when needed."""
    ctx = runtime.context
    return await history.read_text(ctx.services.db, ctx.id, entry, start_line, limit)


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
        return (
            "\n\n".join(
                f"{binding.name} — {'read/write' if binding.writable else 'read-only'}\n  /mnt/{id}"
                for id, binding in runtime.context.filesystem.bindings.items()
            )
            or "No accessible external storages."
        )
    result, _ = await vfs.dispatch("list_page", scope(path), cursor=cursor, depth=depth)
    return directory_text(path, cast(dict[str, JSON], result))


def directory_text(base: str, result: dict[str, JSON]) -> str:
    lines = [f"Directory: {base}"]
    for item in cast(list[dict[str, JSON]], result["items"]):
        child = posixpath.relpath(str(item["path"]), file_path(base))
        if child == ".":
            continue
        suffix = (
            "/ [document artifacts]"
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
) -> tuple[JSON, str | None]:
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
            return cast(JSON, result), path
        return directory_text(path, cast(dict[str, JSON], result)), None
    data = await vfs.read(file_path(path))
    return text_page(data.decode(), start_line, limit), None


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
            if len(excerpt) > 800:
                excerpt = excerpt[:800] + " [excerpt truncated]"
            size = len(excerpt.encode())
            if used + size <= BYTE_BUDGET:
                lines.append(name + "\n" + excerpt)
                used += size
            else:
                lines.append(name + " [excerpt omitted; read source]")
        groups.append(
            "\n\n".join(lines) if result["hits"] else f"No matches in {base}."
        )
    return "\n\n".join(groups)


@tool
async def execute(
    runtime: ToolRuntime[Context, State], command: str, cwd: str = "~"
) -> ToolMessage:
    """Run supported shell commands and Python over workspace files. Use cwd for the working directory. Output is capped; read the saved output when needed. No host programs or network access."""
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
            inbox_list,
            inbox_read,
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
