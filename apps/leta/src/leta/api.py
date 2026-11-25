import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from typing import Annotated, Literal, cast
from uuid import UUID

import grpc
import uvicorn
from authzed.api.v1 import (
    Consistency,
    Cursor,
    ReadRelationshipsRequest,
    ReadRelationshipsResponse,
    RelationshipFilter,
    SubjectFilter,
)
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from openlet_sdk.config import JSON, load
from openlet_sdk.telemetry import initialize
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from psycopg import errors
from psycopg.types.json import Jsonb
from pydantic import Field
from sse_starlette import EventSourceResponse, ServerSentEvent
from temporalio.client import WorkflowUpdateFailedError
from temporalio.service import RPCError, RPCStatusCode

from . import (
    activity,
    box_views,
    boxes,
    conversations,
    events,
    file_refs,
    hitl,
    messages,
    reactions,
    schedules,
    sidebar,
    views,
)
from .agents import (
    ConfigureAgent,
    CreateLeta,
    Input,
    LetaRequest,
    gate,
    get_agent,
    json_row,
    stable,
)
from .auth import Actor, human, relationship
from .boxes import BoxCreation, CreateBox
from .config import Services, connect, validate
from .db import Row
from .jobs.resources import ResourceOperation
from .messages import Message, SendMessage
from .worker import deliver, operation, submit_hitl, submit_schedule


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    config = load()
    validate(config)
    shutdown = initialize("openlet-leta-api", config["runtime"], config["telemetry"])
    PsycopgInstrumentor().instrument()
    RedisInstrumentor().instrument()  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
    try:
        async with connect(config) as services:
            app.state.services = services
            yield
    finally:
        shutdown()


app = FastAPI(title="Openlet Leta", version="1", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app, excluded_urls="/health,/ready")
base = "/v1/workspaces/{workspace_id}/letas"
root_path = base + "/{leta_id}"


def services(request: Request) -> Services:
    return cast(Services, request.app.state.services)


type Service = Annotated[Services, Depends(services)]
type User = Annotated[Actor, Depends(human)]


async def root(workspace_id: UUID, leta_id: UUID, s: Service, actor: User) -> Row:
    row = await get_agent(s.db, leta_id)
    if row["workspace_id"] != workspace_id or row["box_id"] is not None:
        raise HTTPException(404, "Leta not found")
    return row


type Root = Annotated[Row, Depends(root)]


async def usable(leta_id: UUID, s: Service, actor: User, resource: Root) -> None:
    await s.auth.require(actor, "agent", leta_id, "use")


async def manageable(leta_id: UUID, s: Service, actor: User, resource: Root) -> None:
    await s.auth.require(actor, "agent", leta_id, "manage")


async def child(s: Services, root: UUID, id: UUID) -> Row:
    row = await get_agent(s.db, id)
    if row["leta_id"] != root:
        raise HTTPException(404, "agent not found")
    return row


@app.exception_handler(ValueError)
async def invalid(request: Request, error: ValueError) -> JSONResponse:
    return JSONResponse({"detail": str(error)}, status_code=422)


@app.exception_handler(LookupError)
async def missing(request: Request, error: LookupError) -> JSONResponse:
    return JSONResponse({"detail": str(error)}, status_code=404)


@app.exception_handler(PermissionError)
async def forbidden(request: Request, error: PermissionError) -> JSONResponse:
    return JSONResponse({"detail": str(error)}, status_code=403)


@app.exception_handler(errors.UniqueViolation)
async def conflict(request: Request, error: errors.UniqueViolation) -> JSONResponse:
    return JSONResponse({"detail": "resource already exists"}, status_code=409)


@app.exception_handler(grpc.aio.AioRpcError)
async def rpc_failed(request: Request, error: grpc.aio.AioRpcError) -> JSONResponse:
    codes = {
        grpc.StatusCode.NOT_FOUND: 404,
        grpc.StatusCode.PERMISSION_DENIED: 403,
        grpc.StatusCode.INVALID_ARGUMENT: 422,
        grpc.StatusCode.ALREADY_EXISTS: 409,
    }
    return JSONResponse(
        {"detail": error.details()}, status_code=codes.get(error.code(), 503)
    )


@app.exception_handler(RPCError)
async def temporal_failed(request: Request, error: RPCError) -> JSONResponse:
    return JSONResponse(
        {"detail": "execution unavailable; retry with the same request ID"},
        status_code=404 if error.status == RPCStatusCode.NOT_FOUND else 503,
    )


