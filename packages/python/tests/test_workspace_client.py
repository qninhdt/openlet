from uuid import UUID

import pytest

from openlet.clients.workspace import WorkspaceClient
from openlet.errors import AppError
from openlet.rpc import (
    Actor,
    Authenticator,
    Credential,
    RpcClient,
    new_server,
    principal,
)
from openlet_api.account.v1.account_pb2 import UserSummary
from openlet_api.workspace.v1 import workspace_pb2 as pb
from openlet_api.workspace.v1.workspace_pb2_grpc import (
    WorkspaceServiceServicer,
    add_WorkspaceServiceServicer_to_server,
)

WS, FS, SHARED, ROOT, HOME, USER, PERSONAL, FILE = (
    f"019a3b66-0000-7000-8000-{index:012d}" for index in range(1, 9)
)
TOKEN = "isolated-leta-workspace-credential-12345"
USER_ACTOR, ROOT_ACTOR = Actor("user", UUID(USER)), Actor("leta", UUID(ROOT))
METHODS = frozenset(
    f"/openlet_api.workspace.v1.WorkspaceService/{name}"
    for name in (
        "GetWorkspace",
        "ListMembers",
        "ListAccessibleScopes",
        "EnsureLetaHomeAccess",
        "ResolvePersonalScope",
        "ChangeScopeAccess",
        "CleanupLetaAccess",
    )
)


class WorkspaceServer(WorkspaceServiceServicer):
    def __init__(self):
        self.calls = []
        self.corrupt = None

    def record(self, name, request, context):
        self.calls.append((name, principal().actor, request, context.time_remaining()))

    async def GetWorkspace(self, request, context):
        self.record("get", request, context)
        value = pb.Workspace(
            id=request.workspace_id,
            name="Team",
            filesystem_id=FS,
            shared_scope_id=SHARED,
            status="active",
        )
        if request.HasField("cleanup_leta_id"):
            value.name, value.status = "", "deleting"
        elif principal().actor.kind == "user":
            value.role, value.personal_scope_id = "member", PERSONAL
        if self.corrupt == "workspace":
            value.id = FS
        return pb.GetWorkspaceResponse(workspace=value)

    async def ListMembers(self, request, context):
        self.record("members", request, context)
        return pb.ListMembersResponse(
            workspace_id=request.workspace_id,
            items=[
                pb.Member(
                    user=UserSummary(id=USER, display_name="Resource owner"),
                    role="member",
                    personal_scope_id=PERSONAL,
                )
            ],
        )

    async def ListAccessibleScopes(self, request, context):
        self.record("scopes", request, context)
        actor = principal().actor
        result = pb.ListAccessibleScopesResponse(
            workspace_id=WS,
            filesystem_id=FS,
            subject_kind="leta" if request.HasField("leta_id") else actor.kind,
            subject_id=request.leta_id
            if request.HasField("leta_id")
            else str(actor.id),
            items=[
                pb.AccessibleScope(
                    id=PERSONAL,
                    root_id=FILE,
                    kind="personal",
                    owner=UserSummary(id=USER),
                    rights=pb.ScopeRights(read_metadata=True, read_content=True),
                )
            ],
        )
        if self.corrupt == "subject":
            result.subject_kind = "user"
        if self.corrupt == "metadata":
            result.items[0].rights.read_metadata = False
        if self.corrupt == "duplicate":
            result.items.append(result.items[0])
        if self.corrupt == "owner":
            result.items[0].ClearField("owner")
        if self.corrupt == "cursor":
            result.next_cursor = ""
        return result

    async def EnsureLetaHomeAccess(self, request, context):
        self.record("home", request, context)
        return pb.EnsureLetaHomeAccessResponse(
            workspace_id=request.workspace_id,
            filesystem_id=FS,
            home_scope_id=request.home_scope_id,
        )

    async def ResolvePersonalScope(self, request, context):
        self.record("personal", request, context)
        return pb.ResolvePersonalScopeResponse(
            workspace_id=request.workspace_id,
            filesystem_id=FS,
            scope_id=PERSONAL,
            owner_user_id=request.owner_user_id,
        )

    async def ChangeScopeAccess(self, request, context):
        self.record("access", request, context)
        return pb.ChangeScopeAccessResponse(
            workspace_id=request.workspace_id,
            scope_id=request.scope_id,
            grantee_kind=request.grantee_kind,
            grantee_id=request.grantee_id,
            rights=pb.ScopeRights(read_metadata=True, read_content=True),
        )

    async def CleanupLetaAccess(self, request, context):
        self.record("cleanup", request, context)
        return pb.CleanupLetaAccessResponse(completed=True)


