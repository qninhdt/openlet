from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from openlet_api.platform.v1 import internal_pb2 as plat_int_pb
from openlet_sdk.centrifugo import sign_centrifugo_token
from openlet_sdk.config import JSON, ReasoningEffort
from pydantic import BaseModel, ConfigDict, Field
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.service import RPCError, RPCStatusCode

from ..activity import activity_channel
from ..auth import Actor, delete_rel, relation, touch
from ..config import Services
from ..db import get_receipt, hash_request, json_row, save_receipt
from ..hitl.service import (
    HitlDecisionInput,
    get_hitl,
    list_leta_hitl,
    list_recipient_hitl,
)
from ..observability import instrument_fastapi
from ..orchestration.lifecycle_workflow import (
    LetaCreateInput,
    LetaLifecycleInput,
    LetaLifecycleWorkflow,
)
from ..schedules.service import (
    Timing,
    calendar_occurrences,
    create_schedule,
    delete_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
)
from ..subagents.service import (
    AgentPatch,
    Appearance,
    list_leta_agents,
    random_appearance,
    stop_agent_tree,
    update_agent,
)
from .grpc_server import start_internal_grpc


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateLetaBody(StrictBody):
    name: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    custom_instructions: str = Field(default="", max_length=32000)
    model_id: str | None = None
    reasoning_effort: ReasoningEffort = None
    appearance: Appearance | None = None
    request_id: UUID | None = None


class CancelRunBody(StrictBody):
    run_id: UUID | None = None


class PauseBody(StrictBody):
    cancel_active: bool = False


class DecideHitlBody(StrictBody):
    status: Literal["answered", "accepted", "denied"]
    response: dict[str, JSON] | None = None


class CreateScheduleBody(Timing):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=32000)
    target_agent_id: UUID | None = None
    paused: bool = False
    request_id: UUID | None = None


class UpdateScheduleBody(Timing):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=32000)
    target_agent_id: UUID | None = None
    paused: bool | None = None


def _services(request: Request) -> Services:
    return cast(Services, request.app.state.services)


def _caller(
    x_openlet_user_id: str | None = Header(default=None),
    x_openlet_agent_id: str | None = Header(default=None),
) -> Actor:
    if x_openlet_user_id and not x_openlet_agent_id:
        try:
            return Actor("user", UUID(x_openlet_user_id))
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="invalid user header") from exc
    if x_openlet_agent_id and not x_openlet_user_id:
        try:
            return Actor("agent", UUID(x_openlet_agent_id))
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="invalid agent header") from exc
    raise HTTPException(status_code=401, detail="verified actor header required")


def _zed_token(x_openlet_zed_token: str | None = Header(default=None)) -> str | None:
    return x_openlet_zed_token


async def _require(
    s: Services,
    actor: Actor,
    resource_type: str,
    resource_id: UUID | str,
    permission: str,
    zed_token: str | None,
) -> None:
    if not await s.auth.allowed(
        actor, resource_type, resource_id, permission, zed_token=zed_token
    ):
        raise HTTPException(
            status_code=403, detail=f"{resource_type}#{permission} denied"
        )


async def _ensure_leta_in_workspace(
    s: Services, workspace_id: UUID, leta_id: UUID
) -> dict[str, object]:
    async with s.db.connection() as conn:
        row = await (
            await conn.execute(
                """
                SELECT l.*, a.name, a.title, a.description, a.appearance, a.handle,
                       a.custom_instructions, a.model_id, a.reasoning_effort,
                       EXISTS(
                           SELECT 1 FROM runs r
                           JOIN agents ag ON ag.id = r.agent_id
                           WHERE ag.leta_id = l.id AND r.status = 'running'
                       ) AS running
                FROM letas l
                JOIN agents a ON a.id = l.id
                WHERE l.id = %s AND l.workspace_id = %s AND l.state <> 'archived'
                """,
                (leta_id, workspace_id),
            )
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="leta not found")
    return dict(row)