@app.exception_handler(WorkflowUpdateFailedError)
async def admission_failed(
    request: Request, error: WorkflowUpdateFailedError
) -> JSONResponse:
    logging.getLogger(__name__).warning("Temporal admission rejected", exc_info=error)
    return JSONResponse(
        {"detail": "request was not admitted; retry with the same request ID"},
        status_code=409,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready(s: Service) -> dict[str, str]:
    async with s.db.connection() as conn:
        await conn.execute("SELECT 1 FROM agents LIMIT 1")
    await s.redis.ping()  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
    return {"status": "ok"}


@app.get(base + "/models")
async def list_models(workspace_id: UUID, s: Service, actor: User) -> JSON:
    await s.auth.require(actor, "workspace", workspace_id, "participate")
    return {
        "models": [
            {
                "model_id": item.model_id,
                "reasoning_efforts": list(item.reasoning_efforts),
            }
            for item in (await s.models.catalog()).values()
        ]
    }


sidebar_path = base + "/sidebar"


@app.exception_handler(sidebar.StaleLayout)
async def stale_layout(request: Request, error: sidebar.StaleLayout) -> JSONResponse:
    return JSONResponse(
        {"detail": "Sidebar changed in another session. Reload and try again."},
        status_code=409,
    )


@app.get(sidebar_path)
async def get_sidebar(workspace_id: UUID, s: Service, actor: User) -> JSON:
    await s.auth.require(actor, "workspace", workspace_id, "participate")
    result = await sidebar.read(s.db, workspace_id, actor.id)
    layout = sidebar.Layout.model_validate(result["layout"])
    ids = set(layout.pins) | set(layout.order) | set(layout.assignments)
    async with s.db.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT id FROM letas WHERE workspace_id=%s AND id=ANY(%s) AND state NOT IN ('deleting','archived')",
                (workspace_id, list(ids)),
            )
        ).fetchall()
    allowed = (
        await s.auth.allowed_many(
            actor, "agent", [cast(UUID, r["id"]) for r in rows], "use"
        )
        if rows
        else set[UUID]()
    )
    layout.pins = [id for id in layout.pins if id in allowed]
    layout.order = [id for id in layout.order if id in allowed]
    layout.assignments = {
        id: folder for id, folder in layout.assignments.items() if id in allowed
    }
    result["layout"] = layout.model_dump(mode="json")
    result["can_create_agent"] = await s.auth.allowed(
        actor, "workspace", workspace_id, "create_agent"
    )
    return result


@app.put(sidebar_path)
async def put_sidebar(
    workspace_id: UUID, body: sidebar.Update, s: Service, actor: User
) -> JSON:
    await s.auth.require(actor, "workspace", workspace_id, "participate")
    ids = set(body.layout.pins) | set(body.layout.order) | set(body.layout.assignments)
    async with s.db.connection() as conn:
        rows = await (
            await conn.execute(
                "SELECT id FROM letas WHERE workspace_id=%s AND id=ANY(%s) AND state NOT IN ('deleting','archived')",
                (workspace_id, list(ids)),
            )
        ).fetchall()
    allowed = (
        await s.auth.allowed_many(
            actor, "agent", [cast(UUID, r["id"]) for r in rows], "use"
        )
        if rows
        else set[UUID]()
    )
    if ids - allowed:
        raise PermissionError("sidebar contains an unavailable agent")
    result = await sidebar.save(s.db, workspace_id, actor.id, body)
    await events.publish(
        s.redis,
        workspace_id,
        events.event(
            "CUSTOM",
            workspace_id,
            name="openlet.resource_changed",
            value={"resource": "sidebar"},
        ),
        actor.id,
    )
    return result


@app.get(sidebar_path + "/events")
async def sidebar_stream(
    workspace_id: UUID, request: Request, s: Service, actor: User
) -> EventSourceResponse:
    await s.auth.require(actor, "workspace", workspace_id, "participate")
    return await event_response(
        workspace_id,
        request,
        s,
        actor,
        "participate",
        {},
        private=True,
        permission_kind="workspace",
    )


@app.get(base + "/box-view")
async def box_view(
    workspace_id: UUID,
    s: Service,
    actor: User,
    leta_id: UUID | None = None,
    cursor: UUID | None = None,
) -> JSON:
    await s.auth.require(actor, "workspace", workspace_id, "view")
    async with s.db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT id FROM letas WHERE workspace_id=%s AND state<>'archived'
            AND (%s::uuid IS NULL OR id=%s) AND (%s::uuid IS NULL OR id>%s) ORDER BY id LIMIT 20""",
                (workspace_id, leta_id, leta_id, cursor, cursor),
            )
        ).fetchall()
    allowed = await s.auth.allowed_many(
        actor, "agent", [cast(UUID, r["id"]) for r in rows], "manage"
    )
    result = await box_views.graph(
        s.db, [cast(UUID, r["id"]) for r in rows if r["id"] in allowed]
    )
    return {**result, "next_cursor": str(rows[-1]["id"]) if len(rows) == 20 else None}


@app.post(base, status_code=202)
async def create_leta(
    workspace_id: UUID, body: CreateLeta, s: Service, actor: User
) -> JSON:
    await s.auth.require(actor, "workspace", workspace_id, "create_agent")
    if body.model_id is not None:
        await s.models.get(body.model_id, body.reasoning_effort)
    elif body.reasoning_effort is not None:
        raise ValueError("reasoning effort requires an explicit model")
    creation = LetaRequest(
        workspace_id=workspace_id,
        owner_id=actor.id,
        request=body,
    )
    return await operation(
        s,
        ResourceOperation(
            id=body.request_id,
            request_id=body.request_id,
            action="create",
            leta=creation,
            bridge_queue=s.config["dependencies"]["temporal"]["queues"]["leta_bridge"],
        ),
    )


@app.get(base)
async def list_letas(
    workspace_id: UUID, s: Service, actor: User, cursor: UUID | None = None
) -> JSON:
    await s.auth.require(actor, "workspace", workspace_id, "view")
    async with s.db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT l.*,a.name,a.title,a.appearance,a.description FROM letas l JOIN agents a ON a.id=l.id
            WHERE l.workspace_id=%s AND l.state NOT IN ('deleting','archived') AND (%s::uuid IS NULL OR l.id>%s) ORDER BY l.id LIMIT 20""",
                (workspace_id, cursor, cursor),
            )
        ).fetchall()
    allowed = await s.auth.allowed_many(
        actor, "agent", [cast(UUID, row["id"]) for row in rows], "use"
    )
    managed = await s.auth.allowed_many(
        actor, "agent", [cast(UUID, row["id"]) for row in rows], "manage"
    )
    deletable = await s.auth.allowed_many(
        actor, "agent", [cast(UUID, row["id"]) for row in rows], "delete"
    )
    summaries = await views.chat_summaries(s.db, list(allowed), actor.id)
    items: list[JSON] = [
        {
            **views.profile(row, row["id"] in managed, row["id"] in deletable),
            **json_row(summaries[cast(UUID, row["id"])]),
        }
        for row in rows
        if row["id"] in allowed
    ]
    return {
        "items": items,
        "next_cursor": str(rows[-1]["id"]) if len(rows) == 20 else None,
    }


