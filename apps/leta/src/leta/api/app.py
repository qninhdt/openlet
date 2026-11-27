"""FastAPI HTTP control plane for Leta instances, agents, HITL, and schedules."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from openlet_api.platform.v1 import internal_pb2 as plat_int_pb
from openlet_sdk.centrifugo import sign_centrifugo_token
from openlet_sdk.config import JSON, ReasoningEffort
from pydantic import BaseModel, ConfigDict, Field
from temporalio.client import WorkflowUpdateFailedError
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.service import RPCError, RPCStatusCode

from leta.activity import ActivityType, activity_channel
from leta.api.grpc_server import start_internal_grpc
from leta.auth import Actor, delete_rel, relation, touch
from leta.config import ModelSpec, Services
from leta.db import get_receipt, hash_request, hydrate, save_receipt
from leta.hitl.service import (
    HitlDecisionInput,
    HitlRecord,
    RecipientHitlList,
    get_hitl,
    list_leta_hitl,
    list_recipient_hitl,
)
from leta.hitl.workflow import HitlWorkflow
from leta.observability import instrument_fastapi
from leta.orchestration.lifecycle_workflow import (
    LetaCreateInput,
    LetaLifecycleInput,
    LetaLifecycleWorkflow,
)
from leta.schedules.service import (
    ScheduleRecord,
    Timing,
    calendar_occurrences,
    create_schedule,
    delete_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
)
from leta.subagents.service import (
    AgentPatch,
    AgentSummary,
    Appearance,
    list_leta_agents,
    random_appearance,
    stop_agent_tree,
    update_agent,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from langfuse import Langfuse


class StrictBody(BaseModel):
    """Base strict request body forbidding extra fields and trimming strings."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateLetaBody(StrictBody):
    """Request body for provisioning a new Leta instance in a workspace."""

    name: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    custom_instructions: str = Field(default="", max_length=32000)
    model_id: str | None = None
    reasoning_effort: ReasoningEffort = None
    appearance: Appearance | None = None
    request_id: UUID | None = None


class CancelRunBody(StrictBody):
    """Optional request body specifying a run ID to cancel."""

    run_id: UUID | None = None


class PauseBody(StrictBody):
    """Optional request body controlling whether pause cancels active runs."""

    cancel_active: bool = False


class DecideHitlBody(StrictBody):
    """Request body for submitting an HITL decision."""

    status: Literal["answered", "accepted", "denied"]
    response: dict[str, JSON] | None = None


class CreateScheduleBody(Timing):
    """Request body for creating a scheduled wakeup."""

    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=32000)
    target_agent_id: UUID | None = None
    paused: bool = False
    request_id: UUID | None = None


class UpdateScheduleBody(Timing):
    """Request body for partially updating an existing schedule."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=32000)
    target_agent_id: UUID | None = None
    paused: bool | None = None


class ReadyResponse(BaseModel):
    """Health/readiness probe response."""

    status: str


class ModelListResponse(BaseModel):
    """Response listing Leta-enabled models available from the gateway."""

    items: list[ModelSpec]


class LetaRecord(BaseModel):
    """Hydrated Leta workspace instance summary with caller permissions."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    workspace_id: UUID
    storage_id: UUID
    state: str
    paused: bool = False
    created_at: datetime
    name: str
    title: str
    description: str = ""
    appearance: Appearance | dict[str, str] = Field(default_factory=dict[str, str])
    handle: str
    custom_instructions: str = ""
    model_id: str | None = None
    reasoning_effort: ReasoningEffort = None
    running: bool = False
    can_manage: bool = False
    can_delete: bool = False


class LetaListResponse(BaseModel):
    """Response listing Letas visible to the caller in a workspace."""

    items: list[LetaRecord]
    can_create_agent: bool


class AgentListResponse(BaseModel):
    """Response listing all agents in a Leta tree."""

    items: list[AgentSummary]


class AgentDetail(AgentSummary):
    """Detailed agent record including sequence counters and active lease state."""

    model_config = ConfigDict(extra="ignore")

    inbox_seq: int = 0
    activity_seq: int = 0
    lease_token: UUID | None = None
    lease_expires_at: datetime | None = None


