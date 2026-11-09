from contextlib import asynccontextmanager
from uuid import UUID

import grpc
from grpc_health.v1 import health_pb2 as health
from grpc_health.v1 import health_pb2_grpc as health_rpc
from openlet.rpc import Authenticator, Credential, new_server, principal
from openlet_api.leta.v1 import leta_pb2 as pb
from openlet_api.leta.v1 import leta_pb2_grpc as leta_rpc
from opentelemetry import trace

from leta.config import Settings
from leta.store import Store, fault

SERVICE = pb.DESCRIPTOR.services_by_name["LetaService"].full_name
GET_BINDING = f"/{SERVICE}/GetLetaBinding"
LIST_WORKSPACE = f"/{SERVICE}/ListWorkspaceLeta"
STOP_WORKSPACE = f"/{SERVICE}/StopLetaForWorkspaceDeletion"
tracer = trace.get_tracer(__name__)


def workspace_caller():
    caller = principal()
    if caller.service != "workspace" or caller.actor is not None or caller.gateway:
        raise fault("FORBIDDEN", "actor-free Workspace service required", "forbidden")


def identity(raw):
    try:
        value = UUID(raw)
        if not value.int:
            raise ValueError
        return value
    except ValueError:
        raise fault("VALIDATION", "nonzero UUID required", "invalid") from None


class LetaService(leta_rpc.LetaServiceServicer):
    def __init__(self, store: Store, temporal=None, scopes=None):
        self.store, self.temporal, self.scopes = store, temporal, scopes

    async def GetLetaBinding(self, request, context):
        workspace_caller()
        leta_id = identity(request.leta_id)
        with tracer.start_as_current_span(
            "LetaService.GetLetaBinding", kind=trace.SpanKind.SERVER
        ):
            row = await self.store.get_binding(leta_id)
        return pb.GetLetaBindingResponse(
            **{key: str(value) for key, value in row.items()}
        )

    async def ListWorkspaceLeta(self, request, context):
        workspace_caller()
        workspace_id = identity(request.workspace_id)
        after = identity(request.cursor) if request.cursor else None
        limit = request.limit or 100
        found = await self.store.list_workspace_leta(
            workspace_id, after=after, limit=limit
        )
        return pb.ListWorkspaceLetaResponse(
            workspace_id=str(workspace_id),
            leta_ids=[str(row["id"]) for row in found[:limit]],
            **(
                {"next_cursor": str(found[limit - 1]["id"])}
                if len(found) > limit
                else {}
            ),
        )

    async def StopLetaForWorkspaceDeletion(self, request, context):
        from leta.temporal.bridges import change_leta
        from leta.temporal.lifecycle_types import LetaChange

        workspace_caller()
        workspace_id, leta_id = (
            identity(request.workspace_id),
            identity(request.leta_id),
        )
        root = await self.store.get_binding(leta_id)
        if root["workspace_id"] != workspace_id:
            raise fault("NOT_FOUND", "Leta belongs to another workspace", "missing")
        if self.scopes is None or self.temporal is None:
            raise fault("DEPENDENCY_UNAVAILABLE", "cleanup unavailable", "unavailable")
        # Direct status read cannot recurse into WorkspaceChanges' held delete lock.
        await self.scopes.get_cleanup_workspace(str(workspace_id), str(leta_id))
        result = await change_leta(
            self.temporal,
            LetaChange(leta_id=leta_id, action="deleting", workspace_deletion=True),
            command_id=f"workspace-delete/{workspace_id}/{leta_id}",
        )
        if result.status != "archived":
            raise fault("STATE_CONFLICT", "Leta cleanup is incomplete")
        return pb.StopLetaForWorkspaceDeletionResponse(
            workspace_id=str(workspace_id), leta_id=str(leta_id), status=result.status
        )


class Health(health_rpc.HealthServicer):
    def __init__(self, check):
        self.check = check

    async def Check(self, request, context):
        if request.service not in {"", SERVICE}:
            await context.abort(grpc.StatusCode.NOT_FOUND, "unknown service")
        try:
            await self.check()
        except Exception:
            return health.HealthCheckResponse(
                status=health.HealthCheckResponse.NOT_SERVING
            )
        return health.HealthCheckResponse(status=health.HealthCheckResponse.SERVING)


@asynccontextmanager
async def serve(settings: Settings, store: Store, check, *, temporal=None, scopes=None):
    server = new_server(
        Authenticator(
            [
                Credential(
                    "workspace",
                    settings.workspace_service_token,
                    frozenset({GET_BINDING, LIST_WORKSPACE, STOP_WORKSPACE}),
                )
            ]
        )
    )
    try:
        leta_rpc.add_LetaServiceServicer_to_server(
            LetaService(store, temporal, scopes), server
        )
        health_rpc.add_HealthServicer_to_server(Health(check), server)
        if settings.allow_plaintext:
            port = server.add_insecure_port(settings.rpc_listen_addr)
        else:
            try:
                if (
                    settings.rpc_certificate_path is None
                    or settings.rpc_private_key_path is None
                ):
                    raise ValueError
                credentials = grpc.ssl_server_credentials(
                    [
                        (
                            settings.rpc_private_key_path.read_bytes(),
                            settings.rpc_certificate_path.read_bytes(),
                        )
                    ]
                )
                port = server.add_secure_port(settings.rpc_listen_addr, credentials)
            except OSError, ValueError, RuntimeError:
                raise ValueError("RPC TLS certificate unavailable") from None
        if not port:
            raise ValueError("RPC listener unavailable")
        await server.start()
        yield port
    finally:
        await server.stop(5)