@app.get(root_path, dependencies=[Depends(usable)])
async def get_leta(leta_id: UUID, resource: Root, s: Service, actor: User) -> JSON:
    return views.profile(
        resource,
        await s.auth.allowed(actor, "agent", leta_id, "manage"),
        await s.auth.allowed(actor, "agent", leta_id, "delete"),
    )


class CommandInput(Input):
    request_id: UUID


@app.delete(root_path, status_code=202)
async def delete_leta(
    leta_id: UUID, body: CommandInput, s: Service, actor: User, resource: Root
) -> JSON:
    await s.auth.require(actor, "agent", leta_id, "delete")
    return await operation(
        s,
        ResourceOperation(
            id=leta_id,
            request_id=body.request_id,
            action="delete",
            bridge_queue=s.config["dependencies"]["temporal"]["queues"]["leta_bridge"],
        ),
    )


@app.post(root_path + "/pause", status_code=202, dependencies=[Depends(manageable)])
async def pause(leta_id: UUID, body: CommandInput, s: Service) -> JSON:
    return await operation(
        s,
        ResourceOperation(
            id=leta_id,
            request_id=body.request_id,
            action="pause",
            bridge_queue=s.config["dependencies"]["temporal"]["queues"]["leta_bridge"],
        ),
    )


@app.post(root_path + "/resume", status_code=202, dependencies=[Depends(manageable)])
async def resume(leta_id: UUID, body: CommandInput, s: Service) -> JSON:
    return await operation(
        s,
        ResourceOperation(
            id=leta_id,
            request_id=body.request_id,
            action="resume",
            bridge_queue=s.config["dependencies"]["temporal"]["queues"]["leta_bridge"],
        ),
    )


@app.patch(root_path + "/agents/{agent_id}", dependencies=[Depends(manageable)])
async def configure_agent(
    leta_id: UUID, agent_id: UUID, body: ConfigureAgent, s: Service
) -> JSON:
    agent = await child(s, leta_id, agent_id)
    selected = (
        body.model_id
        if "model_id" in body.model_fields_set
        else cast(str | None, agent["model_id"])
    )
    effort = (
        body.reasoning_effort
        if "reasoning_effort" in body.model_fields_set
        else (
            None if "model_id" in body.model_fields_set else agent["reasoning_effort"]
        )
    )
    from openlet_sdk.config import ReasoningEffort

    if selected is None and effort is not None:
        raise ValueError("reasoning effort requires an explicit model")
    if selected is not None:
        await s.models.get(selected, cast(ReasoningEffort, effort))
    if not body.model_fields_set:
        return json_row(agent)
    from psycopg import sql

    values = body.model_dump(exclude_unset=True)
    if "appearance" in values:
        values["appearance"] = Jsonb(values["appearance"])
    if "model_id" in values:
        values["reasoning_effort"] = effort if body.model_id is not None else None
    async with s.db.connection() as conn, conn.transaction():
        await gate(conn, leta_id, cast(UUID | None, agent["box_id"]))
        updated = await (
            await conn.execute(
                sql.SQL("UPDATE agents SET {} WHERE id=%s RETURNING *").format(
                    sql.SQL(",").join(
                        sql.SQL("{}=%s").format(sql.Identifier(field))
                        for field in values
                    )
                ),
                (*values.values(), agent_id),
            )
        ).fetchone()
    assert updated is not None
    return json_row({**agent, **updated})


@app.post(root_path + "/messages", dependencies=[Depends(usable)])
async def send(leta_id: UUID, body: SendMessage, s: Service, actor: User) -> JSON:
    agent = await get_agent(s.db, leta_id)
    refs = await file_refs.validate(
        s,
        cast(UUID, agent["workspace_id"]),
        actor,
        Actor("agent", leta_id),
        body.content,
    )
    await conversations.storage(s, leta_id, actor.id)
    return await deliver(
        s,
        [
            Message(
                id=body.message_id,
                recipient_agent_id=leta_id,
                source_kind="user",
                source_id=actor.id,
                conversation_id=messages.conversation(leta_id, "user", actor.id),
                content=body.content,
                file_refs=refs,
                in_reply_to_message_id=body.in_reply_to,
                in_reply_to_role=body.in_reply_to_role,
            )
        ],
    )


