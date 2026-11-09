import asyncio
from contextlib import contextmanager
from datetime import timedelta

from authzed.api.v1 import (
    ObjectReference,
    Relationship,
    RelationshipUpdate,
    SubjectReference,
    WriteRelationshipsRequest,
)
from openlet.clients.letfs import FilesystemClient, Locator
from openlet.clients.workspace import WorkspaceClient
from openlet.errors import AppError
from openlet.rpc import Actor
from openlet.temporal import application_error
from temporalio import activity
from temporalio.client import Client, WithStartWorkflowOperation
from temporalio.common import WorkflowIDConflictPolicy

from leta.domain import Lifecycle, box_slug, fault
from leta.filesystem.workspace import discover_mounts
from leta.store import Store
from leta.temporal.agent import AgentWorkflow
from leta.temporal.bridges import start_agent
from leta.temporal.lifecycle_types import (
    BoxChange,
    LetaChange,
    LifecycleAgentControl,
    LifecycleSnapshot,
    ResourceRef,
)
from leta.temporal.types import ORCHESTRATION_QUEUE, AgentRef, AgentStart


@contextmanager
def activity_errors():
    try:
        yield
    except AppError as error:
        raise application_error(
            error, fallback="LIFECYCLE_FAILED", message=str(error)
        ) from error


def leta_resource_updates(root, *, remove=False):
    return [
        RelationshipUpdate(
            operation=RelationshipUpdate.OPERATION_DELETE
            if remove
            else RelationshipUpdate.OPERATION_TOUCH,
            relationship=Relationship(
                resource=ObjectReference(object_type="leta", object_id=str(root["id"])),
                relation=relation,
                subject=SubjectReference(
                    object=ObjectReference(
                        object_type=kind, object_id=str(root[column])
                    )
                ),
            ),
        )
        for relation, kind, column in (
            ("workspace", "workspace", "workspace_id"),
            ("creator", "user", "created_by_user_id"),
        )
    ]


