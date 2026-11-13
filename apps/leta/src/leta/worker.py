from collections.abc import Awaitable
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

import grpc
from authzed.api.v1 import (
    DeleteRelationshipsRequest,
    DeleteRelationshipsResponse,
    RelationshipFilter,
    SubjectFilter,
)
from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_api.platform.v1 import internal_pb2 as platform
from openlet_sdk.config import JSON
from temporalio import activity
from temporalio.client import WithStartWorkflowOperation, WorkflowUpdateFailedError
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError, RPCStatusCode

from . import agents, boxes, hitl, messages, schedules
from .agents import RootCreation, get_agent, stable
from .auth import Actor, relationship
from .boxes import BoxCreation
from .config import Services
from .db import effect
from .jobs.agent import Agent, AgentInput
from .jobs.resources import BoxLifecycle, LetaLifecycle, ResourceOperation
from .messages import Message


async def deliver(s: Services, message: Message) -> dict[str, JSON]:
    queue = s.config["dependencies"]["temporal"]["queues"]
    start: WithStartWorkflowOperation[Agent, None] = WithStartWorkflowOperation(
        Agent.run,
        AgentInput(
            agent_id=message.recipient_agent_id, runtime_queue=queue["leta_runtime"]
        ),
        id=f"agent/{message.recipient_agent_id}",
        task_queue=queue["leta"],
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    return await s.temporal.execute_update_with_start_workflow(
        Agent.receive, message, id=str(message.id), start_workflow_operation=start
    )


async def operation(
    s: Services, command: ResourceOperation, *, wait: bool = False
) -> dict[str, JSON]:
    is_box = command.box is not None or command.action == "delete_box"
    type = BoxLifecycle if is_box else LetaLifecycle
    action = "delete" if command.action == "delete_box" else command.action
    id = f"{'box' if is_box else 'leta'}/{command.id}/{action}"
    if action in ("pause", "resume"):
        id = f"leta/{command.id}/control/{command.request_id}"
    handle = await s.temporal.start_workflow(
        type.run,
        command,
        id=id,
        task_queue=s.config["dependencies"]["temporal"]["queues"]["leta"],
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    return (
        await handle.result()
        if wait
        else await handle.execute_update("open", result_type=dict[str, JSON])
    )


class Activities:
    def __init__(self, services: Services) -> None:
        self.s = services

    @activity.defn
    async def admit_input(self, message: Message) -> dict[str, JSON]:
        return await messages.admit(self.s.db, self.s.auth, message)

    @activity.defn
    async def load_agent_control(self, id: UUID) -> dict[str, JSON]:
        agent = await get_agent(self.s.db, id)
        async with self.s.db.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT id FROM runs WHERE agent_id=%s AND status IN ('running','paused')",
                    (id,),
                )
            ).fetchone()
        return {
            "active": agent["state"] == "active"
            and (agent["box_id"] is None or agent["box_state"] == "active"),
            "paused": bool(agent["paused"]),
            "run_id": str(row["id"]) if row else None,
        }

    @activity.defn
    async def finish_run(
        self,
        id: UUID,
        status: Literal["completed", "paused", "failed", "cancelled"],
        error: str | None,
    ) -> None:
        await agents.finish_run(self.s.db, id, status, error)

    @activity.defn
    async def deliver_input(self, message: Message) -> dict[str, JSON]:
        try:
            target = await get_agent(self.s.db, message.recipient_agent_id)
            if (
                target["state"] != "active"
                or target["box_id"]
                and target["box_state"] != "active"
            ):
                return {"skipped": True}
            return await deliver(self.s, message)
        except WorkflowUpdateFailedError as error:
            if (
                isinstance(error.cause, ApplicationError)
                and error.cause.type == "admission_closed"
            ):
                raise ApplicationError(
                    "retry admission in current execution", type="rotation"
                ) from error
            raise

    @activity.defn
    async def prepare_leta(self, creation: RootCreation) -> dict[str, JSON]:
        return await agents.prepare(self.s.db, creation)

    @activity.defn
    async def provision_leta(self, creation: RootCreation) -> None:
        async with effect(self.s.db, creation.leta_id):
            agent = await get_agent(self.s.db, creation.leta_id)
            if agent["state"] not in ("provisioning", "active"):
                return
            await self.s.internal.CheckWorkspaceActive(
                platform.CheckWorkspaceActiveRequest(
                    workspace_id=str(creation.workspace_id)
                ),
                timeout=15,
            )
            await self.s.auth.write(
                [
                    relationship(
                        "agent",
                        creation.leta_id,
                        "workspace",
                        "workspace",
                        creation.workspace_id,
                    ),
                    relationship(
                        "workspace",
                        creation.workspace_id,
                        "agent",
                        "agent",
                        creation.leta_id,
                    ),
                    relationship(
                        "agent", creation.leta_id, "owner", "user", creation.owner_id
                    ),
                ]
            )
            await self.s.storage.CreateStorage(
                internal.CreateStorageRequest(
                    workspace_id=str(creation.workspace_id),
                    storage_id=str(creation.storage_id),
                    root_node_id=str(creation.root_node_id),
                    owner=fs.StorageOwnership(agent_id=str(creation.leta_id)),
                    name=creation.request.name,
                    visibility=fs.STORAGE_VISIBILITY_PRIVATE,
                    allow_blob_files=True,
                    allow_indexing=True,
                ),
                timeout=30,
            )
            async with self.s.db.connection() as conn:
                await conn.execute(
                    "UPDATE letas SET state='active' WHERE id=%s AND state='provisioning'",
                    (creation.leta_id,),
                )

    @activity.defn
    async def close_leta(self, id: UUID) -> None:
        async with self.s.db.connection() as conn:
            await conn.execute(
                "UPDATE letas SET state='deleting' WHERE id=%s AND state IN ('active','provisioning')",
                (id,),
            )

    @activity.defn
    async def set_leta_paused(self, command: ResourceOperation) -> None:
        async with self.s.db.connection() as conn, conn.transaction():
            await agents.gate(conn, command.id)
            saved = await agents.receipt(
                conn, str(command.id), "leta.control", command.request_id, command
            )
            if saved is not None:
                return
            await conn.execute(
                "UPDATE letas SET paused=%s WHERE id=%s",
                (command.action == "pause", command.id),
            )
            await agents.save_receipt(
                conn,
                str(command.id),
                "leta.control",
                command.request_id,
                command,
                {"paused": command.action == "pause"},
            )

    @activity.defn
    async def refresh_leta_agents(self, root: UUID) -> None:
        async with self.s.db.connection() as conn:
            rows = await (
                await conn.execute("SELECT id FROM agents WHERE leta_id=%s", (root,))
            ).fetchall()
        for row in rows:
            try:
                await self.s.temporal.get_workflow_handle(
                    f"agent/{row['id']}"
                ).execute_update("refresh_control")
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    raise

    @activity.defn
    async def provision_box(self, creation: BoxCreation) -> UUID:
        async with effect(self.s.db, creation.leta_id):
            root = await get_agent(self.s.db, creation.leta_id)
            if root["state"] != "active":
                raise ValueError("Leta is inactive")
            storage = await self.s.files.GetStorage(
                fs.StorageRequest(
                    workspace_id=str(root["workspace_id"]),
                    storage_id=str(root["storage_id"]),
                ),
                metadata=Actor("agent", creation.leta_id).metadata,
                timeout=15,
            )
            node = await self.s.files.CreateDirectories(
                fs.CreateDirectoriesRequest(
                    workspace_id=str(root["workspace_id"]),
                    storage_id=str(root["storage_id"]),
                    base=fs.NodeLocator(
                        node_id=storage.root_node_id, root_node_id=storage.root_node_id
                    ),
                    path=f".boxes/{creation.box_id}",
                ),
                metadata=Actor("agent", creation.leta_id).metadata,
                timeout=30,
            )
            return UUID(node.id)

    @activity.defn
    async def prepare_box(self, creation: BoxCreation, home: UUID) -> dict[str, JSON]:
        return await boxes.prepare(self.s.db, creation, home)

    @activity.defn
    async def close_box(self, id: UUID) -> None:
        async with self.s.db.connection() as conn, conn.transaction():
            row = await (
                await conn.execute("SELECT leta_id FROM boxes WHERE id=%s", (id,))
            ).fetchone()
            if row:
                await conn.execute(
                    "SELECT id FROM letas WHERE id=%s FOR UPDATE", (row["leta_id"],)
                )
                await conn.execute(
                    "UPDATE boxes SET state='deleting' WHERE id=%s AND state='active'",
                    (id,),
                )

    async def settle_agents(self, root: UUID, box: UUID | None = None) -> None:
        async with self.s.db.connection() as conn:
            ids = [
                cast(UUID, row["id"])
                for row in await (
                    await conn.execute(
                        "SELECT id FROM agents WHERE leta_id=%s AND (%s::uuid IS NULL OR box_id=%s)",
                        (root, box, box),
                    )
                ).fetchall()
            ]
            producers = await (
                await conn.execute(
                    "SELECT id FROM schedules WHERE (creator_agent_id=ANY(%s) OR target_agent_id=ANY(%s)) AND deleted_at IS NULL",
                    (ids, ids),
                )
            ).fetchall()
        for row in producers:
            try:
                await self.s.temporal.get_schedule_handle(
                    f"schedule/{row['id']}"
                ).delete()
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    raise
        async with self.s.db.connection() as conn:
            await conn.execute(
                "UPDATE schedules SET deleted_at=coalesce(deleted_at,now()) WHERE creator_agent_id=ANY(%s) OR target_agent_id=ANY(%s)",
                (ids, ids),
            )
            requests = await (
                await conn.execute(
                    "SELECT id,requester_agent_id FROM hitl_requests WHERE requester_agent_id=ANY(%s) AND (status='pending' OR (status='accepted' AND outcome IS NULL))",
                    (ids,),
                )
            ).fetchall()
        for row in requests:
            handle = self.s.temporal.get_workflow_handle(f"hitl/{row['id']}")
            try:
                await handle.execute_update(
                    "decide",
                    hitl.Decision(
                        request_id=cast(UUID, row["id"]),
                        actor=Actor("agent", root),
                        status="cancelled",
                        resolved_at=datetime.now().astimezone(),
                    ),
                )
            except WorkflowUpdateFailedError:
                request = await hitl.get(self.s.db, cast(UUID, row["id"]))
                if request["status"] == "pending":
                    raise
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    raise
        for id in ids:
            try:
                await self.s.temporal.get_workflow_handle(f"agent/{id}").execute_update(
                    "stop"
                )
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    raise
            async with self.s.db.connection() as conn:
                await conn.execute(
                    "SELECT pg_advisory_lock(hashtextextended(%s,2))", (str(id),)
                )
                await conn.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s,2))", (str(id),)
                )
            activity.heartbeat()

    async def archive_box(self, id: UUID) -> None:
        async with self.s.db.connection() as conn:
            box = await (
                await conn.execute("SELECT * FROM boxes WHERE id=%s", (id,))
            ).fetchone()
        if box is None or box["state"] == "archived":
            return
        root = await get_agent(self.s.db, cast(UUID, box["leta_id"]))
        await self.settle_agents(cast(UUID, box["leta_id"]), id)
        try:
            await self.s.files.TrashNode(
                fs.TrashNodeRequest(
                    workspace_id=str(root["workspace_id"]),
                    storage_id=str(root["storage_id"]),
                    target=fs.NodeLocator(node_id=str(box["home_node_id"])),
                    request_id=str(stable(id, "delete-home")),
                ),
                metadata=Actor("agent", cast(UUID, box["leta_id"])).metadata,
                timeout=30,
            )
        except grpc.aio.AioRpcError as error:
            if error.code() not in (
                grpc.StatusCode.NOT_FOUND,
                grpc.StatusCode.PERMISSION_DENIED,
            ):
                raise
        async with self.s.db.connection() as conn:
            await conn.execute("UPDATE boxes SET state='archived' WHERE id=%s", (id,))

    @activity.defn
    async def cleanup_box(self, id: UUID) -> None:
        async with self.s.db.connection() as conn:
            row = await (
                await conn.execute("SELECT leta_id FROM boxes WHERE id=%s", (id,))
            ).fetchone()
        if row:
            async with effect(self.s.db, cast(UUID, row["leta_id"])):
                await self.archive_box(id)

    @activity.defn
    async def cleanup_leta(self, id: UUID) -> None:
        # Producers are settled before taking the effect barrier used by grant activities.
        await self.settle_agents(id)
        async with effect(self.s.db, id):
            async with self.s.db.connection() as conn:
                await conn.execute(
                    "UPDATE boxes SET state='deleting' WHERE leta_id=%s AND state='active'",
                    (id,),
                )
                rows = await (
                    await conn.execute(
                        "SELECT id FROM boxes WHERE leta_id=%s AND state<>'archived'",
                        (id,),
                    )
                ).fetchall()
            for row in rows:
                await self.archive_box(cast(UUID, row["id"]))
            for filter in (
                RelationshipFilter(resource_type="agent", optional_resource_id=str(id)),
                RelationshipFilter(
                    resource_type="workspace",
                    optional_relation="agent",
                    optional_subject_filter=SubjectFilter(
                        subject_type="agent", optional_subject_id=str(id)
                    ),
                ),
            ):
                await cast(
                    Awaitable[DeleteRelationshipsResponse],
                    self.s.auth.stub.DeleteRelationships(
                        DeleteRelationshipsRequest(relationship_filter=filter),
                        metadata=self.s.auth.metadata,
                        timeout=15,
                    ),
                )
            async with self.s.db.connection() as conn:
                await conn.execute(
                    "UPDATE letas SET state='archived' WHERE id=%s", (id,)
                )

    @activity.defn(name="DeleteWorkspaceAgents")
    async def delete_workspace_agents(self, input: dict[str, str]) -> None:
        root_id = input.get("workspace_id") or input.get("WorkspaceID")
        if root_id is None:
            raise ValueError("workspace ID required")
        async with self.s.db.connection() as conn:
            rows = await (
                await conn.execute(
                    "UPDATE letas SET state='deleting' WHERE workspace_id=%s AND state<>'archived' RETURNING id",
                    (UUID(root_id),),
                )
            ).fetchall()
        for row in rows:
            await self.cleanup_leta(cast(UUID, row["id"]))

    @activity.defn
    async def open_hitl_request(self, request: hitl.OpenRequest) -> dict[str, JSON]:
        return await hitl.open_request(self.s.db, self.s.auth, request)

    @activity.defn
    async def resolve_hitl_request(self, decision: hitl.Decision) -> dict[str, JSON]:
        return await hitl.resolve(self.s.db, self.s.auth, decision)

    @activity.defn
    async def apply_hitl_outcome(self, id: UUID) -> dict[str, JSON]:
        return await hitl.apply(self.s.db, self.s.auth, self.s.files, id)

    @activity.defn
    async def save_schedule_change(
        self, change: schedules.CanonicalChange
    ) -> dict[str, JSON]:
        return await schedules.save(self.s.db, change)

    @activity.defn
    async def apply_native_schedule(
        self, change: schedules.CanonicalChange, result: dict[str, JSON]
    ) -> dict[str, JSON]:
        queue = self.s.config["dependencies"]["temporal"]["queues"]
        return await schedules.apply(
            self.s.db,
            self.s.temporal,
            queue["leta"],
            queue["leta_bridge"],
            change,
            result,
        )

    @activity.defn
    async def load_schedule_occurrence(
        self, id: UUID, nominal: datetime
    ) -> Message | None:
        value = await schedules.get(self.s.db, id)
        target = UUID(str(value["target_agent_id"]))
        message_id = stable(id, nominal.isoformat())
        async with self.s.db.connection() as conn:
            old = await (
                await conn.execute(
                    "SELECT * FROM agent_messages WHERE id=%s", (message_id,)
                )
            ).fetchone()
        if old is not None:
            return Message.model_validate({k: old[k] for k in Message.model_fields})
        if value["deleted_at"] is not None or value["paused"]:
            return None
        return Message(
            id=message_id,
            recipient_agent_id=target,
            source_kind="schedule",
            source_id=id,
            conversation_id=messages.conversation(target, "schedule", id),
            scheduled_at=nominal,
            content=str(value["content"]),
        )