class FileReference(Input):
    storage_id: UUID
    node_id: UUID
    label: str = Field(min_length=1, max_length=255)
    copy_file: bool = Field(default=False, alias="copy")
    request_id: UUID


@app.post(root_path + "/file-reference", dependencies=[Depends(usable)])
async def attach_file(
    leta_id: UUID, body: FileReference, s: Service, actor: User, response: Response
) -> JSON:
    from openlet_api.letfs.v1 import letfs_pb2 as fs

    resource = await get_agent(s.db, leta_id)
    workspace = str(resource["workspace_id"])
    storage_id, node_id = body.storage_id, body.node_id
    if body.copy_file:
        target = await conversations.storage(s, leta_id, actor.id)
        if token := target.get("zed_token"):
            actor = replace(actor, zed_token=str(token))
            response.headers["x-openlet-zed-token"] = actor.zed_token
        source: fs.Node = await s.files.Stat(
            fs.NodeRequest(
                workspace_id=workspace,
                storage_id=str(storage_id),
                target=fs.NodeLocator(node_id=str(node_id)),
            ),
            metadata=actor.metadata,
            timeout=15,
        )
        if source.kind not in (fs.NODE_KIND_FILE, fs.NODE_KIND_DIRECTORY):
            raise ValueError("only stored files and folders can be attached")
        copied: fs.Node = await s.files.CopyNode(
            fs.TransferNodeRequest(
                workspace_id=workspace,
                storage_id=str(storage_id),
                source=fs.NodeLocator(node_id=str(node_id)),
                destination_storage_id=str(target["storage_id"]),
                parent=fs.NodeLocator(node_id=str(target["root_node_id"])),
                name=source.name,
                request_id=str(body.request_id),
            ),
            metadata=actor.metadata,
            timeout=15,
        )
        storage_id, node_id = UUID(copied.storage_id), UUID(copied.id)
    token = file_refs.token(body.label, str(storage_id), str(node_id))
    refs = await file_refs.validate(
        s, cast(UUID, resource["workspace_id"]), actor, Actor("agent", leta_id), token
    )
    return refs[0]


@app.post(root_path + "/conversation-storage", dependencies=[Depends(usable)])
async def conversation_storage(
    leta_id: UUID, s: Service, actor: User, response: Response
) -> JSON:
    result = await conversations.storage(s, leta_id, actor.id)
    if token := result.pop("zed_token", ""):
        response.headers["x-openlet-zed-token"] = str(token)
    return cast(JSON, result)


@app.put(
    root_path + "/messages/{role}/{message_id}/reaction", dependencies=[Depends(usable)]
)
async def react_message(
    leta_id: UUID,
    role: Literal["user", "assistant"],
    message_id: UUID,
    body: reactions.React,
    s: Service,
    actor: User,
) -> JSON:
    result = await reactions.react(
        s.db,
        s.auth,
        leta_id,
        message_id,
        "incoming" if role == "user" else "outgoing",
        actor,
        body,
    )
    await events.changed(s.redis, leta_id, "reactions", message_id, actor.id)
    return result


@app.get(root_path + "/messages", dependencies=[Depends(usable)])
async def chat(
    leta_id: UUID,
    s: Service,
    actor: User,
    before: datetime | None = None,
    cursor: UUID | None = None,
    role: Literal["user", "assistant"] = "user",
) -> JSON:
    return await views.chat(s.db, leta_id, actor.id, before, cursor, role)


class ChatRead(Input):
    through: UUID


@app.get(
    root_path + "/messages/{role}/{message_id}/context", dependencies=[Depends(usable)]
)
async def chat_context(
    leta_id: UUID,
    role: Literal["user", "assistant"],
    message_id: UUID,
    s: Service,
    actor: User,
) -> JSON:
    return await views.chat_context(s.db, leta_id, actor.id, message_id, role)


@app.get(root_path + "/processing", dependencies=[Depends(usable)])
async def chat_processing(leta_id: UUID, s: Service, actor: User) -> JSON:
    manage = await s.auth.allowed(actor, "agent", leta_id, "manage")
    async with s.db.connection() as conn:
        row = await (
            await conn.execute(
                """SELECT r.id FROM runs r WHERE r.agent_id=%s AND r.status='running'
            AND r.heartbeat_at > now()-interval '30 seconds'
            AND (%s OR EXISTS (SELECT 1 FROM agent_messages m WHERE m.processing_run_id=r.id
                AND m.source_kind='user' AND m.source_id=%s)) LIMIT 1""",
                (leta_id, manage, actor.id),
            )
        ).fetchone()
    return {
        "working": row is not None,
        "run_id": str(row["id"]) if row and manage else None,
    }


@app.put(root_path + "/messages/read", dependencies=[Depends(usable)])
async def mark_chat_read(
    leta_id: UUID, body: ChatRead, s: Service, actor: User
) -> JSON:
    await views.mark_chat_read(s.db, leta_id, actor.id, body.through)
    return {"status": "read"}


@app.get(root_path + "/agents/{agent_id}/settings", dependencies=[Depends(manageable)])
async def agent_settings(leta_id: UUID, agent_id: UUID, s: Service) -> JSON:
    return json_row(await child(s, leta_id, agent_id))