class StoppedAgentsResponse(BaseModel):
    """Response listing agent IDs stopped during a subtree teardown."""

    stopped_agent_ids: list[str]


class PausedResponse(BaseModel):
    """Response reporting the resulting paused state of a Leta."""

    paused: bool


class AcceptedResponse(BaseModel):
    """Response confirming an asynchronous control signal was accepted."""

    accepted: bool


class RunRecord(BaseModel):
    """Hydrated execution run row with token and cost metrics."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    agent_id: UUID
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    heartbeat_at: datetime
    error_code: str | None = None
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0


class RunListResponse(BaseModel):
    """Response listing agent execution runs."""

    items: list[RunRecord]


class AccessUser(BaseModel):
    """Workspace user entry in a Leta access control list."""

    id: str
    display_name: str | None = None
    handle: str | None = None
    avatar_url: str | None = None


class AccessResponse(BaseModel):
    """Response listing owners and operators granted access to a Leta."""

    owners: list[AccessUser]
    operators: list[AccessUser]


class OperatorAddedResponse(BaseModel):
    """Response returned after adding an operator relationship in SpiceDB."""

    user_id: str
    zed_token: str


class ActivityEventDetail(BaseModel):
    """Hydrated persisted activity event record for API inspection."""

    model_config = ConfigDict(extra="ignore")

    agent_id: UUID
    seq: int
    run_id: UUID | None = None
    type: ActivityType
    data: dict[str, JSON] = Field(default_factory=dict[str, JSON])
    created_at: datetime


class ActivityListResponse(BaseModel):
    """Response containing ordered activity events for an agent."""

    items: list[ActivityEventDetail]


class RealtimeTokenResponse(BaseModel):
    """Signed Centrifugo subscription token for a Leta activity channel."""

    token: str
    channel: str
    expires_at: str


class LetaHitlListResponse(BaseModel):
    """Response listing HITL requests owned by a Leta instance."""

    items: list[HitlRecord]


class CancelledResponse(BaseModel):
    """Response confirming an HITL cancellation request."""

    cancelled: bool


class ScheduleListResponse(BaseModel):
    """Response listing active schedules for a Leta instance."""

    items: list[ScheduleRecord]


class CalendarOccurrencesResponse(BaseModel):
    """Response listing upcoming schedule occurrence timestamps."""

    occurrences: list[str]


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


def _services(request: Request) -> Services:
    svc: object = getattr(request.app.state, "services", None)
    if svc is None:
        raise RuntimeError("Leta services are not initialized")
    if not isinstance(svc, Services):
        raise TypeError("Leta app.state.services must be a Services instance")
    return svc


async def _require(
    s: Services,
    actor: Actor,
    resource_type: str,
    resource_id: UUID | str,
    permission: str,
    *,
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
) -> LetaRecord:
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
    return hydrate(row, LetaRecord)


_system_router = APIRouter()
_leta_router = APIRouter()
_agent_router = APIRouter()
_access_activity_router = APIRouter()
_hitl_router = APIRouter()
_schedule_router = APIRouter()


@_system_router.get("/ready")
@_system_router.get("/health")
async def ready(s: Annotated[Services, Depends(_services)]) -> ReadyResponse:
    """Verify PostgreSQL connectivity for readiness and health probes."""
    async with s.db.connection() as conn:
        await conn.execute("SELECT 1")
    return ReadyResponse(status="ok")


# --- Models & Leta CRUD ---


@_leta_router.get("/v1/workspaces/{wid}/models")
async def list_models(
    wid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> ModelListResponse:
    """List Leta-enabled LLM models available to workspace participants."""
    await _require(s, actor, "workspace", wid, "participate", zed_token=zed)
    cat = await s.models.catalog()
    return ModelListResponse(items=list(cat.values()))


@_leta_router.get("/v1/workspaces/{wid}/letas")
async def list_letas(
    wid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> LetaListResponse:
    """List active Leta instances visible to the caller in a workspace."""
    await _require(s, actor, "workspace", wid, "participate", zed_token=zed)
    can_create = await s.auth.allowed(
        actor, "workspace", wid, "create_agent", zed_token=zed
    )
    usable = set(await s.auth.lookup_resources(actor, "agent", "use", zed_token=zed))
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
    items: list[LetaRecord] = []
    for r in rows:
        lid_str = str(r["id"])
        if lid_str not in usable and lid_str not in manageable:
            continue
        item = hydrate(r, LetaRecord).model_copy(
            update={
                "can_manage": lid_str in manageable,
                "can_delete": lid_str in deletable,
            }
        )
        items.append(item)
    return LetaListResponse(items=items, can_create_agent=can_create)


@_leta_router.post("/v1/workspaces/{wid}/letas", status_code=status.HTTP_201_CREATED)
async def create_leta(
    wid: UUID,
    *,
    body: CreateLetaBody,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> LetaRecord:
    """Provision a new Leta instance in a workspace via LetaLifecycleWorkflow."""
    if actor.type != "user":
        raise HTTPException(status_code=403, detail="human user required")
    await _require(s, actor, "workspace", wid, "create_agent", zed_token=zed)
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
            return LetaRecord.model_validate(cached)

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
    record = await _ensure_leta_in_workspace(s, wid, leta_id)
    out = record.model_copy(update={"can_manage": True, "can_delete": True})
    if body.request_id is not None:
        await save_receipt(
            s.db,
            f"ws:{wid}:user:{actor.id}",
            "leta.create",
            body.request_id,
            request_hash=req_hash,
            response=out.model_dump(mode="json"),
        )
    return out


@_leta_router.get("/v1/workspaces/{wid}/letas/{lid}")
async def get_leta(
    wid: UUID,
    lid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> LetaRecord:
    """Return a single Leta instance and caller permissions."""
    await _require(s, actor, "agent", lid, "use", zed_token=zed)
    record = await _ensure_leta_in_workspace(s, wid, lid)
    can_manage = await s.auth.allowed(actor, "agent", lid, "manage", zed_token=zed)
    can_delete = await s.auth.allowed(actor, "agent", lid, "delete", zed_token=zed)
    return record.model_copy(
        update={"can_manage": can_manage, "can_delete": can_delete}
    )


@_leta_router.delete(
    "/v1/workspaces/{wid}/letas/{lid}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_leta(
    wid: UUID,
    lid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> None:
    """Archive a Leta instance and clean up its resources via LetaLifecycleWorkflow."""
    await _require(s, actor, "agent", lid, "delete", zed_token=zed)
    await _ensure_leta_in_workspace(s, wid, lid)
    await s.temporal.execute_workflow(
        LetaLifecycleWorkflow.run,
        LetaLifecycleInput(action="delete", leta_id=lid, workspace_id=wid),
        id=f"leta-op/{lid}/delete/{uuid4()}",
        task_queue=s.queues.orchestration,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
    )


# --- Agents, Subagent Tree, Control, & Runs ---


@_agent_router.get("/v1/workspaces/{wid}/letas/{lid}/agents")
async def get_agents(
    wid: UUID,
    lid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> AgentListResponse:
    """List the Root Leta and all subagents in a Leta tree."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
    await _ensure_leta_in_workspace(s, wid, lid)
    return AgentListResponse(items=await list_leta_agents(s.db, lid))


