"""Typed Workspace RPCs with explicit, trusted runtime actors."""

from uuid import UUID

from openlet.rpc import Actor, RpcClient
from openlet_api.workspace.v1 import workspace_pb2 as pb
from openlet_api.workspace.v1.workspace_pb2_grpc import WorkspaceServiceStub


def _id(value: str) -> str:
    if not value or UUID(value).int == 0:
        raise ValueError("nonzero UUID required")
    return str(UUID(value))


def _page(limit: int, cursor: str | None, maximum: int = 2048):
    if not 1 <= limit <= 100 or (cursor is not None and not 0 < len(cursor) <= maximum):
        raise ValueError("invalid Workspace page")


def _workspace(value: pb.Workspace, workspace_id: str):
    if (
        value.id != workspace_id
        or not _id(value.filesystem_id)
        or not _id(value.shared_scope_id)
        or value.status not in {"initializing", "active", "deleting", "deleted"}
    ):
        raise ValueError("invalid Workspace response")


class WorkspaceClient:
    def __init__(self, rpc: RpcClient):
        self._rpc = rpc
        self._stub = WorkspaceServiceStub(rpc.channel)

    async def get_workspace(self, workspace_id: str, *, actor: Actor) -> pb.Workspace:
        workspace_id = _id(workspace_id)
        result = await self._rpc.invoke(
            self._stub.GetWorkspace,
            pb.GetWorkspaceRequest(workspace_id=workspace_id),
            actor=actor,
            timeout=15,
        )
        value = result.workspace
        _workspace(value, workspace_id)
        if value.status != "active" or (
            actor.kind == "leta"
            and (value.HasField("role") or value.HasField("personal_scope_id"))
        ):
            raise ValueError("invalid runtime Workspace response")
        if actor.kind == "user" and (
            value.role not in {"owner", "admin", "member"}
            or not _id(value.personal_scope_id)
        ):
            raise ValueError("invalid human Workspace response")
        return value

    async def get_cleanup_workspace(
        self, workspace_id: str, leta_id: str
    ) -> pb.Workspace:
        workspace_id = _id(workspace_id)
        result = await self._rpc.invoke(
            self._stub.GetWorkspace,
            pb.GetWorkspaceRequest(
                workspace_id=workspace_id, cleanup_leta_id=_id(leta_id)
            ),
            timeout=15,
        )
        value = result.workspace
        _workspace(value, workspace_id)
        if (
            value.status not in {"deleting", "deleted"}
            or value.name
            or value.HasField("role")
            or value.HasField("personal_scope_id")
        ):
            raise ValueError("invalid cleanup Workspace response")
        return value

    async def list_members(
        self,
        workspace_id: str,
        *,
        actor: Actor,
        limit: int = 100,
        cursor: str | None = None,
    ) -> pb.ListMembersResponse:
        workspace_id = _id(workspace_id)
        _page(limit, cursor, 36)
        previous = UUID(_id(cursor)).int if cursor is not None else 0
        request = pb.ListMembersRequest(workspace_id=workspace_id, limit=limit)
        if cursor is not None:
            request.cursor = cursor
        result = await self._rpc.invoke(
            self._stub.ListMembers, request, actor=actor, timeout=15
        )
        if result.workspace_id != workspace_id or len(result.items) > limit:
            raise ValueError("invalid member page")
        for item in result.items:
            current = UUID(_id(item.user.id)).int
            _id(item.personal_scope_id)
            if current <= previous or item.role not in {"owner", "admin", "member"}:
                raise ValueError("invalid member response")
            previous = current
        if result.HasField("next_cursor") and (
            not result.items or result.next_cursor != result.items[-1].user.id
        ):
            raise ValueError("invalid member continuation")
        return result

    async def list_accessible_scopes(
        self,
        workspace_id: str,
        *,
        actor: Actor,
        leta_id: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> pb.ListAccessibleScopesResponse:
        workspace_id = _id(workspace_id)
        _page(limit, cursor)
        request = pb.ListAccessibleScopesRequest(workspace_id=workspace_id, limit=limit)
        if cursor is not None:
            request.cursor = cursor
        subject_kind, subject_id = actor.kind, str(actor.id)
        if leta_id is not None:
            if actor.kind != "user":
                raise ValueError("Leta inspection requires a human actor")
            subject_kind, subject_id = "leta", _id(leta_id)
            request.leta_id = subject_id
        result = await self._rpc.invoke(
            self._stub.ListAccessibleScopes, request, actor=actor, timeout=20
        )
        _id(result.filesystem_id)
        if (
            result.workspace_id != workspace_id
            or result.subject_kind != subject_kind
            or result.subject_id != subject_id
            or len(result.items) > limit
        ):
            raise ValueError("invalid scope page identity")
        previous, roots = 0, set()
        for item in result.items:
            current, root = UUID(_id(item.id)).int, _id(item.root_id)
            if current <= previous or root in roots or not item.rights.read_metadata:
                raise ValueError("invalid visible scope")
            previous = current
            roots.add(root)
            if item.kind == "personal":
                _id(item.owner.id)
            elif item.kind not in {"scope", "shared", "home"} or item.HasField("owner"):
                raise ValueError("invalid scope kind/owner")
        if result.HasField("next_cursor") and (
            not 0 < len(result.next_cursor) <= 2048 or result.next_cursor == cursor
        ):
            raise ValueError("invalid scope continuation")
        return result

    async def ensure_leta_home_access(
        self,
        workspace_id: str,
        leta_id: str,
        home_scope_id: str,
        idempotency_key: str,
        *,
        actor: Actor,
    ) -> pb.EnsureLetaHomeAccessResponse:
        if actor.kind != "user":
            raise ValueError("home provisioning requires the creator actor")
        workspace_id, home_scope_id = _id(workspace_id), _id(home_scope_id)
        result = await self._rpc.invoke(
            self._stub.EnsureLetaHomeAccess,
            pb.EnsureLetaHomeAccessRequest(
                workspace_id=workspace_id,
                leta_id=_id(leta_id),
                home_scope_id=home_scope_id,
                idempotency_key=_id(idempotency_key),
            ),
            actor=actor,
            timeout=60,
        )
        _id(result.filesystem_id)
        if result.workspace_id != workspace_id or result.home_scope_id != home_scope_id:
            raise ValueError("invalid home response")
        return result

    async def resolve_personal_scope(
        self, workspace_id: str, owner_user_id: str, *, actor: Actor
    ) -> pb.ResolvePersonalScopeResponse:
        if actor.kind != "leta":
            raise ValueError("personal resolution requires the root Leta actor")
        workspace_id, owner_user_id = _id(workspace_id), _id(owner_user_id)
        result = await self._rpc.invoke(
            self._stub.ResolvePersonalScope,
            pb.ResolvePersonalScopeRequest(
                workspace_id=workspace_id, owner_user_id=owner_user_id
            ),
            actor=actor,
            timeout=15,
        )
        _id(result.filesystem_id)
        _id(result.scope_id)
        if result.workspace_id != workspace_id or result.owner_user_id != owner_user_id:
            raise ValueError("invalid personal owner response")
        return result

    async def change_scope_access(
        self, request: pb.ChangeScopeAccessRequest, *, actor: Actor
    ) -> pb.ChangeScopeAccessResponse:
        for value in (
            request.workspace_id,
            request.scope_id,
            request.grantee_id,
            request.idempotency_key,
        ):
            if _id(value) != value:
                raise ValueError("canonical UUID required")
        if (
            actor.kind != "user"
            or request.grantee_kind not in {"user", "leta"}
            or request.role not in {"viewer", "editor", "manager"}
            or (request.grantee_kind == "leta" and request.role == "manager")
            or (
                request.HasField("personal_owner_user_id")
                and (
                    request.personal_owner_user_id != str(actor.id)
                    or request.grantee_kind != "leta"
                    or request.revoke
                )
            )
        ):
            raise ValueError("invalid scope access request")
        result = await self._rpc.invoke(
            self._stub.ChangeScopeAccess, request, actor=actor, timeout=60
        )
        if (
            result.workspace_id != request.workspace_id
            or result.scope_id != request.scope_id
            or result.grantee_kind != request.grantee_kind
            or result.grantee_id != request.grantee_id
            or not result.HasField("rights")
        ):
            raise ValueError("invalid scope access response")
        return result

    async def cleanup_leta_access(
        self,
        workspace_id: str,
        leta_id: str,
        home_scope_id: str,
        *,
        actor: Actor | None = None,
    ) -> None:
        if actor is not None and actor.kind != "user":
            raise ValueError("cleanup delegation requires the creator actor")
        result = await self._rpc.invoke(
            self._stub.CleanupLetaAccess,
            pb.CleanupLetaAccessRequest(
                workspace_id=_id(workspace_id),
                leta_id=_id(leta_id),
                home_scope_id=_id(home_scope_id),
            ),
            actor=actor,
            timeout=90,
        )
        if not result.completed:
            raise ValueError("cleanup was not completed")