@app.get(root_path + "/agents/{agent_id}/activity", dependencies=[Depends(manageable)])
async def browser_activity(
    leta_id: UUID,
    agent_id: UUID,
    s: Service,
    before: int | None = None,
    after: int | None = None,
) -> JSON:
    await child(s, leta_id, agent_id)
    return await views.activity(s.db, agent_id, before, after)


@app.get(
    root_path + "/agents/{agent_id}/activity/{entry_id}",
    dependencies=[Depends(manageable)],
)
async def browser_activity_entry(
    leta_id: UUID, agent_id: UUID, entry_id: UUID, s: Service
) -> JSON:
    await child(s, leta_id, agent_id)
    return await views.activity_entry(s.db, agent_id, entry_id)


@app.get(root_path + "/inbox", dependencies=[Depends(manageable)])
async def browser_inbox(
    leta_id: UUID,
    s: Service,
    agent_id: UUID | None = None,
    query: str = "",
    kind: Literal["user", "agent", "box", "hitl", "schedule"] | None = None,
    unread: bool = False,
    before: datetime | None = None,
    cursor: UUID | None = None,
) -> JSON:
    agent_id = agent_id or leta_id
    await child(s, leta_id, agent_id)
    return await views.inbox(s.db, agent_id, query, kind, unread, before, cursor)


@app.get(
    root_path + "/inbox/{conversation_id}/messages", dependencies=[Depends(manageable)]
)
async def browser_conversation(
    leta_id: UUID,
    conversation_id: UUID,
    s: Service,
    agent_id: UUID | None = None,
    before: datetime | None = None,
    cursor: UUID | None = None,
    direction: Literal["in", "out"] = "in",
) -> JSON:
    agent_id = agent_id or leta_id
    await child(s, leta_id, agent_id)
    return await views.conversation(
        s.db, agent_id, conversation_id, before, cursor, direction
    )


@app.get(root_path + "/agents/{agent_id}/history", dependencies=[Depends(manageable)])
async def activity_history(
    leta_id: UUID,
    agent_id: UUID,
    s: Service,
    before: int | None = None,
    query: str = "",
) -> JSON:
    await child(s, leta_id, agent_id)
    return await activity.search(s.db, agent_id, before, query)


@app.get(
    root_path + "/agents/{agent_id}/history/{entry_id}",
    dependencies=[Depends(manageable)],
)
async def activity_entry(
    leta_id: UUID,
    agent_id: UUID,
    entry_id: UUID,
    s: Service,
    start_line: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
) -> JSON:
    await child(s, leta_id, agent_id)
    return await activity.read(s.db, agent_id, entry_id, start_line, limit)


@app.get(
    root_path + "/agents/{agent_id}/runs/{run_id}", dependencies=[Depends(manageable)]
)
async def get_run(leta_id: UUID, agent_id: UUID, run_id: UUID, s: Service) -> JSON:
    await child(s, leta_id, agent_id)
    async with s.db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT * FROM runs WHERE id=%s AND agent_id=%s", (run_id, agent_id)
            )
        ).fetchone()
    if row is None:
        raise LookupError("run not found")
    return json_row(row)


@app.post(
    root_path + "/agents/{agent_id}/runs/{run_id}/cancel",
    dependencies=[Depends(manageable)],
)
async def cancel_run(leta_id: UUID, agent_id: UUID, run_id: UUID, s: Service) -> JSON:
    await get_run(leta_id, agent_id, run_id, s)
    await s.temporal.get_workflow_handle(f"agent/{agent_id}").execute_update(  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
        "cancel_current", run_id
    )
    return {"run_id": str(run_id), "status": "cancelled"}


