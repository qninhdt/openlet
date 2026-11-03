import grpc
import pytest
from google.protobuf.any_pb2 import Any
from google.rpc import error_details_pb2, status_pb2
from openlet.clients.letfs import Generation, ProcessingClient
from openlet.errors import AppError
from openlet.rpc import RpcClient
from openlet_api.letfs.v1 import letfs_pb2_grpc as rpc


@pytest.mark.parametrize(
    "address,token",
    [
        ("", "i" * 32),
        ("localhost", "i" * 32),
        ("localhost:0", "i" * 32),
        ("localhost:65536", "i" * 32),
        ("http://localhost:9090", "i" * 32),
        ("user:password@localhost:9090", "i" * 32),
        ("localhost:9090/path", "i" * 32),
        ("localhost:9090?token=secret", "i" * 32),
        ("localhost:9090#fragment", "i" * 32),
        ("localhost:9090\n", "i" * 32),
        ("localhost:9090", "short"),
        ("localhost:9090", "i" * 32 + "\n"),
    ],
)
def test_invalid_ingest_transport_is_rejected_without_dialing(address, token):
    with pytest.raises(ValueError, match="invalid RPC configuration"):
        RpcClient(address, token)


@pytest.mark.parametrize(
    "status,reason,attempts,terminal,expected",
    [
        (grpc.StatusCode.INTERNAL, "INTERNAL", 3, False, "INTERNAL"),
        (
            grpc.StatusCode.UNAVAILABLE,
            "DEPENDENCY_UNAVAILABLE",
            3,
            False,
            "DEPENDENCY_UNAVAILABLE",
        ),
        (grpc.StatusCode.RESOURCE_EXHAUSTED, "REQUEST_LIMIT", 1, True, "REQUEST_LIMIT"),
        (grpc.StatusCode.RESOURCE_EXHAUSTED, None, 1, True, "RESOURCE_LIMIT"),
    ],
)
async def test_native_error_classification_preserves_retry_and_resource_limits(
    status, reason, attempts, terminal, expected
):
    calls = 0

    class Refused(rpc.IngestServiceServicer):
        async def PrepareParse(self, request, context):
            nonlocal calls
            calls += 1
            if reason:
                info = Any()
                info.Pack(error_details_pb2.ErrorInfo(domain="openlet", reason=reason))
                details = status_pb2.Status(
                    code=status.value[0],
                    message="private dependency details",
                    details=[info],
                )
                context.set_trailing_metadata(
                    (("grpc-status-details-bin", details.SerializeToString()),)
                )
            await context.abort(status, "private dependency details")

    server = grpc.aio.server()
    rpc.add_IngestServiceServicer_to_server(Refused(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with RpcClient(
            f"127.0.0.1:{port}", "a" * 32, allow_plaintext=True
        ) as transport:
            with pytest.raises(AppError) as captured:
                await ProcessingClient(transport).prepare_parse(Generation("file", 1))
        assert calls == attempts
        assert captured.value.reason == expected
        assert captured.value.retryable is not terminal
        assert "private" not in str(captured.value)
    finally:
        await server.stop(None)
