"""Workspace directory, subagent, HITL, schedule, and todo LangChain tools."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import grpc
from langchain_core.tools import ToolException
from langgraph.prebuilt import ToolRuntime  # noqa: TC002  # Evaluated at runtime by LangGraph ToolNode.get_type_hints.
from openlet_api.chat.v1 import chat_pb2 as chat_pb
from openlet_api.platform.v1 import internal_pb2 as plat_int_pb
from openlet_api.platform.v1 import platform_pb2 as plat_pb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from leta.auth import Actor
from leta.hitl.models import ApprovalPayload
from leta.hitl.service import (
    OpenHitlInput,
    Question,
    build_ask_form,
    cancel_hitl_workflow,
    get_hitl,
    list_leta_hitl,
    start_hitl_workflow,
)
from leta.runs import (
    AgentMessageEventData,
    InboxReceivedEventData,
    MessageEventData,
    RunFinishedEventData,
    ToolCallEventData,
    ToolResultEventData,
    list_recent_activity,
)
from leta.runtime.formatting import format_hitl_outcome, format_hitl_response
from leta.runtime.state import AgentState, RuntimeContext  # noqa: TC001  # Evaluated at runtime by LangGraph ToolNode.get_type_hints.
from leta.runtime.tools.base import ToolArgs, ToolResult, idempotency_key, make_tool
from leta.schedules.service import (
    Timing,
    create_schedule,
    delete_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
)
from leta.subagents.service import (
    list_leta_agents,
    list_workspace_root_agents,
    resolve_leta_agent,
    spawn_subagent,
    stop_agent_tree,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from langchain_core.tools import BaseTool
    from openlet_sdk.config import JSON

    from leta.subagents.service import ResolvedAgent

logger = logging.getLogger(__name__)

# --- Workspace Context & Directory ---


class EmptyArgs(ToolArgs):
    """Empty input schema for parameterless tools."""


class ListMembersArgs(ToolArgs):
    """Input schema for ``list_members``."""

    query: str = ""
    kind: Literal["all", "user", "agent"] = "all"
    limit: int = Field(default=30, ge=1, le=100)


@dataclass(frozen=True, slots=True)
class _WorkspaceUser:
    id: str
    name: str
    handle: str
    role: str

    def to_json(self) -> dict[str, JSON]:
        return {
            "id": self.id,
            "name": self.name,
            "handle": self.handle,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class _GroupSummary:
    id: str
    title: str
    handle: str

    def to_json(self) -> dict[str, JSON]:
        return {
            "id": self.id,
            "title": self.title,
            "handle": self.handle,
        }


@dataclass(frozen=True, slots=True)
class _MemberItem:
    kind: Literal["user", "agent"]
    id: str
    name: str
    handle: str
    role: str

    def to_json(self) -> dict[str, JSON]:
        return {
            "kind": self.kind,
            "id": self.id,
            "name": self.name,
            "handle": self.handle,
            "role": self.role,
        }


async def _fetch_workspace_human_users(rt: RuntimeContext) -> list[_WorkspaceUser]:
    s = rt.services
    rels = await s.auth.read_relationships("workspace", rt.workspace_id)
    roles = {
        str(r.subject.object.object_id): str(r.relation)
        for r in rels
        if r.subject.object.object_type == "user" and r.relation in ("owner", "member")
    }
    ids = list(roles)
    out: list[_WorkspaceUser] = []
    for i in range(0, len(ids), 100):
        resp = await s.platform_internal.BatchGetUsers(
            plat_int_pb.BatchGetUsersRequest(user_ids=ids[i : i + 100]), timeout=15
        )
        out.extend(
            _WorkspaceUser(
                id=str(u.id),
                name=str(u.display_name),
                handle=str(u.handle),
                role=roles.get(str(u.id), "member"),
            )
            for u in resp.users
        )
    return out


async def handle_get_context(
    *, runtime: ToolRuntime[RuntimeContext, AgentState]
) -> ToolResult:
    """Return a workspace snapshot covering members, peers, groups, subagents, HITL, and schedules."""
    rt = runtime.context
    s = rt.services
    agents = await list_leta_agents(s.db, rt.leta_id)
    subagents = [
        a for a in agents if a.parent_agent_id is not None and a.state == "active"
    ]

    if not rt.is_root:
        lines = [
            f"## Workspace Context (Subagent {rt.handle})",
            "Mounts: `/home` (~), `/shared`, `/user/<handle>`, `/chat/<handle>`, `/letfs/<storage_id>/<node_id>`",
            f"Active agents in this Leta ({len(agents)}):",
            *(
                f"- {a.handle} (agent:{a.handle}) | {a.name} ({a.title}) | {'running' if a.running else a.state}"
                for a in agents[:20]
            ),
        ]
        return "\n".join(lines), {
            "subagents": [a.model_dump(mode="json") for a in subagents]
        }

    ws_info = await s.platform_internal.GetWorkspaceInfo(
        plat_pb.WorkspaceRequest(workspace_id=str(rt.workspace_id)), timeout=15
    )
    all_users = await _fetch_workspace_human_users(rt)
    users_list = all_users[:30]

    peers = await list_workspace_root_agents(s.db, rt.workspace_id, limit=20)

    groups: list[_GroupSummary] = []
    try:
        c_resp = await s.chat.ListConversations(
            chat_pb.ListConversationsRequest(
                workspace_id=str(rt.workspace_id), page_size=50
            ),
            metadata=Actor("agent", rt.leta_id).metadata,
            timeout=15,
        )
        groups.extend(
            _GroupSummary(
                id=c.id,
                title=c.title,
                handle=c.handle if c.HasField("handle") else "",
            )
            for c in c_resp.conversations
            if c.type == "group"
        )
    except grpc.aio.AioRpcError:
        logger.debug("failed to list workspace groups for context", exc_info=True)

    open_hitl = await list_leta_hitl(s.db, rt.leta_id, status="pending", limit=20)
    schedules = await list_schedules(s.db, rt.leta_id)

    lines = [
        f"## Workspace: {ws_info.name} ({ws_info.id})",
        "Mounts: `/home` (~), `/shared`, `/user/<handle>`, `/chat/<handle>`, `/letfs/<storage_id>/<node_id>`",
        "",
        f"### Human Members ({len(users_list)} shown of {len(all_users)})",
        *[
            f"- {u.name} | {u.handle} | {u.role} | /chat/{u.handle} | /user/{u.handle}"
            for u in users_list
        ],
        "",
        f"### Peer Agents ({len(peers)})",
        *[
            f"- {p.name} — {p.title} | {p.handle} | /chat/{p.handle} | {p.description}"
            for p in peers
        ],
        "",
        f"### Active Groups ({len(groups[:20])})",
        *[f"- {g.title} | chat:{g.id} | /chat/{g.handle}" for g in groups[:20]],
        "",
        f"### Active Subagents ({len(subagents)})",
        *[
            f"- {a.handle} (agent:{a.handle}) | {a.name} ({a.title}) | {'running' if a.running else 'idle'}"
            for a in subagents
        ],
        "",
        f"### Pending HITL Requests ({len(open_hitl)})",
        *[f"- {h.id} | {h.type} | {h.title}" for h in open_hitl],
        "",
        f"### Active Schedules ({len(schedules)})",
        *[
            f"- {sc.id} | {sc.title} | {sc.type} | paused={sc.paused}"
            for sc in schedules[:20]
        ],
    ]
    return (
        "\n".join(lines),
        {
            "workspace": {"id": ws_info.id, "name": ws_info.name},
            "members": [u.to_json() for u in users_list],
            "letas": [p.model_dump(mode="json") for p in peers],
            "groups": [g.to_json() for g in groups[:20]],
            "subagents": [a.model_dump(mode="json") for a in subagents],
            "open_hitl": [h.model_dump(mode="json") for h in open_hitl],
            "schedules": [sc.model_dump(mode="json") for sc in schedules[:20]],
        },
    )


async def handle_list_members(
    query: str = "",
    kind: Literal["all", "user", "agent"] = "all",
    limit: int = 30,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Search and list workspace humans and peer root agents."""
    rt = runtime.context
    s = rt.services
    needle = query.strip().lstrip("@").lower()
    items: list[_MemberItem] = []

    if kind in ("all", "user"):
        for u in await _fetch_workspace_human_users(rt):
            if (
                needle
                and needle not in u.name.lower()
                and needle not in u.handle.lower()
            ):
                continue
            items.append(
                _MemberItem(
                    kind="user",
                    id=u.id,
                    name=u.name,
                    handle=u.handle,
                    role=u.role,
                )
            )

    if kind in ("all", "agent"):
        rows = await list_workspace_root_agents(s.db, rt.workspace_id)
        for r in rows:
            if (
                needle
                and needle not in r.name.lower()
                and needle not in r.handle.lower()
                and needle not in r.title.lower()
            ):
                continue
            items.append(
                _MemberItem(
                    kind="agent",
                    id=str(r.id),
                    name=r.name,
                    handle=r.handle,
                    role=r.title,
                )
            )

    page = items[:limit]
    lines = [
        f"- {it.name} | {it.handle} | {it.kind} | {it.role} | /chat/{it.handle}"
        for it in page
    ]
    return (
        "\n".join(lines) if lines else "No matching members found.",
        {"items": [it.to_json() for it in page], "total": len(items)},
    )