async def event_response(
    leta_id: UUID,
    request: Request,
    s: Services,
    actor: Actor,
    permission: str,
    resource: Row,
    private: bool = False,
    permission_kind: str = "agent",
) -> EventSourceResponse:
    after = request.headers.get("last-event-id")
    if after:
        events.cursor(after)
    user = actor.id if private else None

    async def generate() -> AsyncIterator[ServerSentEvent]:
        if not await s.auth.allowed(actor, permission_kind, leta_id, permission):
            return
        position = after or await events.tail(s.redis, leta_id, user)
        if after is None:
            snapshot = (
                events.event(
                    "CUSTOM",
                    leta_id,
                    name="openlet.resource_changed",
                    value={"resource": "sidebar"},
                )
                if permission_kind == "workspace"
                else (
                    events.event(
                        "CUSTOM",
                        leta_id,
                        name="openlet.snapshot",
                        value={
                            "profile": views.profile(
                                resource,
                                await s.auth.allowed(actor, "agent", leta_id, "manage"),
                            ),
                            "messages": await views.chat(s.db, leta_id, actor.id),
                            "requests": await views.requests(
                                s.db,
                                cast(UUID, resource["workspace_id"]),
                                actor.id,
                                leta_id,
                            ),
                        },
                    )
                    if private
                    else await events.snapshot(s.db, leta_id)
                )
            )
            yield ServerSentEvent(
                id=position, data=json.dumps(snapshot, ensure_ascii=False)
            )
        checked = asyncio.get_running_loop().time()
        async for id, event in events.suffix(s.redis, leta_id, position, user):
            now = asyncio.get_running_loop().time()
            if now - checked >= 30:
                if not await s.auth.allowed(
                    actor, permission_kind, leta_id, permission
                ):
                    return
                checked = now
            yield (
                ServerSentEvent(id=id, data=json.dumps(event, ensure_ascii=False))
                if event
                else ServerSentEvent(comment="keepalive")
            )

    return EventSourceResponse(
        generate(),
        send_timeout=10,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get(root_path + "/events", dependencies=[Depends(manageable)])
async def stream(
    leta_id: UUID, request: Request, s: Service, actor: User, resource: Root
) -> EventSourceResponse:
    return await event_response(leta_id, request, s, actor, "manage", resource)


@app.get(root_path + "/messages/events", dependencies=[Depends(usable)])
async def private_stream(
    leta_id: UUID, request: Request, s: Service, actor: User, resource: Root
) -> EventSourceResponse:
    return await event_response(
        leta_id, request, s, actor, "use", resource, private=True
    )


class BoxInput(CreateBox):
    request_id: UUID


@app.post(root_path + "/boxes", dependencies=[Depends(manageable)])
async def create_box(leta_id: UUID, body: BoxInput, s: Service) -> JSON:
    id = stable(leta_id, f"box/{body.request_id}")
    creation = BoxCreation(
        leta_id=leta_id,
        box_id=id,
        request_id=body.request_id,
        request=CreateBox.model_validate(body.model_dump(exclude={"request_id"})),
    )
    return await operation(
        s,
        ResourceOperation(
            id=id,
            request_id=body.request_id,
            action="create",
            box=creation,
            bridge_queue=s.config["dependencies"]["temporal"]["queues"]["leta_bridge"],
        ),
        wait=True,
    )


@app.get(root_path + "/boxes", dependencies=[Depends(manageable)])
async def list_boxes(leta_id: UUID, s: Service, cursor: UUID | None = None) -> JSON:
    return await boxes.list_boxes(s.db, leta_id, cursor)


@app.get(root_path + "/boxes/{box_id}", dependencies=[Depends(manageable)])
async def get_box(
    leta_id: UUID, box_id: UUID, s: Service, include_prompts: bool = False
) -> JSON:
    return await boxes.get(s.db, leta_id, box_id, include_prompts)


@app.delete(root_path + "/boxes/{box_id}", dependencies=[Depends(manageable)])
async def delete_box(
    leta_id: UUID, box_id: UUID, body: CommandInput, s: Service
) -> JSON:
    await boxes.identity(s.db, leta_id, box_id)
    return await operation(
        s,
        ResourceOperation(
            id=box_id,
            request_id=body.request_id,
            action="delete_box",
            bridge_queue=s.config["dependencies"]["temporal"]["queues"]["leta_bridge"],
        ),
        wait=True,
    )


@app.get(root_path + "/access", dependencies=[Depends(manageable)])
async def access(leta_id: UUID, s: Service, cursor: str = "") -> JSON:
    stream = cast(
        AsyncIterator[ReadRelationshipsResponse],
        s.auth.stub.ReadRelationships(
            ReadRelationshipsRequest(
                relationship_filter=RelationshipFilter(
                    resource_type="agent",
                    optional_resource_id=str(leta_id),
                    optional_subject_filter=SubjectFilter(subject_type="user"),
                ),
                consistency=Consistency(fully_consistent=True),
                optional_limit=20,
                optional_cursor=Cursor(token=cursor) if cursor else None,
            ),
            metadata=s.auth.metadata,
            timeout=10,
        ),
    )
    people: list[JSON] = []
    position = ""
    async for item in stream:
        if item.relationship.relation in ("owner", "operator"):
            people.append(
                {
                    "user_id": item.relationship.subject.object.object_id,
                    "role": item.relationship.relation,
                }
            )
        position = item.after_result_cursor.token
    return {"items": people, "next_cursor": position if len(people) >= 20 else None}


@app.put(root_path + "/operators/{user_id}", dependencies=[Depends(manageable)])
async def add_operator(
    workspace_id: UUID, leta_id: UUID, user_id: UUID, s: Service
) -> JSON:
    await s.auth.require(
        Actor("user", user_id), "workspace", workspace_id, "participate"
    )
    await s.auth.write([relationship("agent", leta_id, "operator", "user", user_id)])
    return {"user_id": str(user_id), "role": "operator"}


@app.delete(root_path + "/operators/{user_id}", dependencies=[Depends(manageable)])
async def remove_operator(leta_id: UUID, user_id: UUID, s: Service) -> JSON:
    await s.auth.write(
        [relationship("agent", leta_id, "operator", "user", user_id)], delete=True
    )
    return {"user_id": str(user_id), "removed": True}


@app.get("/v1/hitl-requests")
async def incoming_requests(
    s: Service,
    actor: User,
    cursor: UUID | None = None,
    workspace_id: UUID | None = None,
    leta_id: UUID | None = None,
    status: Literal["pending", "answered", "accepted", "denied", "cancelled", "expired"]
    | None = None,
    before: datetime | None = None,
) -> JSON:
    if workspace_id is not None:
        await s.auth.require(actor, "workspace", workspace_id, "participate")
        return await views.requests(
            s.db, workspace_id, actor.id, leta_id, status, before, cursor
        )
    if (before is None) != (cursor is None):
        raise ValueError("before and cursor must be supplied together")
    async with s.db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT h.*,l.workspace_id,a.leta_id,a.name AS requester_name FROM hitl_requests h JOIN agents a ON a.id=h.requester_agent_id
            JOIN letas l ON l.id=a.leta_id WHERE h.recipient_user_id=%s
            AND (%s::uuid IS NULL OR a.leta_id=%s) AND (%s::text IS NULL OR h.status=%s)
            AND (%s::timestamptz IS NULL OR (h.created_at,h.id)<(%s,%s))
            ORDER BY h.created_at DESC,h.id DESC LIMIT 20""",
                (actor.id, leta_id, leta_id, status, status, before, before, cursor),
            )
        ).fetchall()
        counts = await (
            await conn.execute(
                """SELECT l.workspace_id,count(*) AS count FROM hitl_requests h JOIN agents a ON a.id=h.requester_agent_id
            JOIN letas l ON l.id=a.leta_id WHERE h.recipient_user_id=%s AND h.status='pending'
            AND (%s::uuid IS NULL OR a.leta_id=%s) GROUP BY l.workspace_id""",
                (actor.id, leta_id, leta_id),
            )
        ).fetchall()
    allowed = await s.auth.allowed_many(
        actor,
        "workspace",
        list({cast(UUID, row["workspace_id"]) for row in [*rows, *counts]}),
        "participate",
    )
    items: list[JSON] = [
        json_row(row) for row in rows if row["workspace_id"] in allowed
    ]
    return {
        "items": items,
        "pending_count": sum(
            cast(int, row["count"]) for row in counts if row["workspace_id"] in allowed
        ),
        "next_cursor": {
            "before": cast(datetime, rows[-1]["created_at"]).isoformat(),
            "cursor": str(rows[-1]["id"]),
        }
        if len(rows) == 20
        else None,
    }


@app.get("/v1/hitl-requests/{request_id}")
async def incoming_request(request_id: UUID, s: Service, actor: User) -> JSON:
    value = await hitl.get(s.db, request_id)
    if value["recipient_user_id"] != str(actor.id):
        raise HTTPException(403, "only the addressed person may view this request")
    agent = await get_agent(s.db, UUID(str(value["requester_agent_id"])))
    await s.auth.require(
        actor, "workspace", cast(UUID, agent["workspace_id"]), "participate"
    )
    return value


class Answer(Input):
    status: Literal["answered", "accepted", "denied"]
    response: dict[str, JSON] | None = None


@app.post("/v1/hitl-requests/{request_id}/answer")
async def answer_request(
    request_id: UUID, body: Answer, s: Service, actor: User
) -> JSON:
    await incoming_request(request_id, s, actor)
    return await s.temporal.get_workflow_handle(f"hitl/{request_id}").execute_update(  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
        "decide",
        hitl.Decision(
            request_id=request_id,
            actor=actor,
            status=body.status,
            response=body.response,
            resolved_at=datetime.now(timezone.utc),
        ),
        result_type=dict[str, JSON],
    )


@app.get(root_path + "/hitl-requests", dependencies=[Depends(manageable)])
async def requests(
    leta_id: UUID, s: Service, cursor: UUID | None = None, agent_id: UUID | None = None
) -> JSON:
    if agent_id is not None:
        await child(s, leta_id, agent_id)
    async with s.db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT h.* FROM hitl_requests h JOIN agents a ON a.id=h.requester_agent_id
            WHERE a.leta_id=%s AND (%s::uuid IS NULL OR h.requester_agent_id=%s)
            AND (%s::uuid IS NULL OR h.id>%s) ORDER BY h.id LIMIT 20""",
                (leta_id, agent_id, agent_id, cursor, cursor),
            )
        ).fetchall()
    return {
        "items": [json_row(row) for row in rows],
        "next_cursor": str(rows[-1]["id"]) if len(rows) == 20 else None,
    }


