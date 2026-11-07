import grpc
import pytest
from google.rpc import error_details_pb2, status_pb2

from openlet.errors import AppError
from openlet.rpc import Authenticator, Credential, new_server, principal
from openlet_api.account.v1 import account_pb2 as pb
from openlet_api.account.v1 import account_pb2_grpc as account_rpc

ACTOR = "019a3b66-0000-7000-8000-000000000001"
GATEWAY_TOKEN = "isolated-public-gateway-credential-12345"
SERVICE_TOKEN = "isolated-owner-service-credential-12345"
SUMMARIES = "/openlet_api.account.v1.AccountService/GetAccountSummaries"
EMAILS = "/openlet_api.account.v1.AccountService/GetVerifiedEmails"
STREAM = "/openlet_api.test.v1.StreamService/Read"


class Account(account_rpc.AccountServiceServicer):
    async def GetAccountSummaries(self, request, context):
        caller = principal()
        return pb.GetAccountSummariesResponse(
            accounts=[
                pb.AccountSummary(
                    id=str(caller.actor_id),
                    display_name=caller.service,
                )
            ]
        )

    async def GetVerifiedEmails(self, request, context):
        raise AppError(
            "user is unavailable",
            reason="NOT_FOUND",
            kind="missing",
            retryable=False,
        )


@pytest.fixture
async def account_server():
    server = new_server(
        Authenticator(
            [
                Credential(
                    "gateway",
                    GATEWAY_TOKEN,
                    frozenset({SUMMARIES, EMAILS}),
                    gateway=True,
                ),
                Credential("workspace", SERVICE_TOKEN, frozenset({SUMMARIES})),
                Credential(
                    "reader",
                    "isolated-stream-service-credential-123",
                    frozenset({STREAM}),
                ),
            ]
        )
    )
    account_rpc.add_AccountServiceServicer_to_server(Account(), server)

    async def read(request, context):
        if request == b"range":
            raise AppError(
                "position is outside the resource",
                reason="INVALID_RANGE",
                kind="out_of_range",
                retryable=False,
            )
        yield f"{principal().service}:first".encode()
        raise AppError(
            "stream is gone",
            reason="NOT_FOUND",
            kind="missing",
            retryable=False,
        )

    server.add_generic_rpc_handlers(
        (
            grpc.method_handlers_generic_handler(
                "openlet_api.test.v1.StreamService",
                {
                    "Read": grpc.unary_stream_rpc_method_handler(
                        read,
                        request_deserializer=lambda value: value,
                        response_serializer=lambda value: value,
                    )
                },
            ),
        )
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        yield f"127.0.0.1:{port}"
    finally:
        await server.stop(None)


async def invoke(stub, metadata, method="GetAccountSummaries"):
    call = getattr(stub, method)
    request = (
        pb.GetAccountSummariesRequest(ids=[ACTOR])
        if method == "GetAccountSummaries"
        else pb.GetVerifiedEmailsRequest(account_id=ACTOR)
    )
    return await call(request, metadata=metadata, timeout=2)


async def test_authenticated_rpc_wire_enforces_identity_and_method_scope(
    account_server,
):
    async with grpc.aio.insecure_channel(account_server) as channel:
        stub = account_rpc.AccountServiceStub(channel)
        gateway = (
            ("authorization", f"Bearer {GATEWAY_TOKEN}"),
            ("x-openlet-account-id", ACTOR),
        )
        response = await invoke(stub, gateway)
        assert response.accounts[0].id == ACTOR
        assert response.accounts[0].display_name == "gateway"

        cases = [
            ((), grpc.StatusCode.UNAUTHENTICATED),
            (
                gateway + (("authorization", f"Bearer {GATEWAY_TOKEN}"),),
                grpc.StatusCode.UNAUTHENTICATED,
            ),
            (
                gateway + (("x-openlet-account-id", ACTOR),),
                grpc.StatusCode.UNAUTHENTICATED,
            ),
            (
                gateway + (("x-openlet-service", "workspace"),),
                grpc.StatusCode.UNAUTHENTICATED,
            ),
            (
                (("authorization", f"Bearer {GATEWAY_TOKEN}"),),
                grpc.StatusCode.UNAUTHENTICATED,
            ),
            (
                (
                    ("authorization", f"Bearer {SERVICE_TOKEN}"),
                    ("x-openlet-account-id", ACTOR),
                ),
                grpc.StatusCode.PERMISSION_DENIED,
            ),
        ]
        for metadata, expected in cases:
            with pytest.raises(grpc.aio.AioRpcError) as captured:
                await invoke(stub, metadata)
            assert captured.value.code() == expected

        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await invoke(
                stub,
                (("authorization", f"Bearer {SERVICE_TOKEN}"),),
                "GetVerifiedEmails",
            )
        assert captured.value.code() == grpc.StatusCode.PERMISSION_DENIED


async def test_server_preserves_safe_application_error_details(account_server):
    async with grpc.aio.insecure_channel(account_server) as channel:
        stub = account_rpc.AccountServiceStub(channel)
        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await invoke(
                stub,
                (
                    ("authorization", f"Bearer {GATEWAY_TOKEN}"),
                    ("x-openlet-account-id", ACTOR),
                ),
                "GetVerifiedEmails",
            )
        error = captured.value
        assert error.code() == grpc.StatusCode.NOT_FOUND
        details = next(
            value
            for key, value in error.trailing_metadata()
            if key == "grpc-status-details-bin"
        )
        status = status_pb2.Status.FromString(details)
        info = error_details_pb2.ErrorInfo()
        assert status.details[0].Unpack(info)
        assert info.domain == "openlet"
        assert info.reason == "NOT_FOUND"


async def test_streaming_rpc_preserves_cardinality_auth_context_and_safe_errors(
    account_server,
):
    async with grpc.aio.insecure_channel(account_server) as channel:
        read = channel.unary_stream(
            STREAM,
            request_serializer=lambda value: value,
            response_deserializer=lambda value: value,
        )
        metadata = (
            (
                "authorization",
                "Bearer isolated-stream-service-credential-123",
            ),
        )
        call = read(b"request", metadata=metadata, timeout=2)
        assert await call.read() == b"reader:first"
        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await call.read()
        assert captured.value.code() == grpc.StatusCode.NOT_FOUND

        outside = read(b"range", metadata=metadata, timeout=2)
        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await outside.read()
        assert captured.value.code() == grpc.StatusCode.OUT_OF_RANGE

        denied = read(b"request", timeout=2)
        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await denied.read()
        assert captured.value.code() == grpc.StatusCode.UNAUTHENTICATED