# --- Subagents ---


class SpawnAgentArgs(ToolArgs):
    """Input schema for ``spawn_agent``."""

    name: str = Field(
        min_length=1,
        max_length=255,
        description="Established one-word astronomical proper name (e.g. 'Orion', 'Vega').",
    )
    title: str = Field(
        min_length=1,
        max_length=255,
        description="Clear English job title (displayed as '<Name> The <Title>').",
    )
    description: str = Field(
        min_length=1,
        max_length=4000,
        description="Role and scope summary.",
    )
    task: str | None = Field(
        default=None,
        description="Self-contained initial assignment (goal, file paths, constraints, done criteria).",
    )


class AgentStatusArgs(ToolArgs):
    """Input schema for ``agent_status``."""

    agent: str = Field(
        min_length=1,
        description="Subagent handle, 'agent:<handle>', or UUID.",
    )
    activity_limit: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Recent events to include.",
    )


class StopAgentArgs(ToolArgs):
    """Input schema for ``stop_agent``."""

    agent: str = Field(
        min_length=1,
        description="Subagent handle, 'agent:<handle>', or UUID.",
    )


async def _resolve_leta_agent(
    rt: RuntimeContext,
    raw_ref: str,
    *,
    active_only: bool = True,
) -> ResolvedAgent:
    cleaned = raw_ref.strip().removeprefix("agent:").lstrip("@").strip()
    if not cleaned:
        raise ToolException("Agent handle or UUID cannot be empty.")
    row = await resolve_leta_agent(
        rt.services.db, rt.leta_id, cleaned, active_only=active_only
    )
    if row is not None:
        return row

    agents = await list_leta_agents(rt.services.db, rt.leta_id)
    active = [a for a in agents if a.state == "active"]
    if active:
        opts = ", ".join(f"{a.handle} ({a.name} — {a.title})" for a in active[:10])
        raise ToolException(
            f"Agent {raw_ref!r} not found. Active agents in this Leta: {opts}"
        )
    raise ToolException(f"Agent {raw_ref!r} not found (no active agents in this Leta).")