@app.get(root_path + "/hitl-requests/{request_id}", dependencies=[Depends(manageable)])
async def get_request(leta_id: UUID, request_id: UUID, s: Service) -> JSON:
    value = await hitl.get(s.db, request_id)
    await child(s, leta_id, UUID(str(value["requester_agent_id"])))
    return value


@app.post(
    root_path + "/hitl-requests/{request_id}/cancel", dependencies=[Depends(manageable)]
)
async def cancel_request(
    leta_id: UUID, request_id: UUID, s: Service, actor: User
) -> JSON:
    await get_request(leta_id, request_id, s)
    return await s.temporal.get_workflow_handle(f"hitl/{request_id}").execute_update(  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
        "decide",
        hitl.Decision(
            request_id=request_id,
            actor=actor,
            status="cancelled",
            resolved_at=datetime.now(timezone.utc),
        ),
        result_type=dict[str, JSON],
    )


class Ask(Input):
    type: Literal["ask"]
    request_id: UUID
    requester_agent_id: UUID
    recipient_user_id: UUID
    title: str = Field(min_length=1, max_length=255)
    questions: list[hitl.Question] = Field(min_length=1, max_length=10)


class Approval(Input):
    type: Literal["approval"]
    request_id: UUID
    requester_agent_id: UUID
    recipient_user_id: UUID
    storage_id: UUID
    role: Literal["viewer", "editor"] = "viewer"
    reason: str = Field(default="", max_length=4000)


