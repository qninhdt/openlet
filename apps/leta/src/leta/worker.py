import asyncio
import logging
import signal
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timedelta
from typing import Literal, TypeVar, cast
from uuid import UUID

import grpc
from langfuse import Langfuse
from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_api.platform.v1 import internal_pb2 as platform
from openlet_sdk.config import JSON, load
from openlet_sdk.telemetry import initialize, initialize_langfuse
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from temporalio import activity
from temporalio.client import WithStartWorkflowOperation, WorkflowUpdateFailedError
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.runtime import (
    LogForwardingConfig,
    LoggingConfig,
    OpenTelemetryConfig,
    Runtime,
    TelemetryConfig,
    TelemetryFilter,
)
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import Worker

from . import agents, boxes, events, hitl, messages, schedules
from .agents import RootCreation, get_agent, stable
from .auth import Actor, relationship
from .boxes import BoxCreation
from .config import Services, connect, validate
from .db import Row, effect, receipt, request_hash
from .jobs.agent import Agent, AgentInput, RunInput, RunResult
from .jobs.hitl import HitlInput, HitlRequest
from .jobs.resources import BoxLifecycle, LetaLifecycle, ResourceOperation
from .jobs.schedules import ScheduleChanges, ScheduleDelivery, ScheduleInput
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
    return await s.temporal.execute_update_with_start_workflow(  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
        Agent.receive,
        message,
        id=request_hash(message).hex(),
        start_workflow_operation=start,
    )


