import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
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
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from openlet_sdk.config import JSON, load
from openlet_sdk.telemetry import initialize
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from psycopg import errors
from pydantic import Field
from sse_starlette import EventSourceResponse, ServerSentEvent
from temporalio.client import WithStartWorkflowOperation, WorkflowUpdateFailedError
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.service import RPCError, RPCStatusCode

from . import boxes, events, history, hitl, messages, schedules
from .agents import (
    ConfigureAgent,
    CreateLeta,
    Input,
    RootRequest,
    gate,
    get_agent,
    json_row,
    stable,
)
from .auth import Actor, human, relationship
from .boxes import BoxCreation, CreateBox
from .config import Services, connect, model, validate
from .db import Row, request_hash
from .jobs.hitl import HitlInput, HitlRequest
from .jobs.resources import ResourceOperation
from .jobs.schedules import ScheduleChanges, ScheduleInput
from .messages import Message, SendMessage
from .worker import deliver, operation


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


@app.post(base, status_code=202)
async def create_leta(
    workspace_id: UUID, body: CreateLeta, s: Service, actor: User
) -> JSON:
    await s.auth.require(actor, "workspace", workspace_id, "create_agent")
    model(s.config, body.model_id, body.reasoning_effort)
    creation = RootRequest(
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
            root=creation,
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
                """SELECT l.*,a.name,a.description FROM letas l JOIN agents a ON a.id=l.id
            WHERE l.workspace_id=%s AND (%s::uuid IS NULL OR l.id>%s) ORDER BY l.id LIMIT 20""",
                (workspace_id, cursor, cursor),
            )
        ).fetchall()
    items: list[JSON] = []
    for row in rows:
        if await s.auth.allowed(actor, "agent", cast(UUID, row["id"]), "use"):
            items.append(json_row(row))
    return {
        "items": items,
        "next_cursor": str(rows[-1]["id"]) if len(rows) == 20 else None,
    }


@app.get(root_path, dependencies=[Depends(usable)])
async def get_leta(resource: Root) -> JSON:
    return json_row(resource)


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


@app.post(root_path + "/pause", status_code=202, dependencies=[Depends(usable)])
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


@app.post(root_path + "/resume", status_code=202, dependencies=[Depends(usable)])
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


@app.patch(root_path + "/agents/{agent_id}", dependencies=[Depends(usable)])
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
        else agent["reasoning_effort"]
    )
    from openlet_sdk.config import ReasoningEffort

    if selected is None and agent["box_id"]:
        parent = await get_agent(s.db, leta_id)
        selected = cast(str | None, parent["model_id"])
        effort = parent["reasoning_effort"]
    model(s.config, selected, cast(ReasoningEffort, effort))
    if not body.model_fields_set:
        return json_row(agent)
    from psycopg import sql

    values = body.model_dump(exclude_unset=True)
    if "model_id" in values and body.model_id is None:
        values["reasoning_effort"] = None
    async with s.db.connection() as conn, conn.transaction():
        await gate(conn, leta_id, cast(UUID | None, agent["box_id"]))
        await conn.execute(
            sql.SQL("UPDATE agents SET {} WHERE id=%s").format(
                sql.SQL(",").join(
                    sql.SQL("{}=%s").format(sql.Identifier(field)) for field in values
                )
            ),
            (*values.values(), agent_id),
        )
    return json_row(await get_agent(s.db, agent_id))


@app.post(root_path + "/messages", dependencies=[Depends(usable)])
async def send(leta_id: UUID, body: SendMessage, s: Service, actor: User) -> JSON:
    return await deliver(
        s,
        Message(
            id=body.message_id,
            recipient_agent_id=leta_id,
            source_kind="user",
            source_id=actor.id,
            conversation_id=messages.conversation(leta_id, "user", actor.id),
            content=body.content,
            in_reply_to_message_id=body.in_reply_to,
        ),
    )