def create_app(
    *,
    services: Services | None = None,
    langfuse: object | None = None,
    start_grpc: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        owned = services is None
        svc = (
            services
            if services is not None
            else await Services.create(langfuse=langfuse)  # pyright: ignore[reportArgumentType]
        )
        app.state.services = svc
        grpc_server = await start_internal_grpc(svc) if start_grpc else None
        try:
            yield
        finally:
            if grpc_server is not None:
                await grpc_server.stop(grace=5)
            if owned:
                await svc.close()

    app = FastAPI(title="Openlet Leta API", lifespan=lifespan)
    instrument_fastapi(app)

    @app.get("/ready")
    @app.get("/health")
    async def ready(s: Services = Depends(_services)) -> dict[str, str]:
        async with s.db.connection() as conn:
            await conn.execute("SELECT 1")
        return {"status": "ok"}

    # --- Models & Leta CRUD ---

    @app.get("/v1/workspaces/{wid}/models")
    async def list_models(
        wid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "workspace", wid, "participate", zed)
        cat = await s.models.catalog()
        return {"items": [m.model_dump() for m in cat.values()]}

    @app.get("/v1/workspaces/{wid}/letas")
    async def list_letas(
        wid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "workspace", wid, "participate", zed)
        can_create = await s.auth.allowed(
            actor, "workspace", wid, "create_agent", zed_token=zed
        )
        usable = set(
            await s.auth.lookup_resources(actor, "agent", "use", zed_token=zed)
        )
        manageable = set(
            await s.auth.lookup_resources(actor, "agent", "manage", zed_token=zed)
        )
        deletable = set(
            await s.auth.lookup_resources(actor, "agent", "delete", zed_token=zed)
        )
        async with s.db.connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT l.id, l.workspace_id, l.storage_id, l.state, l.paused, l.created_at,
                           a.name, a.title, a.description, a.appearance, a.handle,
                           a.custom_instructions, a.model_id, a.reasoning_effort,
                           EXISTS(
                               SELECT 1 FROM runs r
                               JOIN agents ag ON ag.id = r.agent_id
                               WHERE ag.leta_id = l.id AND r.status = 'running'
                           ) AS running
                    FROM letas l
                    JOIN agents a ON a.id = l.id
                    WHERE l.workspace_id = %s AND l.state = 'active'
                    ORDER BY l.created_at DESC
                    """,
                    (wid,),
                )
            ).fetchall()
        items: list[dict[str, JSON]] = []
        for r in rows:
            lid_str = str(r["id"])
            if lid_str not in usable and lid_str not in manageable:
                continue
            item = json_row(r)
            item["can_manage"] = lid_str in manageable
            item["can_delete"] = lid_str in deletable
            items.append(item)
        return {"items": items, "can_create_agent": can_create}

    @app.post("/v1/workspaces/{wid}/letas", status_code=status.HTTP_201_CREATED)
    async def create_leta(
        wid: UUID,
        body: CreateLetaBody,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, JSON]:
        if actor.type != "user":
            raise HTTPException(status_code=403, detail="human user required")
        await _require(s, actor, "workspace", wid, "create_agent", zed)
        if body.model_id is not None:
            try:
                await s.models.get(body.model_id, body.reasoning_effort)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        req_hash = hash_request(body.model_dump(exclude={"request_id"}))
        if body.request_id is not None:
            try:
                cached = await get_receipt(
                    s.db,
                    f"ws:{wid}:user:{actor.id}",
                    "leta.create",
                    body.request_id,
                    req_hash,
                )
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            if cached is not None:
                return cached

        leta_id = uuid4()
        req_id = body.request_id or uuid4()
        create_in = LetaCreateInput(
            leta_id=leta_id,
            workspace_id=wid,
            owner_user_id=actor.id,
            storage_id=uuid4(),
            root_node_id=uuid4(),
            name=body.name,
            title=body.title,
            description=body.description,
            custom_instructions=body.custom_instructions,
            model_id=body.model_id,
            reasoning_effort=body.reasoning_effort,
            appearance=(
                body.appearance.model_dump()
                if body.appearance is not None
                else random_appearance()
            ),
        )
        await s.temporal.execute_workflow(
            LetaLifecycleWorkflow.run,
            LetaLifecycleInput(
                action="create", leta_id=leta_id, workspace_id=wid, create=create_in
            ),
            id=f"leta-op/{leta_id}/create/{req_id}",
            task_queue=s.queues.orchestration,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
        row = await _ensure_leta_in_workspace(s, wid, leta_id)
        out = json_row(row)
        out["can_manage"] = True
        out["can_delete"] = True
        if body.request_id is not None:
            await save_receipt(
                s.db,
                f"ws:{wid}:user:{actor.id}",
                "leta.create",
                body.request_id,
                req_hash,
                out,
            )
        return out

    @app.get("/v1/workspaces/{wid}/letas/{lid}")
    async def get_leta(
        wid: UUID,
        lid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, JSON]:
        await _require(s, actor, "agent", lid, "use", zed)
        row = await _ensure_leta_in_workspace(s, wid, lid)
        out = json_row(row)
        out["can_manage"] = await s.auth.allowed(
            actor, "agent", lid, "manage", zed_token=zed
        )
        out["can_delete"] = await s.auth.allowed(
            actor, "agent", lid, "delete", zed_token=zed
        )
        return out

    @app.delete(
        "/v1/workspaces/{wid}/letas/{lid}", status_code=status.HTTP_204_NO_CONTENT
    )
    async def delete_leta(
        wid: UUID,
        lid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> None:
        await _require(s, actor, "agent", lid, "delete", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        await s.temporal.execute_workflow(
            LetaLifecycleWorkflow.run,
            LetaLifecycleInput(action="delete", leta_id=lid, workspace_id=wid),
            id=f"leta-op/{lid}/delete/{uuid4()}",
            task_queue=s.queues.orchestration,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        )

    # --- Agents & Subagent Tree ---

    @app.get("/v1/workspaces/{wid}/letas/{lid}/agents")
    async def get_agents(
        wid: UUID,
        lid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        return {"items": await list_leta_agents(s.db, lid)}

    @app.get("/v1/workspaces/{wid}/letas/{lid}/agents/{aid}")
    async def get_single_agent(
        wid: UUID,
        lid: UUID,
        aid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, JSON]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        async with s.db.connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT a.*,
                           EXISTS(SELECT 1 FROM runs r WHERE r.agent_id = a.id AND r.status = 'running') AS running
                    FROM agents a
                    WHERE a.id = %s AND a.leta_id = %s
                    """,
                    (aid, lid),
                )
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return json_row(row)

    @app.patch("/v1/workspaces/{wid}/letas/{lid}/agents/{aid}")
    async def patch_agent(
        wid: UUID,
        lid: UUID,
        aid: UUID,
        body: AgentPatch,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, JSON]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        if body.model_id is not None:
            try:
                await s.models.get(body.model_id, body.reasoning_effort)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            return await update_agent(s.db, lid, aid, body)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/workspaces/{wid}/letas/{lid}/agents/{aid}/stop")
    async def stop_agent(
        wid: UUID,
        lid: UUID,
        aid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        if aid == lid:
            raise HTTPException(
                status_code=400,
                detail="cannot stop Root Leta; use pause or delete instead",
            )
        stopped = await stop_agent_tree(
            db=s.db,
            temporal=s.temporal,
            activity=s.activity,
            agent_id=aid,
            include_self=True,
        )
        return {"stopped_agent_ids": [str(i) for i in stopped]}

    # --- Control & Runs ---

    @app.post("/v1/workspaces/{wid}/letas/{lid}/pause")
    async def pause_leta(
        wid: UUID,
        lid: UUID,
        body: PauseBody | None = None,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        cancel_active = body.cancel_active if body is not None else False
        async with s.db.connection() as conn:
            await conn.execute("UPDATE letas SET paused = true WHERE id = %s", (lid,))
            rows = await (
                await conn.execute(
                    "SELECT id FROM agents WHERE leta_id = %s AND state = 'active'",
                    (lid,),
                )
            ).fetchall()
        for r in rows:
            try:
                await s.temporal.get_workflow_handle(f"agent/{r['id']}").signal(
                    "pause", cancel_active
                )
            except RPCError as exc:
                if exc.status != RPCStatusCode.NOT_FOUND:
                    raise
        return {"paused": True}

    @app.post("/v1/workspaces/{wid}/letas/{lid}/resume")
    async def resume_leta(
        wid: UUID,
        lid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        async with s.db.connection() as conn:
            await conn.execute("UPDATE letas SET paused = false WHERE id = %s", (lid,))
            rows = await (
                await conn.execute(
                    "SELECT id FROM agents WHERE leta_id = %s AND state = 'active'",
                    (lid,),
                )
            ).fetchall()
        for r in rows:
            try:
                await s.temporal.get_workflow_handle(f"agent/{r['id']}").signal(
                    "resume"
                )
            except RPCError as exc:
                if exc.status != RPCStatusCode.NOT_FOUND:
                    raise
        return {"paused": False}

    @app.post(
        "/v1/workspaces/{wid}/letas/{lid}/agents/{aid}/cancel",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def cancel_agent_run(
        wid: UUID,
        lid: UUID,
        aid: UUID,
        body: CancelRunBody | None = None,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        run_id = body.run_id if body is not None else None
        try:
            await s.temporal.get_workflow_handle(f"agent/{aid}").signal(
                "cancel_run", run_id
            )
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise
        return {"accepted": True}

    @app.get("/v1/workspaces/{wid}/letas/{lid}/agents/{aid}/runs")
    async def list_runs(
        wid: UUID,
        lid: UUID,
        aid: UUID,
        limit: int = Query(default=50, ge=1, le=100),
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        async with s.db.connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT r.*
                    FROM runs r
                    JOIN agents a ON a.id = r.agent_id
                    WHERE r.agent_id = %s AND a.leta_id = %s
                    ORDER BY r.started_at DESC
                    LIMIT %s
                    """,
                    (aid, lid, limit),
                )
            ).fetchall()
        return {"items": [json_row(r) for r in rows]}

    @app.get("/v1/workspaces/{wid}/letas/{lid}/agents/{aid}/runs/{rid}")
    async def get_run(
        wid: UUID,
        lid: UUID,
        aid: UUID,
        rid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, JSON]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        async with s.db.connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT r.*
                    FROM runs r
                    JOIN agents a ON a.id = r.agent_id
                    WHERE r.id = %s AND r.agent_id = %s AND a.leta_id = %s
                    """,
                    (rid, aid, lid),
                )
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="run not found")
        return json_row(row)

    # --- Access & Operators ---

    @app.get("/v1/workspaces/{wid}/letas/{lid}/access")
    async def get_access(
        wid: UUID,
        lid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        rels = await s.auth.read_relationships("agent", lid, zed_token=zed)
        owner_ids: list[str] = []
        operator_ids: list[str] = []
        for rel in rels:
            if rel.subject.object.object_type != "user":
                continue
            uid = str(rel.subject.object.object_id)
            if rel.relation == "owner":
                owner_ids.append(uid)
            elif rel.relation == "operator":
                operator_ids.append(uid)
        all_ids = list(dict.fromkeys([*owner_ids, *operator_ids]))
        users_by_id: dict[str, dict[str, object]] = {}
        if all_ids:
            resp = await s.platform_internal.BatchGetUsers(
                plat_int_pb.BatchGetUsersRequest(user_ids=all_ids), timeout=15
            )
            for u in resp.users:
                users_by_id[u.id] = {
                    "id": u.id,
                    "display_name": u.display_name,
                    "handle": u.handle,
                    "avatar_url": u.avatar_url if u.HasField("avatar_url") else None,
                }
        return {
            "owners": [users_by_id.get(uid, {"id": uid}) for uid in owner_ids],
            "operators": [users_by_id.get(uid, {"id": uid}) for uid in operator_ids],
        }

    @app.put("/v1/workspaces/{wid}/letas/{lid}/operators/{user_id}")
    async def add_operator(
        wid: UUID,
        lid: UUID,
        user_id: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        if not await s.auth.allowed(
            Actor("user", user_id), "workspace", wid, "participate", zed_token=zed
        ):
            raise HTTPException(
                status_code=400, detail="user is not a member of this workspace"
            )
        token = await s.auth.write(
            touch(relation("agent", lid, "operator", "user", user_id))
        )
        return {"user_id": str(user_id), "zed_token": token}

    @app.delete(
        "/v1/workspaces/{wid}/letas/{lid}/operators/{user_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def remove_operator(
        wid: UUID,
        lid: UUID,
        user_id: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> None:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        await s.auth.write(
            delete_rel(relation("agent", lid, "operator", "user", user_id))
        )

    # --- Activity & Realtime Token ---

    @app.get("/v1/workspaces/{wid}/letas/{lid}/agents/{aid}/activity")
    async def list_activity(
        wid: UUID,
        lid: UUID,
        aid: UUID,
        before: int | None = Query(default=None, gt=0),
        after: int | None = Query(default=None, ge=0),
        query: str | None = Query(default=None),
        event_type: str | None = Query(default=None, alias="type"),
        limit: int = Query(default=50, ge=1, le=100),
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        async with s.db.connection() as conn:
            if after is not None:
                rows = await (
                    await conn.execute(
                        """
                        SELECT e.*
                        FROM activity_events e
                        JOIN agents a ON a.id = e.agent_id
                        WHERE e.agent_id = %s AND a.leta_id = %s AND e.seq > %s
                          AND (%s::text IS NULL OR e.type = %s)
                          AND (%s::text IS NULL OR e.data::text ILIKE %s)
                        ORDER BY e.seq ASC
                        LIMIT %s
                        """,
                        (
                            aid,
                            lid,
                            after,
                            event_type,
                            event_type,
                            query,
                            f"%{query}%" if query else None,
                            limit,
                        ),
                    )
                ).fetchall()
            else:
                rows = await (
                    await conn.execute(
                        """
                        SELECT e.*
                        FROM activity_events e
                        JOIN agents a ON a.id = e.agent_id
                        WHERE e.agent_id = %s AND a.leta_id = %s
                          AND (%s::bigint IS NULL OR e.seq < %s)
                          AND (%s::text IS NULL OR e.type = %s)
                          AND (%s::text IS NULL OR e.data::text ILIKE %s)
                        ORDER BY e.seq DESC
                        LIMIT %s
                        """,
                        (
                            aid,
                            lid,
                            before,
                            before,
                            event_type,
                            event_type,
                            query,
                            f"%{query}%" if query else None,
                            limit,
                        ),
                    )
                ).fetchall()
                rows = list(reversed(rows))
        return {"items": [json_row(r) for r in rows]}

    @app.get("/v1/workspaces/{wid}/letas/{lid}/agents/{aid}/activity/{seq}")
    async def get_activity_detail(
        wid: UUID,
        lid: UUID,
        aid: UUID,
        seq: int,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, JSON]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        async with s.db.connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT e.*
                    FROM activity_events e
                    JOIN agents a ON a.id = e.agent_id
                    WHERE e.agent_id = %s AND a.leta_id = %s AND e.seq = %s
                    """,
                    (aid, lid, seq),
                )
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="activity event not found")
        return json_row(row)

    @app.post("/v1/workspaces/{wid}/letas/{lid}/realtime-token")
    async def get_activity_realtime_token(
        wid: UUID,
        lid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, str]:
        if actor.type != "user":
            raise HTTPException(status_code=403, detail="human user required")
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        if not s.centrifugo_secret:
            raise HTTPException(
                status_code=503, detail="realtime gateway not configured"
            )
        channel = activity_channel(lid)
        tok, exp = sign_centrifugo_token(
            s.centrifugo_secret,
            str(actor.id),
            channel=channel,
            ttl_seconds=s.centrifugo_ttl,
        )
        return {
            "token": tok,
            "channel": channel,
            "expires_at": exp.isoformat(),
        }

    # --- HITL ---

    @app.get("/v1/hitl-requests")
    async def list_my_hitl(
        workspace_id: UUID | None = Query(default=None),
        leta_id: UUID | None = Query(default=None),
        status_filter: str | None = Query(default=None, alias="status"),
        limit: int = Query(default=50, ge=1, le=100),
        actor: Actor = Depends(_caller),
        s: Services = Depends(_services),
    ) -> dict[str, JSON]:
        if actor.type != "user":
            raise HTTPException(status_code=403, detail="human user required")
        return await list_recipient_hitl(
            s.db,
            actor.id,
            workspace_id=workspace_id,
            leta_id=leta_id,
            status=status_filter,
            limit=limit,
        )

    @app.get("/v1/hitl-requests/{rid}")
    async def get_hitl_detail(
        rid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, JSON]:
        try:
            row = await get_hitl(s.db, rid)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        is_recipient = actor.type == "user" and str(actor.id) == str(
            row["recipient_user_id"]
        )
        is_owner = await s.auth.allowed(
            actor, "agent", str(row["leta_id"]), "manage", zed_token=zed
        )
        if not is_recipient and not is_owner:
            raise HTTPException(status_code=403, detail="hitl access denied")
        return row

    @app.post("/v1/hitl-requests/{rid}/decide")
    async def decide_hitl(
        rid: UUID,
        body: DecideHitlBody,
        actor: Actor = Depends(_caller),
        s: Services = Depends(_services),
    ) -> dict[str, JSON]:
        if actor.type != "user":
            raise HTTPException(status_code=403, detail="human user required")
        try:
            row = await get_hitl(s.db, rid)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if str(row["recipient_user_id"]) != str(actor.id):
            raise HTTPException(status_code=403, detail="only recipient can decide")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"already {row['status']}")

        decision = HitlDecisionInput(
            request_id=rid,
            actor_type="user",
            actor_id=actor.id,
            status=body.status,
            response=body.response,
        )
        try:
            from ..hitl.workflow import HitlWorkflow

            handle = s.temporal.get_workflow_handle(f"hitl/{rid}")
            return await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]
                HitlWorkflow.decide, decision
            )
        except Exception as exc:
            msg = str(exc)
            code = 409 if "already" in msg.lower() else 422
            raise HTTPException(status_code=code, detail=msg) from exc

    @app.get("/v1/workspaces/{wid}/letas/{lid}/hitl-requests")
    async def list_leta_hitl_route(
        wid: UUID,
        lid: UUID,
        status_filter: str | None = Query(default=None, alias="status"),
        limit: int = Query(default=50, ge=1, le=100),
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        items = await list_leta_hitl(s.db, lid, status=status_filter, limit=limit)
        return {"items": items}

    @app.post("/v1/workspaces/{wid}/letas/{lid}/hitl-requests/{rid}/cancel")
    async def cancel_hitl_route(
        wid: UUID,
        lid: UUID,
        rid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        try:
            row = await get_hitl(s.db, rid)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if str(row["leta_id"]) != str(lid):
            raise HTTPException(status_code=404, detail="hitl request not found")
        try:
            await s.temporal.get_workflow_handle(f"hitl/{rid}").signal(
                "cancel", actor.id
            )
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise
        return {"cancelled": True}

    # --- Schedules ---

    @app.get("/v1/workspaces/{wid}/letas/{lid}/schedules")
    async def list_schedules_route(
        wid: UUID,
        lid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        return {"items": await list_schedules(s.db, lid)}

    @app.post(
        "/v1/workspaces/{wid}/letas/{lid}/schedules",
        status_code=status.HTTP_201_CREATED,
    )
    async def create_schedule_route(
        wid: UUID,
        lid: UUID,
        body: CreateScheduleBody,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, JSON]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        timing = Timing(
            at=body.at,
            after_seconds=body.after_seconds,
            every_seconds=body.every_seconds,
            calendar=body.calendar,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            timezone=body.timezone,
        )
        try:
            return await create_schedule(
                db=s.db,
                temporal=s.temporal,
                orchestration_queue=s.queues.orchestration,
                activity=s.activity,
                leta_id=lid,
                creator_agent_id=lid,
                target_agent_id=body.target_agent_id or lid,
                title=body.title,
                content=body.content,
                timing=timing,
                paused=body.paused,
                request_id=body.request_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/workspaces/{wid}/letas/{lid}/schedules/{sid}")
    async def get_schedule_route(
        wid: UUID,
        lid: UUID,
        sid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, JSON]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        try:
            return await get_schedule(s.db, s.temporal, lid, sid)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/workspaces/{wid}/letas/{lid}/schedules/{sid}/calendar")
    async def schedule_calendar_route(
        wid: UUID,
        lid: UUID,
        sid: UUID,
        start: datetime = Query(...),
        end: datetime = Query(...),
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, object]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        try:
            await get_schedule(s.db, None, lid, sid)
            times = await calendar_occurrences(s.temporal, sid, start=start, end=end)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"occurrences": times}

    @app.patch("/v1/workspaces/{wid}/letas/{lid}/schedules/{sid}")
    async def update_schedule_route(
        wid: UUID,
        lid: UUID,
        sid: UUID,
        body: UpdateScheduleBody,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> dict[str, JSON]:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        has_timing = any(
            v is not None
            for v in (body.at, body.after_seconds, body.every_seconds, body.calendar)
        )
        timing = (
            Timing(
                at=body.at,
                after_seconds=body.after_seconds,
                every_seconds=body.every_seconds,
                calendar=body.calendar,
                starts_at=body.starts_at,
                ends_at=body.ends_at,
                timezone=body.timezone,
            )
            if has_timing
            else None
        )
        try:
            return await update_schedule(
                db=s.db,
                temporal=s.temporal,
                orchestration_queue=s.queues.orchestration,
                activity=s.activity,
                leta_id=lid,
                schedule_id=sid,
                title=body.title,
                content=body.content,
                target_agent_id=body.target_agent_id,
                timing=timing,
                paused=body.paused,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete(
        "/v1/workspaces/{wid}/letas/{lid}/schedules/{sid}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_schedule_route(
        wid: UUID,
        lid: UUID,
        sid: UUID,
        actor: Actor = Depends(_caller),
        zed: str | None = Depends(_zed_token),
        s: Services = Depends(_services),
    ) -> None:
        await _require(s, actor, "agent", lid, "manage", zed)
        await _ensure_leta_in_workspace(s, wid, lid)
        try:
            await delete_schedule(
                db=s.db,
                temporal=s.temporal,
                activity=s.activity,
                leta_id=lid,
                schedule_id=sid,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return app