async def submit_hitl(s: Services, request: hitl.OpenRequest) -> dict[str, JSON]:
    queues = s.config["dependencies"]["temporal"]["queues"]
    start: WithStartWorkflowOperation[HitlRequest, None] = WithStartWorkflowOperation(
        HitlRequest.run,
        HitlInput(request=request, bridge_queue=queues["leta_bridge"]),
        id=f"hitl/{request.id}",
        task_queue=queues["leta"],
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    return await s.temporal.execute_update_with_start_workflow(  # pyright: ignore[reportUnknownMemberType]  # Temporal overload is untyped.
        HitlRequest.open,
        request,
        start_workflow_operation=start,
        id=request_hash(request).hex(),
    )


async def submit_schedule(s: Services, change: schedules.Change) -> dict[str, JSON]:
    queues = s.config["dependencies"]["temporal"]["queues"]
    start: WithStartWorkflowOperation[ScheduleChanges, None] = (
        WithStartWorkflowOperation(
            ScheduleChanges.run,
            ScheduleInput(
                schedule_id=change.schedule_id, bridge_queue=queues["leta_bridge"]
            ),
            id=f"schedule-changes/{change.schedule_id}",
            task_queue=queues["leta"],
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        )
    )
    return await s.temporal.execute_update_with_start_workflow(  # pyright: ignore[reportUnknownMemberType]  # Temporal overload is untyped.
        ScheduleChanges.change,
        change,
        start_workflow_operation=start,
        id=request_hash(change).hex(),
    )


T = TypeVar("T")


async def fanout(items: Iterable[T], action: Callable[[T], Awaitable[None]]) -> None:
    limit = asyncio.Semaphore(8)

    async def apply(item: T) -> None:
        async with limit:
            await action(item)

    # Settle all in-flight effects before the caller may retry the phase.
    results = await asyncio.gather(
        *(apply(item) for item in items), return_exceptions=True
    )
    for result in results:
        if isinstance(result, BaseException):
            raise result


async def operation(
    s: Services, command: ResourceOperation, *, wait: bool = False
) -> dict[str, JSON]:
    async with s.db.connection() as conn:
        saved = None
        if command.root is not None:
            saved = await receipt(
                conn,
                f"user:{command.root.owner_id}",
                "leta.create",
                command.request_id,
                command.root,
            )
        elif command.box is not None:
            saved = await receipt(
                conn,
                f"agent:{command.box.leta_id}",
                "box.create",
                command.request_id,
                command.box.request,
            )
        elif command.action in ("pause", "resume"):
            saved = await receipt(
                conn, str(command.id), "leta.control", command.request_id, command
            )
    if saved is not None:
        return cast(dict[str, JSON], saved)
    is_box = command.box is not None or command.action == "delete_box"
    type = BoxLifecycle if is_box else LetaLifecycle
    action = "delete" if command.action == "delete_box" else command.action
    id = f"{'box' if is_box else 'leta'}/{command.id}/{action}"
    if command.root is not None:
        id = f"leta/create/{command.root.owner_id}/{command.request_id}"
    if action in ("pause", "resume"):
        id = f"leta/{command.id}/control/{command.request_id}"
    try:
        handle = await s.temporal.start_workflow(
            type.run,
            command,
            id=id,
            task_queue=s.config["dependencies"]["temporal"]["queues"]["leta"],
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        handle = s.temporal.get_workflow_handle(id, result_type=dict[str, JSON])
    try:
        result = await handle.execute_update(  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
            "open", command, result_type=dict[str, JSON]
        )
    except RPCError as error:
        if error.status != RPCStatusCode.NOT_FOUND:
            raise
        return cast(dict[str, JSON], await handle.result())
    return (
        cast(dict[str, JSON], await handle.result()) if wait and not is_box else result
    )


@asynccontextmanager
async def pulsing() -> AsyncGenerator[None]:
    async def pulse() -> None:
        while True:
            activity.heartbeat()
            await asyncio.sleep(2)

    task = asyncio.create_task(pulse())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class Activities:
    def __init__(self, services: Services, langfuse: Langfuse) -> None:
        self.s, self.langfuse = services, langfuse

    @activity.defn
    async def run_agent(self, input: RunInput) -> RunResult:
        from .runtime.agent import run

        return await run(self.s, self.langfuse, input)

    @activity.defn
    async def admit_input(self, message: Message) -> dict[str, JSON]:
        return await messages.admit(self.s.db, self.s.auth, message)

    @activity.defn
    async def load_agent_control(self, id: UUID) -> dict[str, JSON]:
        async with self.s.db.connection() as conn:
            row = await (
                await conn.execute(
                    """SELECT l.state,l.paused,b.state AS box_state,a.box_id,r.id AS run_id
                FROM agents a JOIN letas l ON l.id=a.leta_id LEFT JOIN boxes b ON b.id=a.box_id
                LEFT JOIN runs r ON r.agent_id=a.id AND r.status IN ('running','paused') WHERE a.id=%s""",
                    (id,),
                )
            ).fetchone()
        if row is None:
            raise LookupError("agent not found")
        return {
            "active": row["state"] == "active"
            and (row["box_id"] is None or row["box_state"] == "active"),
            "paused": bool(row["paused"]),
            "run_id": str(row["run_id"]) if row["run_id"] else None,
        }

    @activity.defn
    async def finish_run(
        self,
        id: UUID,
        status: Literal["completed", "paused", "failed", "cancelled"],
        error: str | None,
    ) -> None:
        row = await agents.finish_run(self.s.db, id, status, error)
        if status != "paused":
            if row:
                await events.publish(
                    self.s.redis,
                    cast(UUID, row["leta_id"]),
                    events.event(
                        "RUN_ERROR" if status == "failed" else "RUN_FINISHED",
                        cast(UUID, row["agent_id"]),
                        id,
                        **(
                            {
                                "message": error or "runtime failed",
                                "code": error or "runtime_error",
                            }
                            if status == "failed"
                            else {"threadId": str(row["agent_id"]), "runId": str(id)}
                        ),
                    ),
                )

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
                await conn.execute(
                    "SELECT a.id FROM agents a LEFT JOIN boxes b ON b.id=a.box_id WHERE a.leta_id=%s AND (a.box_id IS NULL OR b.state='active')",
                    (root,),
                )
            ).fetchall()

        async def refresh(row: Row) -> None:
            try:
                await self.s.temporal.get_workflow_handle(  # pyright: ignore[reportUnknownMemberType]  # Temporal has an untyped overload for args.
                    f"agent/{row['id']}"
                ).execute_update("refresh_control")
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    raise

        await fanout(rows, refresh)

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
                await conn.execute(
                    "SELECT leta_id FROM boxes WHERE id=%s",
                    (id,),
                )
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
                        "SELECT a.id FROM agents a LEFT JOIN boxes b ON b.id=a.box_id WHERE a.leta_id=%s AND (a.box_id IS NULL OR b.state<>'archived') AND (%s::uuid IS NULL OR box_id=%s)",
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

        async def remove_producer(row: Row) -> None:
            try:
                await self.s.temporal.get_schedule_handle(
                    f"schedule/{row['id']}"
                ).delete()
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    raise

        await fanout(producers, remove_producer)
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

        async def settle_request(row: Row) -> None:
            handle = self.s.temporal.get_workflow_handle(f"hitl/{row['id']}")
            try:
                await handle.execute_update("settle_effects")  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
            except WorkflowUpdateFailedError:
                request = await hitl.get(self.s.db, cast(UUID, row["id"]))
                if request["status"] == "pending":
                    raise
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    raise

        await fanout(requests, settle_request)

        async def settle_writer(id: UUID) -> None:
            try:
                handle = self.s.temporal.get_workflow_handle(f"agent/{id}")
                await handle.execute_update("stop")  # pyright: ignore[reportUnknownMemberType]  # Temporal has an untyped overload for args.
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

        await fanout(ids, settle_writer)

    async def archive_box(self, box: Row) -> None:
        id = cast(UUID, box["id"])
        try:
            await self.s.files.TrashNode(
                fs.TrashNodeRequest(
                    workspace_id=str(box["workspace_id"]),
                    storage_id=str(box["storage_id"]),
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
        async with pulsing():
            async with self.s.db.connection() as conn:
                row = await (
                    await conn.execute(
                        "SELECT b.*,l.workspace_id,l.storage_id FROM boxes b JOIN letas l ON l.id=b.leta_id WHERE b.id=%s AND b.state<>'archived'",
                        (id,),
                    )
                ).fetchone()
            if row:
                await self.settle_agents(cast(UUID, row["leta_id"]), id)
                async with effect(self.s.db, cast(UUID, row["leta_id"])):
                    await self.archive_box(row)

    @activity.defn
    async def cleanup_leta(self, id: UUID) -> None:
        async with pulsing():
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
                            "SELECT b.*,l.workspace_id,l.storage_id FROM boxes b JOIN letas l ON l.id=b.leta_id WHERE b.leta_id=%s AND b.state<>'archived'",
                            (id,),
                        )
                    ).fetchall()
                await fanout(rows, self.archive_box)
                root = await get_agent(self.s.db, id)
                workspace = cast(UUID, root["workspace_id"])
                await self.s.auth.write(
                    [
                        relationship("agent", id, "workspace", "workspace", workspace),
                        relationship("workspace", workspace, "agent", "agent", id),
                    ],
                    delete=True,
                )
                async with self.s.db.connection() as conn:
                    await conn.execute(
                        "UPDATE letas SET state='archived' WHERE id=%s", (id,)
                    )

    @activity.defn(name="DeleteWorkspaceAgents")
    async def delete_workspace_agents(self, input: dict[str, str]) -> None:
        async with pulsing():
            root_id = input["workspace_id"]
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
        return await hitl.open_request(self.s.db, self.s.auth, self.s.files, request)

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


async def main() -> None:
    config = load()
    validate(config)
    shutdown = initialize("openlet-leta-worker", config["runtime"], config["telemetry"])
    PsycopgInstrumentor().instrument()
    RedisInstrumentor().instrument()  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    telemetry = config["telemetry"]
    native = Runtime(
        telemetry=TelemetryConfig(
            logging=LoggingConfig(
                TelemetryFilter(core_level="WARN", other_level="ERROR"),
                forwarding=LogForwardingConfig(logging.getLogger("temporalio.core")),
            ),
            metrics=OpenTelemetryConfig(
                url=telemetry["otlp_endpoint"],
                durations_as_seconds=True,
                metric_periodicity=timedelta(
                    seconds=telemetry["metrics_export_interval_seconds"]
                ),
            )
            if telemetry["otlp_endpoint"]
            else None,
            global_tags={
                "service.name": "openlet-leta-worker",
                "worker_role": "leta",
                "deployment.environment.name": config["runtime"]["environment"],
            },
        )
    )
    try:
        async with AsyncExitStack() as stack:
            lf_settings = config.get("langfuse")
            if lf_settings is None:
                raise ValueError("Langfuse settings are required for Leta prompts")
            lf = initialize_langfuse(lf_settings, config["runtime"])
            stack.callback(lf.shutdown)
            services = await stack.enter_async_context(connect(config, native=native))
            activities = Activities(services, lf)
            queues = config["dependencies"]["temporal"]["queues"]
            graceful = timedelta(seconds=config["runtime"]["shutdown_timeout_seconds"])
            await stack.enter_async_context(
                Worker(
                    services.temporal,
                    task_queue=queues["leta"],
                    workflows=[
                        Agent,
                        LetaLifecycle,
                        BoxLifecycle,
                        HitlRequest,
                        ScheduleChanges,
                        ScheduleDelivery,
                    ],
                    activities=[
                        activities.admit_input,
                        activities.load_agent_control,
                        activities.finish_run,
                        activities.prepare_leta,
                        activities.provision_leta,
                        activities.close_leta,
                        activities.set_leta_paused,
                        activities.provision_box,
                        activities.prepare_box,
                        activities.close_box,
                        activities.open_hitl_request,
                        activities.resolve_hitl_request,
                        activities.apply_hitl_outcome,
                        activities.save_schedule_change,
                        activities.apply_native_schedule,
                        activities.load_schedule_occurrence,
                    ],
                    max_concurrent_activities=8,
                    graceful_shutdown_timeout=graceful,
                )
            )
            await stack.enter_async_context(
                Worker(
                    services.temporal,
                    task_queue=queues["leta_runtime"],
                    activities=[activities.run_agent],
                    max_concurrent_activities=4,
                    graceful_shutdown_timeout=graceful,
                )
            )
            await stack.enter_async_context(
                Worker(
                    services.temporal,
                    task_queue=queues["leta_bridge"],
                    activities=[
                        activities.deliver_input,
                        activities.refresh_leta_agents,
                        activities.cleanup_box,
                        activities.cleanup_leta,
                        activities.delete_workspace_agents,
                    ],
                    max_concurrent_activities=8,
                    graceful_shutdown_timeout=graceful,
                )
            )
            logging.getLogger(__name__).info("Leta workers started")
            await stop.wait()
    finally:
        shutdown()


if __name__ == "__main__":
    asyncio.run(main())