@_agent_router.get("/v1/workspaces/{wid}/letas/{lid}/agents/{aid}")
async def get_single_agent(
    wid: UUID,
    lid: UUID,
    aid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> AgentDetail:
    """Fetch detailed runtime and lease state for a single agent."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
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
    return hydrate(row, AgentDetail)


@_agent_router.patch("/v1/workspaces/{wid}/letas/{lid}/agents/{aid}")
async def patch_agent(
    wid: UUID,
    lid: UUID,
    aid: UUID,
    *,
    body: AgentPatch,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> AgentSummary:
    """Update profile, model, or custom instructions on an agent."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
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


@_agent_router.post("/v1/workspaces/{wid}/letas/{lid}/agents/{aid}/stop")
async def stop_agent(
    wid: UUID,
    lid: UUID,
    aid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> StoppedAgentsResponse:
    """Stop a subagent and all of its descendants."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
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
    return StoppedAgentsResponse(stopped_agent_ids=[str(i) for i in stopped])


@_agent_router.post("/v1/workspaces/{wid}/letas/{lid}/pause")
async def pause_leta(
    wid: UUID,
    lid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
    body: PauseBody | None = None,
) -> PausedResponse:
    """Pause a Leta and signal its active agent workflows."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
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
    return PausedResponse(paused=True)


@_agent_router.post("/v1/workspaces/{wid}/letas/{lid}/resume")
async def resume_leta(
    wid: UUID,
    lid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> PausedResponse:
    """Resume a paused Leta and signal its active agent workflows."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
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
            await s.temporal.get_workflow_handle(f"agent/{r['id']}").signal("resume")
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise
    return PausedResponse(paused=False)


@_agent_router.post(
    "/v1/workspaces/{wid}/letas/{lid}/agents/{aid}/cancel",
    status_code=status.HTTP_202_ACCEPTED,
)
async def cancel_agent_run(
    wid: UUID,
    lid: UUID,
    aid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
    body: CancelRunBody | None = None,
) -> AcceptedResponse:
    """Signal an agent workflow to cancel its active run."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
    await _ensure_leta_in_workspace(s, wid, lid)
    run_id = body.run_id if body is not None else None
    try:
        await s.temporal.get_workflow_handle(f"agent/{aid}").signal(
            "cancel_run", run_id
        )
    except RPCError as exc:
        if exc.status != RPCStatusCode.NOT_FOUND:
            raise
    return AcceptedResponse(accepted=True)


@_agent_router.get("/v1/workspaces/{wid}/letas/{lid}/agents/{aid}/runs")
async def list_runs(
    wid: UUID,
    lid: UUID,
    aid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RunListResponse:
    """List recent execution runs for an agent."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
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
    return RunListResponse(items=[hydrate(r, RunRecord) for r in rows])


@_agent_router.get("/v1/workspaces/{wid}/letas/{lid}/agents/{aid}/runs/{rid}")
async def get_run(
    wid: UUID,
    lid: UUID,
    aid: UUID,
    rid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> RunRecord:
    """Fetch a single execution run record for an agent."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
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
    return hydrate(row, RunRecord)


# --- Access, Activity & Realtime Token ---


@_access_activity_router.get("/v1/workspaces/{wid}/letas/{lid}/access")
async def get_access(
    wid: UUID,
    lid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> AccessResponse:
    """List owners and operators granted access to a Leta instance."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
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
    users_by_id: dict[str, AccessUser] = {}
    if all_ids:
        resp = await s.platform_internal.BatchGetUsers(
            plat_int_pb.BatchGetUsersRequest(user_ids=all_ids), timeout=15
        )
        for u in resp.users:
            users_by_id[u.id] = AccessUser(
                id=u.id,
                display_name=u.display_name,
                handle=u.handle,
                avatar_url=u.avatar_url if u.HasField("avatar_url") else None,
            )
    return AccessResponse(
        owners=[users_by_id.get(uid, AccessUser(id=uid)) for uid in owner_ids],
        operators=[users_by_id.get(uid, AccessUser(id=uid)) for uid in operator_ids],
    )


@_access_activity_router.put("/v1/workspaces/{wid}/letas/{lid}/operators/{user_id}")
async def add_operator(
    wid: UUID,
    lid: UUID,
    user_id: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> OperatorAddedResponse:
    """Grant operator permissions on a Leta to a workspace member."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
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
    return OperatorAddedResponse(user_id=str(user_id), zed_token=token)


@_access_activity_router.delete(
    "/v1/workspaces/{wid}/letas/{lid}/operators/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_operator(
    wid: UUID,
    lid: UUID,
    user_id: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> None:
    """Revoke operator permissions on a Leta for a user."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
    await _ensure_leta_in_workspace(s, wid, lid)
    await s.auth.write(delete_rel(relation("agent", lid, "operator", "user", user_id)))


@_access_activity_router.get("/v1/workspaces/{wid}/letas/{lid}/agents/{aid}/activity")
async def list_activity(
    wid: UUID,
    lid: UUID,
    aid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
    before: Annotated[int | None, Query(gt=0)] = None,
    after: Annotated[int | None, Query(ge=0)] = None,
    query: Annotated[str | None, Query()] = None,
    event_type: Annotated[str | None, Query(alias="type")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ActivityListResponse:
    """List persisted activity events for an agent with cursor and filter pagination."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
    await _ensure_leta_in_workspace(s, wid, lid)
    search_pat = f"%{query}%" if query else None
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
                    (aid, lid, after, event_type, event_type, query, search_pat, limit),
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
                        search_pat,
                        limit,
                    ),
                )
            ).fetchall()
            rows = list(reversed(rows))
    return ActivityListResponse(items=[hydrate(r, ActivityEventDetail) for r in rows])


@_access_activity_router.get(
    "/v1/workspaces/{wid}/letas/{lid}/agents/{aid}/activity/{seq}"
)
async def get_activity_detail(
    wid: UUID,
    lid: UUID,
    aid: UUID,
    seq: int,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> ActivityEventDetail:
    """Fetch a single activity event record by sequence number."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
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
    return hydrate(row, ActivityEventDetail)


@_access_activity_router.post("/v1/workspaces/{wid}/letas/{lid}/realtime-token")
async def get_activity_realtime_token(
    wid: UUID,
    lid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> RealtimeTokenResponse:
    """Issue a signed Centrifugo subscription token for a Leta's activity channel."""
    if actor.type != "user":
        raise HTTPException(status_code=403, detail="human user required")
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
    await _ensure_leta_in_workspace(s, wid, lid)
    if not s.centrifugo_secret:
        raise HTTPException(status_code=503, detail="realtime gateway not configured")
    channel = activity_channel(lid)
    tok, exp = sign_centrifugo_token(
        s.centrifugo_secret,
        str(actor.id),
        channel=channel,
        ttl_seconds=s.centrifugo_ttl,
    )
    return RealtimeTokenResponse(
        token=tok,
        channel=channel,
        expires_at=exp.isoformat(),
    )


# --- HITL ---


@_hitl_router.get("/v1/hitl-requests")
async def list_my_hitl(
    *,
    actor: Annotated[Actor, Depends(_caller)],
    s: Annotated[Services, Depends(_services)],
    workspace_id: Annotated[UUID | None, Query()] = None,
    leta_id: Annotated[UUID | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RecipientHitlList:
    """List HITL requests addressed to the authenticated human user."""
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


@_hitl_router.get("/v1/hitl-requests/{rid}")
async def get_hitl_detail(
    rid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> HitlRecord:
    """Fetch an HITL request detail for its recipient or Leta manager."""
    try:
        row = await get_hitl(s.db, rid)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    is_recipient = actor.type == "user" and actor.id == row.recipient_user_id
    is_owner = await s.auth.allowed(
        actor, "agent", row.leta_id, "manage", zed_token=zed
    )
    if not is_recipient and not is_owner:
        raise HTTPException(status_code=403, detail="hitl access denied")
    return row


@_hitl_router.post("/v1/hitl-requests/{rid}/decide")
async def decide_hitl(
    rid: UUID,
    *,
    body: DecideHitlBody,
    actor: Annotated[Actor, Depends(_caller)],
    s: Annotated[Services, Depends(_services)],
) -> HitlRecord:
    """Submit a recipient decision on a pending HITL request."""
    if actor.type != "user":
        raise HTTPException(status_code=403, detail="human user required")
    try:
        row = await get_hitl(s.db, rid)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if row.recipient_user_id != actor.id:
        raise HTTPException(status_code=403, detail="only recipient can decide")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail=f"already {row.status}")

    decision = HitlDecisionInput(
        request_id=rid,
        actor_type="user",
        actor_id=actor.id,
        status=body.status,
        response=body.response,
    )
    try:
        handle = s.temporal.get_workflow_handle_for(HitlWorkflow.run, f"hitl/{rid}")
        return await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]  # temporalio overload #3 leaves args untyped.
            HitlWorkflow.decide, decision
        )
    except (WorkflowUpdateFailedError, RPCError) as exc:
        msg = str(exc)
        code = 409 if "already" in msg.lower() else 422
        raise HTTPException(status_code=code, detail=msg) from exc


@_hitl_router.get("/v1/workspaces/{wid}/letas/{lid}/hitl-requests")
async def list_leta_hitl_route(
    wid: UUID,
    lid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> LetaHitlListResponse:
    """List HITL requests originating from a Leta instance."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
    await _ensure_leta_in_workspace(s, wid, lid)
    items = await list_leta_hitl(s.db, lid, status=status_filter, limit=limit)
    return LetaHitlListResponse(items=items)


@_hitl_router.post("/v1/workspaces/{wid}/letas/{lid}/hitl-requests/{rid}/cancel")
async def cancel_hitl_route(
    wid: UUID,
    lid: UUID,
    rid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> CancelledResponse:
    """Cancel a pending HITL request belonging to a Leta instance."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
    await _ensure_leta_in_workspace(s, wid, lid)
    try:
        row = await get_hitl(s.db, rid)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if row.leta_id != lid:
        raise HTTPException(status_code=404, detail="hitl request not found")
    try:
        await s.temporal.get_workflow_handle(f"hitl/{rid}").signal("cancel", actor.id)
    except RPCError as exc:
        if exc.status != RPCStatusCode.NOT_FOUND:
            raise
    return CancelledResponse(cancelled=True)


# --- Schedules ---


@_schedule_router.get("/v1/workspaces/{wid}/letas/{lid}/schedules")
async def list_schedules_route(
    wid: UUID,
    lid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> ScheduleListResponse:
    """List active schedules belonging to a Leta instance."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
    await _ensure_leta_in_workspace(s, wid, lid)
    return ScheduleListResponse(items=await list_schedules(s.db, lid))


@_schedule_router.post(
    "/v1/workspaces/{wid}/letas/{lid}/schedules",
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule_route(
    wid: UUID,
    lid: UUID,
    *,
    body: CreateScheduleBody,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> ScheduleRecord:
    """Create a new schedule targeting an agent inside a Leta tree."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
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


@_schedule_router.get("/v1/workspaces/{wid}/letas/{lid}/schedules/{sid}")
async def get_schedule_route(
    wid: UUID,
    lid: UUID,
    sid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> ScheduleRecord:
    """Fetch a single schedule record and its upcoming fire times."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
    await _ensure_leta_in_workspace(s, wid, lid)
    try:
        return await get_schedule(s.db, s.temporal, lid, sid)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@_schedule_router.get("/v1/workspaces/{wid}/letas/{lid}/schedules/{sid}/calendar")
async def schedule_calendar_route(
    wid: UUID,
    lid: UUID,
    sid: UUID,
    *,
    start: Annotated[datetime, Query()],
    end: Annotated[datetime, Query()],
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> CalendarOccurrencesResponse:
    """List matching schedule fire times within a bounded time window."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
    await _ensure_leta_in_workspace(s, wid, lid)
    try:
        await get_schedule(s.db, None, lid, sid)
        times = await calendar_occurrences(s.temporal, sid, start=start, end=end)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return CalendarOccurrencesResponse(occurrences=times)


@_schedule_router.patch("/v1/workspaces/{wid}/letas/{lid}/schedules/{sid}")
async def update_schedule_route(
    wid: UUID,
    lid: UUID,
    sid: UUID,
    *,
    body: UpdateScheduleBody,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> ScheduleRecord:
    """Update a schedule's content, timing, target, or paused state."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
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


@_schedule_router.delete(
    "/v1/workspaces/{wid}/letas/{lid}/schedules/{sid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_schedule_route(
    wid: UUID,
    lid: UUID,
    sid: UUID,
    *,
    actor: Annotated[Actor, Depends(_caller)],
    zed: Annotated[str | None, Depends(_zed_token)],
    s: Annotated[Services, Depends(_services)],
) -> None:
    """Soft-delete a schedule and remove its Temporal Schedule."""
    await _require(s, actor, "agent", lid, "manage", zed_token=zed)
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


def create_app(
    *,
    services: Services | None = None,
    langfuse: Langfuse | None = None,
    start_grpc: bool = True,
) -> FastAPI:
    """Create and configure the Leta FastAPI application and lifespan hooks."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        owned = services is None
        svc = (
            services
            if services is not None
            else await Services.create(langfuse=langfuse)
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
                app.state.services = None

    app = FastAPI(title="Openlet Leta API", lifespan=lifespan)
    if services is not None:
        app.state.services = services
    instrument_fastapi(app)
    for router in (
        _system_router,
        _leta_router,
        _agent_router,
        _access_activity_router,
        _hitl_router,
        _schedule_router,
    ):
        app.include_router(router)
    return app
