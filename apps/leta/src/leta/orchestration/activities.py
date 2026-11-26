from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Literal
from uuid import UUID

import grpc
from openlet_api.chat.v1 import internal_pb2 as chat_int_pb
from openlet_api.letfs.v1 import internal_pb2 as letfs_int_pb
from openlet_api.letfs.v1 import letfs_pb2 as letfs_pb
from openlet_api.platform.v1 import internal_pb2 as plat_int_pb
from openlet_sdk.config import JSON
from psycopg.types.json import Jsonb
from temporalio import activity
from temporalio.service import RPCError, RPCStatusCode

from ..auth import relation, touch
from ..config import Services
from ..hitl.service import (
    HitlDecisionInput,
    OpenHitlInput,
    apply_hitl_effect,
    deliver_hitl_result,
    open_hitl,
    resolve_hitl,
)
from ..runs import finish_run
from ..schedules.service import fire_schedule, temporal_schedule_id
from ..subagents.service import (
    allocate_unique_root_handle,
    notify_parent_failure,
    random_appearance,
    stop_agent_tree,
)
from .agent_workflow import RunInput, RunResult
from .lifecycle_workflow import LetaCreateInput


class OrchestrationActivities:
    def __init__(self, services: Services) -> None:
        self.s = services

    @activity.defn(name="finish_run")
    async def finish_run(
        self,
        run_id: UUID,
        agent_id: UUID,
        status: Literal["completed", "failed", "cancelled"],
        error_code: str | None,
    ) -> None:
        await finish_run(
            self.s.db,
            self.s.activity,
            run_id=run_id,
            agent_id=agent_id,
            status=status,
            error_code=error_code,
        )

    @activity.defn(name="notify_parent_failure")
    async def notify_parent_failure(self, agent_id: UUID, error_message: str) -> None:
        await notify_parent_failure(
            db=self.s.db,
            inbox=self.s.inbox,
            agent_id=agent_id,
            error_message=error_message,
        )

    @activity.defn(name="stop_child_agents")
    async def stop_child_agents(self, agent_id: UUID) -> None:
        await stop_agent_tree(
            db=self.s.db,
            temporal=self.s.temporal,
            activity=self.s.activity,
            agent_id=agent_id,
            include_self=False,
        )

    @activity.defn(name="prepare_leta_db")
    async def prepare_leta_db(self, data: LetaCreateInput) -> str:
        appearance = data.appearance or random_appearance()
        async with self.s.db.connection() as conn, conn.transaction():
            existing = await (
                await conn.execute(
                    "SELECT handle FROM agents WHERE id = %s", (data.leta_id,)
                )
            ).fetchone()
            if existing is not None:
                return str(existing["handle"])

            # Serialize root handle allocation per workspace via transaction advisory lock.
            lock_key = data.workspace_id.int & ((1 << 63) - 1)
            await conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))
            handle = await allocate_unique_root_handle(
                conn, data.workspace_id, data.name, data.title
            )
            await conn.execute(
                """
                INSERT INTO letas(id, workspace_id, storage_id, state)
                VALUES (%s, %s, %s, 'provisioning')
                ON CONFLICT (id) DO NOTHING
                """,
                (data.leta_id, data.workspace_id, data.storage_id),
            )
            await conn.execute(
                """
                INSERT INTO agents(
                    id, leta_id, parent_agent_id, depth, name, title, description,
                    appearance, handle, custom_instructions, model_id, reasoning_effort, state
                ) VALUES (%s, %s, NULL, 0, %s, %s, %s, %s, %s, %s, %s, %s, 'active')
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    data.leta_id,
                    data.leta_id,
                    data.name.strip(),
                    data.title.strip(),
                    data.description.strip(),
                    Jsonb(appearance),
                    handle,
                    data.custom_instructions,
                    data.model_id,
                    data.reasoning_effort,
                ),
            )
        return handle

    @activity.defn(name="provision_leta_resources")
    async def provision_leta_resources(self, data: LetaCreateInput) -> None:
        await self.s.platform_internal.CheckWorkspaceActive(
            plat_int_pb.CheckWorkspaceActiveRequest(
                workspace_id=str(data.workspace_id)
            ),
            timeout=15,
        )
        await self.s.auth.write(
            touch(
                relation("workspace", data.workspace_id, "agent", "agent", data.leta_id)
            ),
            touch(
                relation(
                    "agent", data.leta_id, "workspace", "workspace", data.workspace_id
                )
            ),
            touch(relation("agent", data.leta_id, "owner", "user", data.owner_user_id)),
        )
        try:
            await self.s.letfs_internal.CreateStorage(
                letfs_int_pb.CreateStorageRequest(
                    workspace_id=str(data.workspace_id),
                    storage_id=str(data.storage_id),
                    root_node_id=str(data.root_node_id),
                    owner=letfs_pb.StorageOwnership(agent_id=str(data.leta_id)),
                    name=data.name.strip(),
                    visibility=letfs_pb.STORAGE_VISIBILITY_PRIVATE,
                    allow_blob_files=True,
                    allow_indexing=True,
                ),
                timeout=30,
            )
        except grpc.aio.AioRpcError as exc:
            if exc.code() != grpc.StatusCode.ALREADY_EXISTS:
                raise
        async with self.s.db.connection() as conn:
            await conn.execute(
                "UPDATE letas SET state = 'active' WHERE id = %s AND state = 'provisioning'",
                (data.leta_id,),
            )

    @activity.defn(name="mark_leta_deleting")
    async def mark_leta_deleting(self, leta_id: UUID) -> None:
        async with self.s.db.connection() as conn:
            await conn.execute(
                "UPDATE letas SET state = 'deleting' WHERE id = %s AND state <> 'archived'",
                (leta_id,),
            )

    @activity.defn(name="cleanup_leta_schedules")
    async def cleanup_leta_schedules(self, leta_id: UUID) -> None:
        async with self.s.db.connection() as conn:
            rows = await (
                await conn.execute(
                    "UPDATE schedules SET deleted_at = now() WHERE leta_id = %s AND deleted_at IS NULL RETURNING id",
                    (leta_id,),
                )
            ).fetchall()

        async def _del(sid: str) -> None:
            try:
                await self.s.temporal.get_schedule_handle(
                    temporal_schedule_id(sid)
                ).delete()
            except RPCError as exc:
                if exc.status != RPCStatusCode.NOT_FOUND:
                    raise

        if rows:
            await asyncio.gather(*(_del(str(r["id"])) for r in rows))

    @activity.defn(name="cleanup_leta_hitl")
    async def cleanup_leta_hitl(self, leta_id: UUID) -> None:
        async with self.s.db.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT id FROM hitl_requests WHERE leta_id = %s AND status = 'pending'",
                    (leta_id,),
                )
            ).fetchall()

        async def _cancel(rid: UUID) -> None:
            try:
                handle = self.s.temporal.get_workflow_handle(f"hitl/{rid}")
                await handle.signal("cancel", leta_id)
            except RPCError as exc:
                if exc.status != RPCStatusCode.NOT_FOUND:
                    raise

        if rows:
            await asyncio.gather(*(_cancel(UUID(str(r["id"]))) for r in rows))

    @activity.defn(name="cleanup_leta_agents")
    async def cleanup_leta_agents(self, leta_id: UUID) -> None:
        await stop_agent_tree(
            db=self.s.db,
            temporal=self.s.temporal,
            activity=self.s.activity,
            agent_id=leta_id,
            include_self=True,
        )

    @activity.defn(name="cleanup_leta_resources")
    async def cleanup_leta_resources(self, workspace_id: UUID, leta_id: UUID) -> None:
        try:
            await self.s.chat_internal.RemoveAgent(
                chat_int_pb.RemoveAgentRequest(
                    workspace_id=str(workspace_id), agent_id=str(leta_id)
                ),
                timeout=30,
            )
        except grpc.aio.AioRpcError as exc:
            if exc.code() != grpc.StatusCode.NOT_FOUND:
                raise
        await self.s.auth.delete_filter("agent", leta_id)
        await self.s.auth.delete_filter(
            "workspace",
            workspace_id,
            relation_name="agent",
            subject_type="agent",
            subject_id=leta_id,
        )
        async with self.s.db.connection() as conn:
            await conn.execute(
                "UPDATE letas SET state = 'archived' WHERE id = %s", (leta_id,)
            )

    @activity.defn(name="open_hitl")
    async def open_hitl(self, request: OpenHitlInput) -> dict[str, JSON]:
        return await open_hitl(
            db=self.s.db,
            auth=self.s.auth,
            letfs=self.s.letfs,
            activity=self.s.activity,
            request=request,
        )

    @activity.defn(name="resolve_hitl")
    async def resolve_hitl(self, decision: HitlDecisionInput) -> dict[str, JSON]:
        return await resolve_hitl(
            db=self.s.db, activity=self.s.activity, decision=decision
        )

    @activity.defn(name="apply_hitl_effect")
    async def apply_hitl_effect(self, request_id: UUID) -> dict[str, JSON]:
        return await apply_hitl_effect(
            db=self.s.db,
            auth=self.s.auth,
            letfs=self.s.letfs,
            activity=self.s.activity,
            request_id=request_id,
        )

    @activity.defn(name="deliver_hitl_result")
    async def deliver_hitl_result(self, request_id: UUID) -> None:
        await deliver_hitl_result(
            db=self.s.db, inbox=self.s.inbox, request_id=request_id
        )

    @activity.defn(name="fire_schedule")
    async def fire_schedule(self, schedule_id: UUID, nominal_time: datetime) -> None:
        await fire_schedule(
            db=self.s.db,
            inbox=self.s.inbox,
            schedule_id=schedule_id,
            nominal_time=nominal_time,
        )


class RuntimeActivities:
    def __init__(self, services: Services) -> None:
        self.s = services

    @activity.defn(name="run_agent_turn")
    async def run_agent_turn(self, payload: RunInput) -> RunResult:
        from ..runtime.runner import run_agent_turn

        outcome = await run_agent_turn(
            self.s,
            agent_id=payload.agent_id,
            run_id=payload.run_id,
            heartbeat=activity.heartbeat,
        )
        return RunResult(
            inbox_cursor=outcome.inbox_cursor,
            latest_wake_seq=outcome.latest_wake_seq,
        )