@app.post(root_path + "/hitl-requests", dependencies=[Depends(manageable)])
async def ask(
    leta_id: UUID,
    body: Annotated[Ask | Approval, Field(discriminator="type")],
    s: Service,
) -> JSON:
    await child(s, leta_id, body.requester_agent_id)
    request = hitl.OpenRequest(
        id=body.request_id,
        requester_agent_id=body.requester_agent_id,
        recipient_user_id=body.recipient_user_id,
        type=body.type,
        title=body.title if isinstance(body, Ask) else "Storage access request",
        payload=hitl.form(body.questions)
        if isinstance(body, Ask)
        else {
            "storage_id": str(body.storage_id),
            "role": body.role,
            "reason": body.reason,
        },
    )
    return await submit_hitl(s, request)


class ScheduleCreate(schedules.Timing):
    request_id: UUID
    target_box_id: UUID | None = None
    title: str = Field(default="", max_length=255)
    content: str = Field(min_length=1, max_length=32000)


class ScheduleUpdate(schedules.Timing):
    request_id: UUID
    title: str | None = Field(default=None, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=32000)
    paused: bool | None = None


@app.post(root_path + "/schedules", dependencies=[Depends(manageable)])
async def create_schedule(leta_id: UUID, body: ScheduleCreate, s: Service) -> JSON:
    target = leta_id
    if body.target_box_id:
        box = await boxes.identity(s.db, leta_id, body.target_box_id)
        target = UUID(str(box["leader_agent_id"]))
    data = body.model_dump(exclude={"request_id", "target_box_id"})
    return await submit_schedule(
        s,
        schedules.Change(
            **data,
            request_id=body.request_id,
            schedule_id=stable(leta_id, f"schedule/{body.request_id}"),
            creator_agent_id=leta_id,
            target_agent_id=target,
            action="create",
        ),
    )


@app.get(root_path + "/schedules", dependencies=[Depends(manageable)])
async def list_schedules(
    leta_id: UUID, s: Service, cursor: UUID | None = None, agent_id: UUID | None = None
) -> JSON:
    if agent_id is not None:
        await child(s, leta_id, agent_id)
    async with s.db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT sc.* FROM schedules sc JOIN agents a ON a.id=sc.creator_agent_id
            WHERE a.leta_id=%s AND (%s::uuid IS NULL OR sc.creator_agent_id=%s OR sc.target_agent_id=%s)
            AND (%s::uuid IS NULL OR sc.id>%s) ORDER BY sc.id LIMIT 20""",
                (leta_id, agent_id, agent_id, agent_id, cursor, cursor),
            )
        ).fetchall()
    return {
        "items": [json_row(row) for row in rows],
        "next_cursor": str(rows[-1]["id"]) if len(rows) == 20 else None,
    }


@app.get(root_path + "/schedules/{schedule_id}", dependencies=[Depends(manageable)])
async def get_schedule(leta_id: UUID, schedule_id: UUID, s: Service) -> dict[str, JSON]:
    value = await schedules.get(s.db, schedule_id)
    await child(s, leta_id, UUID(str(value["creator_agent_id"])))
    return {**value, **await schedules.upcoming(s.temporal, value)}


@app.patch(root_path + "/schedules/{schedule_id}", dependencies=[Depends(manageable)])
async def update_schedule(
    leta_id: UUID, schedule_id: UUID, body: ScheduleUpdate, s: Service
) -> JSON:
    value = await schedules.get(s.db, schedule_id, root=leta_id)
    return await submit_schedule(
        s,
        schedules.Change(
            **body.model_dump(exclude={"request_id"}, exclude_unset=True),
            request_id=body.request_id,
            schedule_id=schedule_id,
            creator_agent_id=UUID(str(value["creator_agent_id"])),
            target_agent_id=UUID(str(value["target_agent_id"])),
            action="update",
        ),
    )


@app.delete(root_path + "/schedules/{schedule_id}", dependencies=[Depends(manageable)])
async def delete_schedule(
    leta_id: UUID, schedule_id: UUID, body: CommandInput, s: Service
) -> JSON:
    value = await schedules.get(s.db, schedule_id, root=leta_id)
    return await submit_schedule(
        s,
        schedules.Change(
            request_id=body.request_id,
            schedule_id=schedule_id,
            creator_agent_id=UUID(str(value["creator_agent_id"])),
            target_agent_id=UUID(str(value["target_agent_id"])),
            action="delete",
        ),
    )


@app.get(
    root_path + "/schedules/{schedule_id}/calendar", dependencies=[Depends(manageable)]
)
async def calendar(
    leta_id: UUID, schedule_id: UUID, s: Service, start: datetime, end: datetime
) -> JSON:
    value = await schedules.get(s.db, schedule_id)
    await child(s, leta_id, UUID(str(value["creator_agent_id"])))
    return {
        "times": cast(JSON, await schedules.calendar(s.temporal, value, start, end)),
        "paused": value["paused"],
    }


if __name__ == "__main__":
    host, port = load()["services"]["leta"]["http_listen"].rsplit(":", 1)
    uvicorn.run(app, host=host, port=int(port), access_log=False)
