"""Short SQL transitions and remote human-request effects have separate retries."""

from uuid import UUID

from openlet.clients.workspace import WorkspaceClient
from openlet.errors import AppError
from openlet.rpc import Actor
from openlet.temporal import application_error
from openlet_api.workspace.v1 import workspace_pb2 as pb
from temporalio import activity
from temporalio.client import Client

from leta.domain import Lifecycle, fault
from leta.human import RequestResolution
from leta.store import Store
from leta.temporal.activities import AgentActivities
from leta.temporal.bridges import settle_hitl
from leta.temporal.human_types import (
    HumanRequestOutcome,
    HumanRequestRef,
    HumanRequestState,
    OpenHumanRequest,
    SettleHumanRequest,
)


class HumanActivities(AgentActivities):
    def __init__(self, store: Store, scopes: WorkspaceClient, temporal: Client):
        super().__init__(store, temporal)
        self.scopes = scopes

    @activity.defn
    async def open_hitl_request(self, value: OpenHumanRequest) -> HumanRequestState:
        try:
            row = (
                await self.store.create_request(
                    value.creation, timeout_seconds=value.timeout_seconds
                )
                if value.creation is not None
                else await self.store.get_request(value.leta_id, value.request_id)
            )
            return HumanRequestState.from_row(row)
        except AppError as error:
            raise application_error(
                error, fallback="HITL_FAILED", message=str(error)
            ) from error

    @activity.defn
    async def resolve_hitl_request(self, value: RequestResolution) -> HumanRequestState:
        try:
            return HumanRequestState.from_row(await self.store.resolve_request(value))
        except AppError as error:
            raise application_error(
                error, fallback="HITL_FAILED", message=str(error)
            ) from error

    @activity.defn
    async def save_hitl_outcome(self, value: HumanRequestOutcome) -> HumanRequestState:
        try:
            return HumanRequestState.from_row(
                await self.store.save_request_outcome(
                    value.leta_id, value.request_id, value.outcome
                )
            )
        except AppError as error:
            raise application_error(
                error, fallback="HITL_FAILED", message=str(error)
            ) from error

    @activity.defn
    async def grant_requested_access(self, ref: HumanRequestRef) -> dict:
        request = await self.store.get_request(ref.leta_id, ref.request_id)
        if not (
            request["kind"] == "approval"
            and request["status"] == "resolved"
            and request["decision"]["action"] == "accept"
            and request["decision"]["actor_user_id"] == str(request["approver_user_id"])
            and request["grantee_leta_id"] == ref.leta_id
        ):
            raise application_error(
                fault("FORBIDDEN", "request has no accepted resource-owner decision"),
                fallback="HITL_FAILED",
                message="request has no accepted resource-owner decision",
            )
        if request["outcome"] is not None:
            return request["outcome"]
        try:
            root = await self.store.get_agent(ref.leta_id, ref.leta_id)
            resource = request["resource"]
            owner_id = str(request["approver_user_id"])
            if (
                resource.get("type") != "personal_scope"
                or resource.get("user_id") != owner_id
            ):
                raise fault("VALIDATION", "invalid personal resource", "invalid")
            scope_id = str(UUID(resource["scope_id"]))
            role = request["requested_role"]
            sufficient = False
            if root["status"] == Lifecycle.ACTIVE:
                try:
                    resolved = await self.scopes.resolve_personal_scope(
                        str(root["workspace_id"]),
                        owner_id,
                        actor=Actor("leta", ref.leta_id),
                    )
                    if resolved.scope_id != scope_id:
                        raise fault(
                            "RESOURCE_CHANGED", "personal scope mapping changed"
                        )
                    sufficient = await has_scope_access(
                        self.scopes, root, scope_id, role
                    )
                except AppError as error:
                    if error.retryable:
                        raise
                    # Workspace recovers an applied key before lifecycle rejection.
                    # Reusing that command also revalidates any unapplied grant.
            if not sufficient:
                result = await self.scopes.change_scope_access(
                    pb.ChangeScopeAccessRequest(
                        workspace_id=str(root["workspace_id"]),
                        scope_id=scope_id,
                        grantee_kind="leta",
                        grantee_id=str(ref.leta_id),
                        role=role,
                        idempotency_key=str(request["grant_key"]),
                        personal_owner_user_id=owner_id,
                    ),
                    actor=Actor("user", UUID(owner_id)),
                )
                if not result.rights.read_content or (
                    role == "editor" and not result.rights.write
                ):
                    raise fault(
                        "GRANT_NOT_EFFECTIVE", "Workspace did not acknowledge access"
                    )
            return {
                "granted": True,
                "scope_id": scope_id,
                "role": role,
                "mount_path": f"/users/{owner_id}",
            }
        except AppError as error:
            if error.retryable:
                raise
            return {"granted": False, "reason": error.reason, "error": str(error)}

    @activity.defn
    async def settle_hitl(self, value: SettleHumanRequest) -> HumanRequestState:
        return await settle_hitl(self.temporal, value)

    def registered(self):
        return [
            self.open_hitl_request,
            self.resolve_hitl_request,
            self.save_hitl_outcome,
            self.grant_requested_access,
            self.settle_hitl,
        ]


async def has_scope_access(scopes, root, scope_id: str, role: str) -> bool:
    """Current Workspace discovery, never a previous accepted request, proves access."""
    cursor, seen = None, set()
    while True:
        page = await scopes.list_accessible_scopes(
            str(root["workspace_id"]),
            actor=Actor("leta", root["id"]),
            limit=100,
            cursor=cursor,
        )
        for scope in page.items:
            if scope.id == scope_id:
                return scope.rights.read_content and (
                    role == "viewer" or scope.rights.write
                )
        if not page.HasField("next_cursor"):
            return False
        if page.next_cursor in seen:
            raise ValueError("scope discovery cursor cycle")
        cursor = page.next_cursor
        seen.add(cursor)