@pytest.fixture
async def workspace_client():
    implementation = WorkspaceServer()
    server = new_server(
        Authenticator(
            [
                Credential(
                    "leta",
                    TOKEN,
                    METHODS,
                    delegate_actor=True,
                    leta_methods=frozenset(
                        method
                        for method in METHODS
                        if method.rsplit("/", 1)[-1]
                        in {
                            "GetWorkspace",
                            "ListMembers",
                            "ListAccessibleScopes",
                            "ResolvePersonalScope",
                        }
                    ),
                )
            ]
        )
    )
    add_WorkspaceServiceServicer_to_server(implementation, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with RpcClient(
            f"127.0.0.1:{port}", TOKEN, allow_plaintext=True
        ) as connection:
            yield WorkspaceClient(connection), implementation
    finally:
        await server.stop(None)


async def test_workspace_client_real_wire_actors_and_methods(workspace_client):
    client, server = workspace_client
    assert (await client.get_workspace(WS, actor=ROOT_ACTOR)).id == WS
    assert (
        await client.get_workspace(WS, actor=USER_ACTOR)
    ).personal_scope_id == PERSONAL
    members = await client.list_members(WS, actor=ROOT_ACTOR)
    assert members.items[0].user.display_name == "Resource owner"
    scopes = await client.list_accessible_scopes(WS, actor=ROOT_ACTOR)
    assert scopes.subject_kind == "leta" and scopes.items[0].owner.id == USER
    scopes = await client.list_accessible_scopes(WS, actor=USER_ACTOR, leta_id=ROOT)
    assert scopes.subject_id == ROOT
    home = await client.ensure_leta_home_access(WS, ROOT, HOME, FILE, actor=USER_ACTOR)
    assert home.home_scope_id == HOME
    personal = await client.resolve_personal_scope(WS, USER, actor=ROOT_ACTOR)
    assert personal.scope_id == PERSONAL and personal.owner_user_id == USER
    request = pb.ChangeScopeAccessRequest(
        workspace_id=WS,
        scope_id=PERSONAL,
        grantee_kind="leta",
        grantee_id=ROOT,
        role="viewer",
        idempotency_key=FILE,
        personal_owner_user_id=USER,
    )
    result = await client.change_scope_access(request, actor=USER_ACTOR)
    assert result.rights.read_content and not result.rights.write
    assert (await client.get_cleanup_workspace(WS, ROOT)).status == "deleting"
    await client.cleanup_leta_access(WS, ROOT, HOME)
    await client.cleanup_leta_access(WS, ROOT, HOME, actor=USER_ACTOR)
    calls = {
        name: (actor, request, timeout)
        for name, actor, request, timeout in server.calls
    }
    assert calls["home"][0] == USER_ACTOR and calls["home"][1].idempotency_key == FILE
    assert calls["personal"][0] == ROOT_ACTOR
    assert calls["access"][0] == USER_ACTOR
    assert 0 < calls["access"][2] <= 61
    assert server.calls[-2][1] is None
    assert server.calls[-1][1] == USER_ACTOR


@pytest.mark.parametrize(
    "corrupt", ["subject", "metadata", "duplicate", "owner", "cursor"]
)
async def test_scope_client_rejects_invalid_native_response(workspace_client, corrupt):
    client, server = workspace_client
    server.corrupt = corrupt
    with pytest.raises(ValueError):
        await client.list_accessible_scopes(WS, actor=ROOT_ACTOR)


async def test_workspace_client_validation_and_error_mapping(workspace_client):
    client, server = workspace_client
    with pytest.raises(ValueError):
        await client.list_members(WS, actor=ROOT_ACTOR, limit=101)
    with pytest.raises(ValueError):
        await client.resolve_personal_scope(WS, USER, actor=USER_ACTOR)
    with pytest.raises(ValueError):
        await client.ensure_leta_home_access(WS, ROOT, HOME, FILE, actor=ROOT_ACTOR)
    with pytest.raises(ValueError, match="canonical"):
        await client.change_scope_access(
            pb.ChangeScopeAccessRequest(
                workspace_id=WS.upper(),
                scope_id=PERSONAL,
                grantee_kind="leta",
                grantee_id=ROOT,
                role="viewer",
                idempotency_key=FILE,
            ),
            actor=USER_ACTOR,
        )
    assert not server.calls
    server.corrupt = "workspace"
    with pytest.raises(ValueError):
        await client.get_workspace(WS, actor=ROOT_ACTOR)
    server.corrupt = None
    # The destination's method allowlist rejects a root trying the human grant method.
    with pytest.raises(AppError) as failure:
        await client._rpc.invoke(
            client._stub.ChangeScopeAccess,
            pb.ChangeScopeAccessRequest(),
            actor=ROOT_ACTOR,
        )
    assert failure.value.kind == "forbidden"