async def handle_spawn_agent(
    name: str,
    title: str,
    description: str,
    task: str | None = None,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Spawn a background subagent and optionally dispatch its initial task."""
    rt = runtime.context
    sub_cfg = rt.services.settings.subagents
    try:
        created = await spawn_subagent(
            db=rt.services.db,
            inbox=rt.services.inbox,
            activity=rt.emitter,
            parent_agent_id=rt.agent_id,
            name=name,
            title=title,
            description=description,
            task=task or "",
            max_depth=sub_cfg.max_depth,
            max_active_per_leta=sub_cfg.max_active_per_leta,
            idempotency_key=f"spawn:{idempotency_key(runtime)}",
        )
    except (ValueError, LookupError) as exc:
        raise ToolException(str(exc)) from None
    status_label = "running" if task else "idle"
    guidance = (
        " It works asynchronously in the background and will report back to your <inbox> when done. "
        "Do not poll agent_status repeatedly; continue independent work or end your turn."
        if task
        else f" Send it a task via send_message(to={created.handle!r}, content=...)."
    )
    return (
        (
            f"Spawned {created.name} The {created.title} "
            f"(handle: {created.handle}, address: agent:{created.handle}, id: {created.id}, status: {status_label}).{guidance}"
        ),
        {
            "agent_id": str(created.id),
            "handle": created.handle,
            "name": created.name,
            "title": created.title,
            "status": status_label,
        },
    )


async def handle_list_agents(
    *, runtime: ToolRuntime[RuntimeContext, AgentState]
) -> ToolResult:
    """List active agents in the current Leta tree."""
    rt = runtime.context
    agents = await list_leta_agents(rt.services.db, rt.leta_id)
    active = [a for a in agents if a.state == "active"]
    lines = [
        f"- {a.handle} (agent:{a.handle}) | {a.name} The {a.title} | "
        f"{'running' if a.running else 'idle'} | {a.description}"
        for a in active
    ]
    return (
        "\n".join(lines) if lines else "No active agents.",
        {"agents": [a.model_dump(mode="json") for a in active]},
    )


def _clip_inline(text: str, limit: int = 200) -> str:
    single = " ".join(text.split())
    return single if len(single) <= limit else single[: limit - 1] + "…"


def format_activity_event_summary(event_type: str, data: Mapping[str, JSON]) -> str:
    """Format a subagent activity_events payload into clean readable text (no Python dict repr)."""
    try:
        match event_type:
            case "activity.message":
                ev = MessageEventData.model_validate(data)
                text = (ev.text or ev.reasoning or "").strip()
                return _clip_inline(text) if text else "(empty message)"
            case "activity.tool_call":
                ev = ToolCallEventData.model_validate(data)
                args_json = json.dumps(ev.args, ensure_ascii=False, default=str)
                return _clip_inline(f"{ev.name}({args_json})")
            case "activity.tool_result":
                ev = ToolResultEventData.model_validate(data)
                preview = (ev.preview or ev.content).strip()
                return _clip_inline(
                    f"{ev.name} [{ev.status}]: {preview}"
                    if preview
                    else f"{ev.name} [{ev.status}]"
                )
            case "activity.agent_message":
                ev = AgentMessageEventData.model_validate(data)
                sender_lbl = (
                    (ev.sender.handle or ev.sender.name)
                    if ev.sender is not None
                    else ""
                )
                prefix = f"from {sender_lbl}: " if sender_lbl else ""
                return _clip_inline(prefix + ev.content.strip())
            case "activity.inbox_received":
                ev = InboxReceivedEventData.model_validate(data)
                if ev.items:
                    preview = ev.items[-1].preview
                    return _clip_inline(
                        f"{len(ev.items)} item(s): {preview}"
                        if preview
                        else f"{len(ev.items)} item(s)"
                    )
                return "inbox batch"
            case "run.finished":
                ev = RunFinishedEventData.model_validate(data)
                err = (ev.error_code or "").strip()
                return _clip_inline(f"{ev.status}: {err}" if err else ev.status)
            case _:
                pass
    except ValidationError:
        pass
    return _clip_inline(json.dumps(dict(data), ensure_ascii=False, default=str))


async def handle_agent_status(
    agent: str,
    activity_limit: int = 3,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Inspect a subagent's run state and recent activity summaries."""
    rt = runtime.context
    row = await _resolve_leta_agent(rt, agent, active_only=False)
    events = await list_recent_activity(rt.services.db, row.id, activity_limit)
    st = "running" if row.running else row.state
    lines = [f"{row.handle} (agent:{row.handle}, {row.name} — {row.title}): {st}"]
    recent: list[dict[str, JSON]] = []
    for ev in reversed(events):
        summary = format_activity_event_summary(ev.type, ev.data)
        lines.append(f"  - [{ev.seq}] {ev.type}: {summary}")
        recent.append({"seq": ev.seq, "type": ev.type})
    return (
        "\n".join(lines),
        {
            "agent_id": str(row.id),
            "status": st,
            "recent_activity": recent,
        },
    )


async def handle_stop_agent(
    agent: str,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Stop a subagent and all of its descendant subagents."""
    rt = runtime.context
    row = await _resolve_leta_agent(rt, agent, active_only=True)
    if row.parent_agent_id is None:
        raise ToolException("Cannot stop the Root Leta.")
    stopped = await stop_agent_tree(
        db=rt.services.db,
        temporal=rt.services.temporal,
        activity=rt.emitter,
        agent_id=row.id,
        include_self=True,
    )
    children = max(0, len(stopped) - 1)
    return (
        f"Stopped {row.handle} (and {children} child subagent(s)).",
        {"agent_id": str(row.id), "handle": row.handle, "stopped_children": children},
    )


# --- HITL ---


class HitlAskArgs(ToolArgs):
    """Input schema for ``hitl_ask``."""

    recipient: str = Field(
        min_length=1,
        description="Human handle, UUID, or full display name.",
    )
    title: str = Field(min_length=1, max_length=255)
    questions: list[Question] = Field(min_length=1, max_length=20)
    expires_in_seconds: int = Field(
        default=86400,
        ge=60,
        le=604800,
        description="Expiry in seconds (default 86400 = 24h).",
    )


class HitlRequestAccessArgs(ToolArgs):
    """Input schema for ``hitl_request_access``."""

    recipient: str = Field(
        min_length=1,
        description="Human handle, UUID, or full display name.",
    )
    title: str = Field(min_length=1, max_length=255)
    reason: str = Field(
        min_length=1,
        max_length=2000,
        description="Which files in /user/<handle> are needed and why in-place access is required.",
    )
    role: Literal["viewer", "editor"] = "viewer"
    expires_in_seconds: int = Field(
        default=86400,
        ge=60,
        le=604800,
        description="Expiry in seconds (default 86400 = 24h).",
    )


class HitlCancelArgs(ToolArgs):
    """Input schema for ``hitl_cancel``."""

    request_id: UUID


class HitlListArgs(ToolArgs):
    """Input schema for ``hitl_list``."""

    request_id: UUID | None = None
    status: (
        Literal["pending", "answered", "accepted", "denied", "cancelled", "expired"]
        | None
    ) = None


async def _resolve_human_recipient(
    rt: RuntimeContext, recipient: str
) -> tuple[UUID, str]:
    cleaned = recipient.strip()
    for prefix in ("chat:user:", "user:"):
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    cleaned = cleaned.lstrip("@").strip()
    if not cleaned:
        raise ToolException("Recipient must be a non-empty user handle, UUID, or name.")

    try:
        uid = UUID(cleaned)
        return uid, str(uid)
    except ValueError:
        pass

    # 1. Exact handle lookup via PlatformInternal
    try:
        u = await rt.services.platform_internal.GetUserByHandle(
            plat_int_pb.UserHandleRequest(handle=cleaned.lower()), timeout=15
        )
        return UUID(u.id), str(u.handle)
    except grpc.aio.AioRpcError as exc:
        if exc.code() != grpc.StatusCode.NOT_FOUND:
            raise

    # 2. Fallback: unique display name match in workspace members
    users = await _fetch_workspace_human_users(rt)
    low = cleaned.lower()
    name_matches = [u for u in users if u.name.strip().lower() == low]
    if len(name_matches) == 1:
        return UUID(name_matches[0].id), name_matches[0].handle
    if len(name_matches) > 1:
        opts = ", ".join(f"{u.handle} ({u.name})" for u in name_matches)
        raise ToolException(
            f"Recipient {recipient!r} matches multiple users. Specify a handle: {opts}"
        )

    if users:
        opts = ", ".join(f"{u.handle} ({u.name})" for u in users[:15])
        raise ToolException(
            f"Workspace user {recipient!r} not found. Available users: {opts}"
        )
    raise ToolException(f"Workspace user {recipient!r} not found.")


async def handle_hitl_ask(
    recipient: str,
    title: str,
    questions: list[Question],
    expires_in_seconds: int = 86400,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Open an asynchronous HITL question form for a workspace user."""
    rt = runtime.context
    recipient_id, recipient_label = await _resolve_human_recipient(rt, recipient)
    req_id = uuid4()
    expires = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
    payload = build_ask_form(questions)
    await start_hitl_workflow(
        temporal=rt.services.temporal,
        orchestration_queue=rt.services.queues.orchestration,
        request=OpenHitlInput(
            id=req_id,
            requester_agent_id=rt.agent_id,
            recipient_user_id=recipient_id,
            type="ask",
            title=title,
            payload=payload,
            expires_at=expires,
        ),
    )
    return (
        (
            f"Opened HITL question form {req_id} ('{title}') for {recipient_label}. "
            "Their response will arrive asynchronously in your <inbox>; continue independent work or end your turn without polling."
        ),
        {"request_id": str(req_id), "status": "pending", "type": "ask"},
    )


async def handle_hitl_request_access(
    recipient: str,
    title: str,
    reason: str,
    role: Literal["viewer", "editor"] = "viewer",
    expires_in_seconds: int = 86400,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Request viewer or editor access to a human user's personal storage."""
    rt = runtime.context
    recipient_id, recipient_label = await _resolve_human_recipient(rt, recipient)
    req_id = uuid4()
    expires = datetime.now(UTC) + timedelta(seconds=expires_in_seconds)
    await start_hitl_workflow(
        temporal=rt.services.temporal,
        orchestration_queue=rt.services.queues.orchestration,
        request=OpenHitlInput(
            id=req_id,
            requester_agent_id=rt.agent_id,
            recipient_user_id=recipient_id,
            type="approval",
            title=title,
            payload=ApprovalPayload(role=role, reason=reason),
            expires_at=expires,
        ),
    )
    return (
        (
            f"Opened HITL storage access request {req_id} ({role}) for {recipient_label}. "
            "The decision will arrive asynchronously in your <inbox>; continue independent work or end your turn without polling."
        ),
        {"request_id": str(req_id), "status": "pending", "type": "approval"},
    )


async def handle_hitl_cancel(
    request_id: UUID,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Cancel a pending HITL request."""
    rt = runtime.context
    cancelled = await cancel_hitl_workflow(
        temporal=rt.services.temporal,
        request_id=request_id,
        actor_id=rt.agent_id,
    )
    if not cancelled:
        pending = await list_leta_hitl(
            rt.services.db, rt.leta_id, status="pending", limit=10
        )
        if pending:
            opts = ", ".join(f"{h.id} ({h.title})" for h in pending)
            raise ToolException(
                f"Active HITL request {request_id} not found (may already be resolved). Pending requests: {opts}"
            )
        raise ToolException(
            f"Active HITL request {request_id} not found (no pending HITL requests)."
        )
    return (
        f"Cancelled HITL request {request_id}.",
        {"request_id": str(request_id), "status": "cancelled"},
    )


async def handle_hitl_list(
    request_id: UUID | None = None,
    status: Literal["pending", "answered", "accepted", "denied", "cancelled", "expired"]
    | None = None,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """List HITL requests or inspect a single request by ID."""
    rt = runtime.context
    if request_id is not None:
        try:
            item = await get_hitl(rt.services.db, request_id)
        except LookupError:
            items = await list_leta_hitl(rt.services.db, rt.leta_id, limit=10)
            if items:
                opts = ", ".join(f"{h.id} ({h.title}, {h.status})" for h in items)
                raise ToolException(
                    f"HITL request {request_id} not found. Recent requests: {opts}"
                ) from None
            raise ToolException(f"HITL request {request_id} not found.") from None
        detail_lines = [f"HITL {item.id} | {item.type} | {item.status} | {item.title}"]
        resp_text = format_hitl_response(item.payload, item.response)
        if resp_text:
            detail_lines.append(resp_text)
        outcome_text = format_hitl_outcome(item.outcome)
        if outcome_text:
            detail_lines.append(f"Outcome: {outcome_text}")
        return ("\n".join(detail_lines), {"request": item.model_dump(mode="json")})
    items = await list_leta_hitl(
        rt.services.db,
        rt.leta_id,
        requester_agent_id=None if rt.is_root else rt.agent_id,
        status=status,
    )
    if not items:
        return "No HITL requests found.", {"items": []}
    lines = [f"- {h.id} | {h.type} | {h.status} | {h.title}" for h in items]
    return "\n".join(lines), {"items": [h.model_dump(mode="json") for h in items]}


# --- Schedules ---

_DURATION_PART_RE = re.compile(
    r"(\d+)\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|wks?|w)(?![a-zA-Z])",
    re.IGNORECASE,
)
_DURATION_UNITS: MappingProxyType[str, int] = MappingProxyType(
    {
        "s": 1,
        "sec": 1,
        "secs": 1,
        "second": 1,
        "seconds": 1,
        "m": 60,
        "min": 60,
        "mins": 60,
        "minute": 60,
        "minutes": 60,
        "h": 3600,
        "hr": 3600,
        "hrs": 3600,
        "hour": 3600,
        "hours": 3600,
        "d": 86400,
        "day": 86400,
        "days": 86400,
        "w": 604800,
        "wk": 604800,
        "wks": 604800,
        "week": 604800,
        "weeks": 604800,
    }
)
_REPEAT_SHORTHANDS: MappingProxyType[str, str] = MappingProxyType(
    {
        "@hourly": "0 * * * *",
        "hourly": "0 * * * *",
        "@daily": "0 9 * * *",
        "daily": "0 9 * * *",
        "@weekly": "0 9 * * 1",
        "weekly": "0 9 * * 1",
        "@monthly": "0 9 1 * *",
        "monthly": "0 9 1 * *",
        "weekdays": "0 9 * * 1-5",
    }
)
_TIMEZONE_ALIASES: MappingProxyType[str, str] = MappingProxyType(
    {
        "gmt": "UTC",
        "utc+0": "UTC",
        "z": "UTC",
        "utc+7": "Asia/Ho_Chi_Minh",
        "gmt+7": "Asia/Ho_Chi_Minh",
        "ict": "Asia/Ho_Chi_Minh",
        "est": "America/New_York",
        "edt": "America/New_York",
        "et": "America/New_York",
        "cst": "America/Chicago",
        "cdt": "America/Chicago",
        "ct": "America/Chicago",
        "mst": "America/Denver",
        "mdt": "America/Denver",
        "mt": "America/Denver",
        "pst": "America/Los_Angeles",
        "pdt": "America/Los_Angeles",
        "pt": "America/Los_Angeles",
        "cet": "Europe/Paris",
        "cest": "Europe/Paris",
        "bst": "Europe/London",
        "jst": "Asia/Tokyo",
        "kst": "Asia/Seoul",
        "sgt": "Asia/Singapore",
    }
)


def normalize_timezone(tz: str) -> str:
    """Validate and resolve common timezone aliases into a canonical IANA zone name."""
    cleaned = tz.strip()
    if not cleaned:
        return "UTC"
    mapped = _TIMEZONE_ALIASES.get(cleaned.lower(), cleaned)
    try:
        ZoneInfo(mapped)
    except ZoneInfoNotFoundError:
        raise ValueError(
            f"Invalid timezone {tz!r}. Use an IANA timezone name such as 'UTC', 'Asia/Ho_Chi_Minh', or 'America/New_York'."
        ) from None
    return mapped


def _parse_duration_seconds(raw: str) -> int:
    text = raw.strip()
    if not text:
        raise ValueError("duration cannot be empty")
    pos = 0
    total = 0
    for m in _DURATION_PART_RE.finditer(text):
        if text[pos : m.start()].strip():
            raise ValueError(
                f"invalid duration {raw!r}; examples: '30s', '15m', '2h', '1d'"
            )
        total += int(m.group(1)) * _DURATION_UNITS[m.group(2).lower()]
        pos = m.end()
    if pos == 0 or text[pos:].strip():
        raise ValueError(
            f"invalid duration {raw!r}; examples: '30s', '15m', '2h', '1d'"
        )
    if total <= 0:
        raise ValueError(f"duration must be positive, got {raw!r}")
    return total


def _try_duration_seconds(raw: str) -> int | None:
    try:
        return _parse_duration_seconds(raw)
    except ValueError:
        return None


def _parse_iso_datetime(raw: str, tz_name: str) -> datetime:
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt


def parse_schedule_timing(
    *,
    run_at: str | None,
    repeat: str | None,
    timezone: str = "UTC",
    ends_at: str | None = None,
) -> Timing:
    """Parse concise schedule tool inputs (`run_at` or `repeat`) into canonical `Timing`."""
    tz = normalize_timezone(timezone)
    if run_at is not None and repeat is not None:
        raise ValueError(
            "specify either run_at (one-shot) or repeat (recurring), not both"
        )
    if run_at is None and repeat is None:
        raise ValueError("specify either run_at (one-shot) or repeat (recurring)")

    ends_dt = _parse_iso_datetime(ends_at, tz) if ends_at is not None else None

    if run_at is not None:
        val = run_at.strip()
        if val.startswith("+"):
            secs = _parse_duration_seconds(val[1:])
            return Timing(after_seconds=secs, timezone=tz)
        if val.lower().startswith("in "):
            secs = _parse_duration_seconds(val[3:])
            return Timing(after_seconds=secs, timezone=tz)
        bare_secs = _try_duration_seconds(val)
        if bare_secs is not None:
            return Timing(after_seconds=bare_secs, timezone=tz)
        return Timing(at=_parse_iso_datetime(val, tz), timezone=tz)

    if repeat is None:
        raise ValueError("specify either run_at (one-shot) or repeat (recurring)")
    rep = repeat.strip()
    if rep.lower().startswith("every "):
        secs = _parse_duration_seconds(rep[6:])
        return Timing(every_seconds=secs, ends_at=ends_dt, timezone=tz)

    shorthand = _REPEAT_SHORTHANDS.get(rep.lower())
    if shorthand is not None:
        rep = shorthand
    else:
        bare_secs = _try_duration_seconds(rep)
        if bare_secs is not None:
            return Timing(every_seconds=bare_secs, ends_at=ends_dt, timezone=tz)

    parts = rep.split()
    if len(parts) != 5:
        raise ValueError(
            f"invalid repeat {repeat!r}; expected 5-field cron (e.g. '0 9 * * 1-5'), "
            "'every <duration>' (e.g. 'every 15m'), or shorthand ('hourly', 'daily', 'weekdays', 'weekly')"
        )
    if all(p == "*" for p in parts):
        return Timing(every_seconds=60, ends_at=ends_dt, timezone=tz)
    return Timing(cron=" ".join(parts), ends_at=ends_dt, timezone=tz)


class ScheduleCreateArgs(ToolArgs):
    """Input schema for ``schedule_create``."""

    model_config = ConfigDict(
        extra="forbid", arbitrary_types_allowed=True, str_strip_whitespace=True
    )
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(
        min_length=1,
        max_length=32000,
        description="Self-contained alarm instructions delivered to <inbox> when fired.",
    )
    run_at: str | None = Field(
        default=None,
        description="One-shot: ISO-8601 or relative ('+30m', 'in 2h'). Exclusive with repeat.",
    )
    repeat: str | None = Field(
        default=None,
        description="Recurring: 5-field cron ('0 9 * * 1-5'), 'every 15m', or 'hourly'/'daily'/'weekdays'/'weekly'/'monthly'. Exclusive with run_at.",
    )
    timezone: str = Field(
        default="UTC",
        description="IANA timezone (e.g. 'Asia/Ho_Chi_Minh').",
    )
    ends_at: str | None = Field(
        default=None,
        description="ISO-8601 end time for recurring schedule.",
    )
    target_agent: str | None = Field(
        default=None,
        description="Subagent handle/UUID to receive the alarm (defaults to self).",
    )


class ScheduleUpdateArgs(ToolArgs):
    """Input schema for ``schedule_update``."""

    model_config = ConfigDict(
        extra="forbid", arbitrary_types_allowed=True, str_strip_whitespace=True
    )
    schedule_id: UUID
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=32000)
    run_at: str | None = Field(
        default=None,
        description="One-shot: ISO-8601 or '+30m'. Exclusive with repeat.",
    )
    repeat: str | None = Field(
        default=None,
        description="Recurring: 5-field cron, 'every 15m', or 'daily'/'weekdays'. Exclusive with run_at.",
    )
    timezone: str = Field(default="UTC", description="IANA timezone.")
    ends_at: str | None = Field(
        default=None, description="ISO-8601 end time for recurring schedule."
    )
    target_agent: str | None = Field(
        default=None, description="Target agent handle/UUID."
    )
    paused: bool | None = None


class ScheduleDeleteArgs(ToolArgs):
    """Input schema for ``schedule_delete``."""

    schedule_id: UUID


class ScheduleListArgs(ToolArgs):
    """Input schema for ``schedule_list``."""

    schedule_id: UUID | None = None


async def _resolve_target_agent(
    rt: RuntimeContext, target_agent: str | None
) -> UUID | None:
    if target_agent is None or not target_agent.strip():
        return None
    row = await _resolve_leta_agent(rt, target_agent, active_only=True)
    return row.id


async def _schedule_not_found_error(
    rt: RuntimeContext, schedule_id: UUID
) -> ToolException:
    items = await list_schedules(rt.services.db, rt.leta_id)
    if items:
        opts = ", ".join(f"{sc.id} ({sc.title})" for sc in items[:10])
        return ToolException(
            f"Schedule {schedule_id} not found. Active schedules: {opts}"
        )
    return ToolException(
        f"Schedule {schedule_id} not found (no active schedules in this Leta)."
    )


def _format_upcoming(upcoming: list[str]) -> str:
    return ", ".join(upcoming) if upcoming else "none"


async def handle_schedule_create(
    title: str,
    content: str,
    *,
    run_at: str | None = None,
    repeat: str | None = None,
    timezone: str = "UTC",
    ends_at: str | None = None,
    target_agent: str | None = None,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Create a one-shot or recurring schedule delivering alarms to <inbox>."""
    rt = runtime.context
    try:
        timing = parse_schedule_timing(
            run_at=run_at,
            repeat=repeat,
            timezone=timezone,
            ends_at=ends_at,
        )
    except ValueError as exc:
        raise ToolException(str(exc)) from None
    target_id = await _resolve_target_agent(rt, target_agent)
    created = await create_schedule(
        db=rt.services.db,
        temporal=rt.services.temporal,
        orchestration_queue=rt.services.queues.orchestration,
        activity=rt.emitter,
        leta_id=rt.leta_id,
        creator_agent_id=rt.agent_id,
        target_agent_id=target_id or rt.agent_id,
        title=title,
        content=content,
        timing=timing,
        paused=False,
        request_id=idempotency_key(runtime),
    )
    return (
        f"Created schedule {created.id} ('{created.title}', type={created.type}, tz={timing.timezone}). Upcoming: {_format_upcoming(created.upcoming)}",
        {"schedule_id": str(created.id), "schedule": created.model_dump(mode="json")},
    )


async def handle_schedule_update(
    schedule_id: UUID,
    *,
    title: str | None = None,
    content: str | None = None,
    run_at: str | None = None,
    repeat: str | None = None,
    timezone: str = "UTC",
    ends_at: str | None = None,
    target_agent: str | None = None,
    paused: bool | None = None,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Update an existing schedule's timing, content, target agent, or pause state."""
    rt = runtime.context
    has_timing = run_at is not None or repeat is not None
    try:
        timing = (
            parse_schedule_timing(
                run_at=run_at,
                repeat=repeat,
                timezone=timezone,
                ends_at=ends_at,
            )
            if has_timing
            else None
        )
    except ValueError as exc:
        raise ToolException(str(exc)) from None
    target_id = await _resolve_target_agent(rt, target_agent)
    try:
        updated = await update_schedule(
            db=rt.services.db,
            temporal=rt.services.temporal,
            orchestration_queue=rt.services.queues.orchestration,
            activity=rt.emitter,
            leta_id=rt.leta_id,
            schedule_id=schedule_id,
            title=title,
            content=content,
            target_agent_id=target_id,
            timing=timing,
            paused=paused,
        )
    except LookupError:
        raise await _schedule_not_found_error(rt, schedule_id) from None
    return (
        f"Updated schedule {updated.id} ('{updated.title}'). Upcoming: {_format_upcoming(updated.upcoming)}",
        {"schedule_id": str(updated.id), "schedule": updated.model_dump(mode="json")},
    )


async def handle_schedule_delete(
    schedule_id: UUID,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Delete an existing schedule by ID."""
    rt = runtime.context
    try:
        await delete_schedule(
            db=rt.services.db,
            temporal=rt.services.temporal,
            activity=rt.emitter,
            leta_id=rt.leta_id,
            schedule_id=schedule_id,
        )
    except LookupError:
        raise await _schedule_not_found_error(rt, schedule_id) from None
    return (
        f"Deleted schedule {schedule_id}.",
        {"schedule_id": str(schedule_id), "status": "deleted"},
    )


async def handle_schedule_list(
    schedule_id: UUID | None = None,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """List active schedules or inspect a single schedule by ID."""
    rt = runtime.context
    if schedule_id is not None:
        try:
            item = await get_schedule(
                rt.services.db, rt.services.temporal, rt.leta_id, schedule_id
            )
        except LookupError:
            raise await _schedule_not_found_error(rt, schedule_id) from None
        return (
            f"Schedule {item.id} | {item.title} | {item.type} | paused={item.paused}\nUpcoming: {_format_upcoming(item.upcoming)}\nContent: {item.content}",
            {"schedule": item.model_dump(mode="json")},
        )
    items = await list_schedules(
        rt.services.db,
        rt.leta_id,
        target_agent_id=None if rt.is_root else rt.agent_id,
    )
    if not items:
        return "No active schedules.", {"items": []}
    lines = [f"- {sc.id} | {sc.title} | {sc.type} | paused={sc.paused}" for sc in items]
    return "\n".join(lines), {"items": [sc.model_dump(mode="json") for sc in items]}


# --- Optional Todo (opt-in flag tools.todo: false) ---


class TodoItem(BaseModel):
    """Single checklist entry in the optional ``todowrite`` scratchpad."""

    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1)
    status: Literal["pending", "in_progress", "completed", "cancelled"]


class TodoWriteArgs(ToolArgs):
    """Input schema for ``todowrite``."""

    todos: list[TodoItem]


async def handle_todowrite(
    todos: list[TodoItem],
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Replace the scratchpad checklist and return a completion summary."""
    _ = runtime
    total = len(todos)
    done = sum(1 for t in todos if t.status == "completed")
    in_prog = [t.content for t in todos if t.status == "in_progress"]
    pending = sum(1 for t in todos if t.status == "pending")
    summary = f"Todos updated: {done}/{total} completed, {len(in_prog)} in progress, {pending} pending."
    if in_prog:
        summary += f' In progress: "{in_prog[0]}"'
    return summary, {"todos": [t.model_dump() for t in todos]}


def build_domain_tools(
    *,
    is_root: bool,
    enable_subagents: bool = True,
    enable_hitl: bool = True,
    enable_schedule: bool = True,
    enable_todo: bool = False,
) -> list[BaseTool]:
    """Build workspace, subagent, HITL, schedule, and optional todo tools."""
    tools: list[BaseTool] = [
        make_tool(
            name="get_context",
            description=(
                "Get a snapshot of the workspace: human members, peer agents, group chats, "
                "active subagents, pending HITL, and active schedules."
            ),
            args_schema=EmptyArgs,
            coroutine=handle_get_context,
        )
    ]
    if is_root:
        tools.append(
            make_tool(
                name="list_members",
                description="Search/list workspace humans and peer Root Letas with their handles and /chat/<handle> mounts.",
                args_schema=ListMembersArgs,
                coroutine=handle_list_members,
            )
        )
    if enable_subagents:
        tools.extend(
            [
                make_tool(
                    name="spawn_agent",
                    description=(
                        "Spawn a subagent to work asynchronously in the background. "
                        "Do small direct tasks yourself; spawn only when parallel work, deep research, "
                        "or independent verification materially helps. Give each deliverable one active owner. "
                        "Results arrive in <inbox> — do not poll agent_status. "
                        "Review outputs before reporting to users and stop finished subagents with stop_agent."
                    ),
                    args_schema=SpawnAgentArgs,
                    coroutine=handle_spawn_agent,
                ),
                make_tool(
                    name="list_agents",
                    description="List active agents in this Leta tree with handles and running/idle status.",
                    args_schema=EmptyArgs,
                    coroutine=handle_list_agents,
                ),
                make_tool(
                    name="agent_status",
                    description="Inspect a subagent's state and recent activity. Use sparingly; do not poll in a loop while waiting for a report.",
                    args_schema=AgentStatusArgs,
                    coroutine=handle_agent_status,
                ),
                make_tool(
                    name="stop_agent",
                    description="Stop a finished or unneeded subagent (and its descendants).",
                    args_schema=StopAgentArgs,
                    coroutine=handle_stop_agent,
                ),
            ]
        )
    if enable_hitl:
        tools.extend(
            [
                make_tool(
                    name="hitl_ask",
                    description=(
                        "Send a structured Human-in-the-Loop question form to a workspace human when missing answers "
                        "materially affect correctness, scope, or decisions. Responses arrive asynchronously in <inbox> — "
                        "continue independent work without polling."
                    ),
                    args_schema=HitlAskArgs,
                    coroutine=handle_hitl_ask,
                ),
                make_tool(
                    name="hitl_request_access",
                    description=(
                        "Request viewer/editor access to a human's Personal storage (/user/<handle>). "
                        "Ask them to share a copy in chat when sufficient; use this only when in-place access is required. "
                        "Decision arrives asynchronously in <inbox> without polling."
                    ),
                    args_schema=HitlRequestAccessArgs,
                    coroutine=handle_hitl_request_access,
                ),
                make_tool(
                    name="hitl_cancel",
                    description="Cancel a pending HITL request.",
                    args_schema=HitlCancelArgs,
                    coroutine=handle_hitl_cancel,
                ),
                make_tool(
                    name="hitl_list",
                    description="List HITL requests or inspect one in detail by request_id.",
                    args_schema=HitlListArgs,
                    coroutine=handle_hitl_list,
                ),
            ]
        )
    if enable_schedule:
        tools.extend(
            [
                make_tool(
                    name="schedule_create",
                    description=(
                        "Create a one-shot (run_at) or recurring (repeat) alarm delivered to <inbox>. "
                        "Set alarms early enough for deadlines, clarify time zones when commitments depend on them, "
                        "and make content self-contained (task, sources, and who to notify via send_message)."
                    ),
                    args_schema=ScheduleCreateArgs,
                    coroutine=handle_schedule_create,
                ),
                make_tool(
                    name="schedule_update",
                    description="Update an existing schedule's timing, content, target, or paused state.",
                    args_schema=ScheduleUpdateArgs,
                    coroutine=handle_schedule_update,
                ),
                make_tool(
                    name="schedule_delete",
                    description="Delete a schedule once fulfilled or cancelled.",
                    args_schema=ScheduleDeleteArgs,
                    coroutine=handle_schedule_delete,
                ),
                make_tool(
                    name="schedule_list",
                    description="List active schedules or inspect one (with full content and upcoming fire times) by schedule_id.",
                    args_schema=ScheduleListArgs,
                    coroutine=handle_schedule_list,
                ),
            ]
        )
    if enable_todo:
        tools.append(
            make_tool(
                name="todowrite",
                description="Scratchpad checklist for multi-step tasks (send full replacement list; keep at most one item in_progress).",
                args_schema=TodoWriteArgs,
                coroutine=handle_todowrite,
            )
        )
    return tools