class LifecycleActivities:
    def __init__(
        self,
        store: Store,
        scopes: WorkspaceClient,
        native: FilesystemClient,
        graph,
        temporal: Client,
    ):
        self.store, self.scopes, self.native = store, scopes, native
        self.graph, self.temporal = graph, temporal

    @activity.defn
    async def save_leta_change(self, value: LetaChange) -> LifecycleSnapshot:
        with activity_errors():
            snapshot = {}
            if value.action == "create":
                root = await self.store.create_leta(value.creation)
            elif value.action == "configure":
                await self.store.configure_agent(
                    value.leta_id, value.agent_id or value.leta_id, value.configuration
                )
                root = await self.store.get_agent(value.leta_id, value.leta_id)
            elif value.action in {"pause", "resume"}:
                snapshot = await self.store.set_paused(
                    value.leta_id, value.action == "pause"
                )
                root = await self.store.get_agent(value.leta_id, value.leta_id)
            elif value.action == "active":
                root = await self.store.activate_leta(value.leta_id)
            elif value.action == "deleting":
                snapshot = await self.store.begin_delete(value.leta_id)
                root = await self.store.get_agent(value.leta_id, value.leta_id)
            else:
                await self.store.archive(value.leta_id)
                root = await self.store.get_agent(value.leta_id, value.leta_id)
            return LifecycleSnapshot(
                leta_id=value.leta_id, status=root["status"], **snapshot
            )

    @activity.defn
    async def save_box_change(self, value: BoxChange) -> LifecycleSnapshot:
        with activity_errors():
            snapshot = {}
            if value.action == "create":
                box = await self.store.create_box(value.creation)
            elif value.action == "active":
                box = await self.store.activate_box(value.leta_id, value.box_id)
            elif value.action == "deleting":
                snapshot = await self.store.begin_delete(value.leta_id, value.box_id)
                box = await self.store.get_box(value.leta_id, value.box_id)
            else:
                await self.store.archive(value.leta_id, value.box_id)
                box = await self.store.get_box_graph(value.leta_id, value.box_id)
            if "agent_ids" not in snapshot:
                graph = (
                    box
                    if value.action == "archived"
                    else await self.store.get_box_graph(value.leta_id, value.box_id)
                )
                snapshot["agent_ids"] = [agent["id"] for agent in graph["letis"]]
            return LifecycleSnapshot(
                leta_id=value.leta_id,
                box_id=value.box_id,
                status=box["status"],
                **snapshot,
            )

    @activity.defn
    async def publish_leta_resource(self, ref: ResourceRef) -> None:
        with activity_errors():
            root = await self.store.get_agent(ref.leta_id, ref.leta_id)
            if ref.remove:
                await self.scopes.get_cleanup_workspace(
                    str(root["workspace_id"]), str(ref.leta_id)
                )
            elif root["status"] not in {Lifecycle.INITIALIZING, Lifecycle.ACTIVE}:
                raise fault("RESOURCE_INACTIVE", "Leta cannot publish access")
            updates = leta_resource_updates(root, remove=ref.remove)
            await self.graph.WriteRelationships(
                WriteRelationshipsRequest(updates=updates),
                metadata=getattr(self.graph, "_openlet_metadata", ()),
                timeout=5,
            )

    @activity.defn
    async def ensure_leta_home(self, ref: ResourceRef) -> None:
        with activity_errors():
            root = await self.store.get_agent(ref.leta_id, ref.leta_id)
            if root["status"] not in {Lifecycle.INITIALIZING, Lifecycle.ACTIVE}:
                raise fault("RESOURCE_INACTIVE", "Leta cannot provision a home")
            try:
                await self.scopes.ensure_leta_home_access(
                    str(root["workspace_id"]),
                    str(ref.leta_id),
                    str(root["home_scope_id"]),
                    str(root["home_scope_id"]),
                    actor=Actor("user", root["created_by_user_id"]),
                )
            except AppError as error:
                if error.retryable or error.kind not in {
                    "conflict",
                    "forbidden",
                    "missing",
                }:
                    raise
                try:
                    await self.scopes.get_cleanup_workspace(
                        str(root["workspace_id"]), str(ref.leta_id)
                    )
                except AppError as lookup_error:
                    if lookup_error.retryable:
                        raise
                    raise error
                raise fault("WORKSPACE_DELETING", "workspace is deleting") from error

    @activity.defn
    async def cleanup_leta_access(self, ref: ResourceRef) -> None:
        with activity_errors():
            root = await self.store.get_agent(ref.leta_id, ref.leta_id)
            if root["status"] not in {Lifecycle.DELETING, Lifecycle.ARCHIVED}:
                raise fault("RESOURCE_INACTIVE", "close Leta before cleaning access")
            if ref.remove:
                await self.scopes.get_cleanup_workspace(
                    str(root["workspace_id"]), str(ref.leta_id)
                )
            await self.scopes.cleanup_leta_access(
                str(root["workspace_id"]),
                str(ref.leta_id),
                str(root["home_scope_id"]),
                actor=None if ref.remove else Actor("user", root["created_by_user_id"]),
            )

    async def box_home(self, ref: ResourceRef):
        root = await self.store.get_agent(ref.leta_id, ref.leta_id)
        box = await self.store.get_box(ref.leta_id, ref.box_id)
        mounts = await discover_mounts(
            self.scopes,
            root["workspace_id"],
            Actor("leta", ref.leta_id),
            root["home_scope_id"],
        )
        return root, box, next(mount for mount in mounts if mount.prefix == "/home")

    @activity.defn
    async def ensure_box_home(self, ref: ResourceRef) -> None:
        with activity_errors():
            root, box, home = await self.box_home(ref)
            if root["status"] != Lifecycle.ACTIVE or box["status"] not in {
                Lifecycle.INITIALIZING,
                Lifecycle.ACTIVE,
            }:
                raise fault("RESOURCE_INACTIVE", "box cannot provision a home")
            actor = Actor("leta", ref.leta_id)
            parent = await self.native.create_directories(
                home.filesystem_id,
                home.scope_id,
                Locator(node_id=home.root_id),
                [".leti"],
                parents=True,
                actor=actor,
            )
            name = box_slug(box["name"])
            try:
                node = (
                    await self.native.stat(
                        home.filesystem_id,
                        home.scope_id,
                        Locator(node_id=str(box["home_node_id"])),
                        actor=actor,
                    )
                ).node
            except AppError as error:
                if error.kind != "missing":
                    raise
                node = await self.native.create_directory(
                    home.filesystem_id,
                    home.scope_id,
                    Locator(node_id=parent.id, expected_parent_id=parent.id),
                    name,
                    str(box["home_node_id"]),
                    node_id=str(box["home_node_id"]),
                    actor=actor,
                )
            if (
                node.kind != "directory"
                or node.parent_id != parent.id
                or node.name != name
            ):
                raise fault("STATE_CONFLICT", "reserved box home identity differs")

    @activity.defn
    async def trash_box_home(self, ref: ResourceRef) -> None:
        with activity_errors():
            _, box, home = await self.box_home(ref)
            if box["status"] not in {Lifecycle.DELETING, Lifecycle.ARCHIVED}:
                raise fault("RESOURCE_INACTIVE", "close box before trashing home")
            actor = Actor("leta", ref.leta_id)
            try:
                node = (
                    await self.native.stat(
                        home.filesystem_id,
                        home.scope_id,
                        Locator(node_id=str(box["home_node_id"])),
                        actor=actor,
                    )
                ).node
                await self.native.trash_node(
                    home.filesystem_id,
                    home.scope_id,
                    Locator(
                        node_id=str(box["home_node_id"]),
                        expected_node_id=str(box["home_node_id"]),
                    ),
                    actor=actor,
                    revision=node.revision,
                )
                return
            except AppError as error:
                if error.kind != "missing":
                    raise
            cursor = None
            while True:
                entries, cursor = await self.native.list_trash(
                    home.filesystem_id,
                    home.scope_id,
                    actor=actor,
                    limit=100,
                    cursor=cursor,
                )
                if any(entry.node_id == str(box["home_node_id"]) for entry in entries):
                    return
                if cursor is None:
                    raise fault(
                        "STATE_CONFLICT",
                        "reserved box home is missing from live files and trash",
                    )

    @activity.defn(name="start_agent")
    async def start_agent(self, ref: AgentRef) -> None:
        with activity_errors():
            current = await self.store.bootstrap_agent(ref.leta_id, ref.agent_id)
            if (
                any(
                    current[key] in {Lifecycle.DELETING, Lifecycle.ARCHIVED}
                    for key in ("status", "root_status", "box_status")
                )
                or current["status"] != Lifecycle.ACTIVE
            ):
                raise fault("RESOURCE_INACTIVE", "agent cannot start")
            await start_agent(
                self.temporal,
                AgentStart(
                    leta_id=ref.leta_id, agent_id=ref.agent_id, paused=current["paused"]
                ),
            )

    @activity.defn(name="control_agent")
    async def control_agent(self, value: LifecycleAgentControl) -> None:
        with activity_errors():
            current = await self.store.bootstrap_agent(value.leta_id, value.agent_id)
            if value.control.action != "stop" and any(
                current[key] in {Lifecycle.DELETING, Lifecycle.ARCHIVED}
                for key in ("status", "root_status", "box_status")
            ):
                return
            operation = WithStartWorkflowOperation(
                AgentWorkflow.run,
                AgentStart(leta_id=value.leta_id, agent_id=value.agent_id),
                id=f"agent/{value.agent_id}",
                task_queue=ORCHESTRATION_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            )

            async def heartbeat():
                while True:
                    activity.heartbeat()
                    await asyncio.sleep(1)

            pulse = asyncio.create_task(heartbeat())
            try:
                await self.temporal.execute_update_with_start_workflow(
                    AgentWorkflow.control,
                    value.control,
                    start_workflow_operation=operation,
                    rpc_timeout=timedelta(seconds=90),
                )
            finally:
                pulse.cancel()
                await asyncio.gather(pulse, return_exceptions=True)

    def registered(self):
        return [
            self.save_leta_change,
            self.save_box_change,
            self.publish_leta_resource,
            self.ensure_leta_home,
            self.cleanup_leta_access,
            self.ensure_box_home,
            self.trash_box_home,
            self.start_agent,
            self.control_agent,
        ]
