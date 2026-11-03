import grpc
from authzed.api.v1 import (
    CheckPermissionResponse,
)
from authzed.api.v1 import (
    permission_service_pb2_grpc as authz_rpc,
)

from openlet.authz import Resource, check, client

TOKEN = "isolated-spicedb-service-credential-123"


class Permissions(authz_rpc.PermissionsServiceServicer):
    async def CheckPermission(self, request, context):
        metadata = dict(context.invocation_metadata())
        assert metadata["authorization"] == f"Bearer {TOKEN}"
        assert 0 < context.time_remaining() <= 2.1
        return CheckPermissionResponse(
            permissionship=CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION
        )


async def test_official_authzed_client_plaintext_boundary_is_bounded_and_owned():
    server = grpc.aio.server()
    authz_rpc.add_PermissionsServiceServicer_to_server(Permissions(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    api = client(f"127.0.0.1:{port}", TOKEN, allow_plaintext=True)
    try:
        assert await check(
            api,
            "019a3b66-0000-7000-8000-000000000001",
            "node_read",
            Resource("filesystem", "drive"),
        )
    finally:
        await api.close()
        await server.stop(None)