@app.get(root_path + "/messages", dependencies=[Depends(usable)])
async def chat(
    leta_id: UUID,
    s: Service,
    actor: User,
    before: datetime | None = None,
    cursor: UUID | None = None,
) -> JSON:
    if (before is None) != (cursor is None):
        raise ValueError("before and cursor must be supplied together")
    async with s.db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT * FROM (
            SELECT id,content,created_at,source_id AS user_id,'user' AS role FROM agent_messages WHERE recipient_agent_id=%s AND source_kind='user' AND source_id=%s
            UNION ALL SELECT id,content,created_at,recipient_user_id,'assistant' FROM user_messages WHERE leta_id=%s AND recipient_user_id=%s
            ) chat WHERE (%s::timestamptz IS NULL OR (created_at,id)<(%s,%s)) ORDER BY created_at DESC,id DESC LIMIT 20""",
                (leta_id, actor.id, leta_id, actor.id, before, before, cursor),
            )
        ).fetchall()
    return {
        "items": [json_row(row) for row in rows],
        "next_cursor": {
            "before": cast(datetime, rows[-1]["created_at"]).isoformat(),
            "cursor": str(rows[-1]["id"]),
        }
        if len(rows) == 20
        else None,
    }


@app.get(root_path + "/agents/{agent_id}/history", dependencies=[Depends(usable)])
async def activity_history(
    leta_id: UUID,
    agent_id: UUID,
    s: Service,
    before: int | None = None,
    query: str = "",
) -> JSON:
    await child(s, leta_id, agent_id)
    return await history.search(s.db, agent_id, before, query)


@app.get(
    root_path + "/agents/{agent_id}/history/{entry_id}", dependencies=[Depends(usable)]
)
async def activity_entry(
    leta_id: UUID,
    agent_id: UUID,
    entry_id: UUID,
    s: Service,
    start_line: Annotated[int, Query(ge=1)] = 1,
) -> JSON:
    await child(s, leta_id, agent_id)
    return await history.read(s.db, agent_id, entry_id, start_line)


@app.get(root_path + "/agents/{agent_id}/runs/{run_id}", dependencies=[Depends(usable)])
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
    dependencies=[Depends(usable)],
)
async def cancel_run(leta_id: UUID, agent_id: UUID, run_id: UUID, s: Service) -> JSON:
    await get_run(leta_id, agent_id, run_id, s)
    await s.temporal.get_workflow_handle(f"agent/{agent_id}").execute_update(  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
        "cancel_current", run_id
    )
    return {"run_id": str(run_id), "status": "cancelled"}


@app.get(root_path + "/events", dependencies=[Depends(usable)])
async def stream(
    leta_id: UUID, request: Request, s: Service, actor: User
) -> EventSourceResponse:
    after = request.headers.get("last-event-id")
    if after:
        events.cursor(after)

    async def generate() -> AsyncIterator[ServerSentEvent]:
        position = after or await events.tail(s.redis, leta_id)
        if after is None:
            yield ServerSentEvent(
                id=position,
                data=json.dumps(
                    await events.snapshot(s.db, leta_id), ensure_ascii=False
                ),
            )
        checked = asyncio.get_running_loop().time()
        async for id, event in events.suffix(s.redis, leta_id, position):
            now = asyncio.get_running_loop().time()
            if now - checked >= 30:
                if not await s.auth.allowed(actor, "agent", leta_id, "use"):
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


class BoxInput(CreateBox):
    request_id: UUID


@app.post(root_path + "/boxes", dependencies=[Depends(usable)])
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


@app.get(root_path + "/boxes", dependencies=[Depends(usable)])
async def list_boxes(leta_id: UUID, s: Service, cursor: UUID | None = None) -> JSON:
    return await boxes.list_boxes(s.db, leta_id, cursor)


@app.get(root_path + "/boxes/{box_id}", dependencies=[Depends(usable)])
async def get_box(
    leta_id: UUID, box_id: UUID, s: Service, include_prompts: bool = False
) -> JSON:
    return await boxes.get(s.db, leta_id, str(box_id), include_prompts)


@app.delete(root_path + "/boxes/{box_id}", dependencies=[Depends(usable)])
async def delete_box(
    leta_id: UUID, box_id: UUID, body: CommandInput, s: Service
) -> JSON:
    await boxes.get(s.db, leta_id, str(box_id))
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
    s: Service, actor: User, cursor: UUID | None = None
) -> JSON:
    async with s.db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT h.*,l.workspace_id FROM hitl_requests h JOIN agents a ON a.id=h.requester_agent_id
            JOIN letas l ON l.id=a.leta_id WHERE h.recipient_user_id=%s AND (%s::uuid IS NULL OR h.id>%s) ORDER BY h.id LIMIT 20""",
                (actor.id, cursor, cursor),
            )
        ).fetchall()
    items: list[JSON] = []
    for row in rows:
        if await s.auth.allowed(
            actor, "workspace", cast(UUID, row["workspace_id"]), "participate"
        ):
            items.append(json_row(row))
    return {
        "items": items,
        "next_cursor": str(rows[-1]["id"]) if len(rows) == 20 else None,
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


@app.get(root_path + "/hitl-requests", dependencies=[Depends(usable)])
async def requests(leta_id: UUID, s: Service, cursor: UUID | None = None) -> JSON:
    async with s.db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT h.* FROM hitl_requests h JOIN agents a ON a.id=h.requester_agent_id
            WHERE a.leta_id=%s AND (%s::uuid IS NULL OR h.id>%s) ORDER BY h.id LIMIT 20""",
                (leta_id, cursor, cursor),
            )
        ).fetchall()
    return {
        "items": [json_row(row) for row in rows],
        "next_cursor": str(rows[-1]["id"]) if len(rows) == 20 else None,
    }


@app.get(root_path + "/hitl-requests/{request_id}", dependencies=[Depends(usable)])
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


@app.post(root_path + "/hitl-requests", dependencies=[Depends(usable)])
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
    queues = s.config["dependencies"]["temporal"]["queues"]
    start: WithStartWorkflowOperation[HitlRequest, None] = WithStartWorkflowOperation(
        HitlRequest.run,
        HitlInput(request=request, bridge_queue=queues["leta_bridge"]),
        id=f"hitl/{request.id}",
        task_queue=queues["leta"],
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    return await s.temporal.execute_update_with_start_workflow(  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
        HitlRequest.open,
        request,
        start_workflow_operation=start,
        id=request_hash(request).hex(),
    )


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


async def submit_schedule(s: Services, command: schedules.Change) -> JSON:
    queues = s.config["dependencies"]["temporal"]["queues"]
    start: WithStartWorkflowOperation[ScheduleChanges, None] = (
        WithStartWorkflowOperation(
            ScheduleChanges.run,
            ScheduleInput(
                schedule_id=command.schedule_id, bridge_queue=queues["leta_bridge"]
            ),
            id=f"schedule-changes/{command.schedule_id}",
            task_queue=queues["leta"],
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
    )
    return await s.temporal.execute_update_with_start_workflow(  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
        ScheduleChanges.change,
        command,
        id=request_hash(command).hex(),
        start_workflow_operation=start,
    )


@app.post(root_path + "/schedules", dependencies=[Depends(usable)])
async def create_schedule(leta_id: UUID, body: ScheduleCreate, s: Service) -> JSON:
    target = leta_id
    if body.target_box_id:
        box = await boxes.get(s.db, leta_id, str(body.target_box_id))
        target = UUID(str(box["representative_agent_id"]))
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


@app.get(root_path + "/schedules", dependencies=[Depends(usable)])
async def list_schedules(leta_id: UUID, s: Service, cursor: UUID | None = None) -> JSON:
    async with s.db.connection() as conn:
        rows = await (
            await conn.execute(
                """SELECT sc.* FROM schedules sc JOIN agents a ON a.id=sc.creator_agent_id
            WHERE a.leta_id=%s AND (%s::uuid IS NULL OR sc.id>%s) ORDER BY sc.id LIMIT 20""",
                (leta_id, cursor, cursor),
            )
        ).fetchall()
    return {
        "items": [json_row(row) for row in rows],
        "next_cursor": str(rows[-1]["id"]) if len(rows) == 20 else None,
    }


@app.get(root_path + "/schedules/{schedule_id}", dependencies=[Depends(usable)])
async def get_schedule(leta_id: UUID, schedule_id: UUID, s: Service) -> dict[str, JSON]:
    value = await schedules.get(s.db, schedule_id)
    await child(s, leta_id, UUID(str(value["creator_agent_id"])))
    return {**value, **await schedules.upcoming(s.temporal, value)}


@app.patch(root_path + "/schedules/{schedule_id}", dependencies=[Depends(usable)])
async def update_schedule(
    leta_id: UUID, schedule_id: UUID, body: ScheduleUpdate, s: Service
) -> JSON:
    value = await get_schedule(leta_id, schedule_id, s)
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


@app.delete(root_path + "/schedules/{schedule_id}", dependencies=[Depends(usable)])
async def delete_schedule(
    leta_id: UUID, schedule_id: UUID, body: CommandInput, s: Service
) -> JSON:
    value = await get_schedule(leta_id, schedule_id, s)
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
    root_path + "/schedules/{schedule_id}/calendar", dependencies=[Depends(usable)]
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
