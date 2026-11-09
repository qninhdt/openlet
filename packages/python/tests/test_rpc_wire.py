from uuid import UUID

import grpc
import pytest
from google.rpc import error_details_pb2, status_pb2

from openlet.errors import AppError
from openlet.rpc import Actor, Authenticator, Credential, new_server, principal
from openlet_api.account.v1 import account_pb2 as pb
from openlet_api.account.v1 import account_pb2_grpc as account_rpc

ACTOR = "019a3b66-0000-7000-8000-000000000001"
GATEWAY_TOKEN = "isolated-public-gateway-credential-12345"
SERVICE_TOKEN = "isolated-owner-service-credential-12345"
SUMMARIES = "/openlet_api.account.v1.AccountService/GetUserSummaries"
EMAILS = "/openlet_api.account.v1.AccountService/GetVerifiedEmails"
STREAM = "/openlet_api.test.v1.StreamService/Read"


class Account(account_rpc.AccountServiceServicer):
    async def GetUserSummaries(self, request, context):
        caller = principal()
        return pb.GetUserSummariesResponse(
            users=[
                pb.UserSummary(
                    id=str(caller.actor.id),
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
                    "leta",
                    "isolated-leta-method-credential-12345",
                    frozenset({SUMMARIES}),
                    delegate_actor=True,
                    leta_methods=frozenset({SUMMARIES}),
                ),
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


async def invoke(stub, metadata, method="GetUserSummaries"):
    call = getattr(stub, method)
    request = (
        pb.GetUserSummariesRequest(ids=[ACTOR])
        if method == "GetUserSummaries"
        else pb.GetVerifiedEmailsRequest(user_id=ACTOR)
    )
    return await call(request, metadata=metadata, timeout=2)


async def test_authenticated_rpc_wire_enforces_identity_and_method_scope(
    account_server,
):
    async with grpc.aio.insecure_channel(account_server) as channel:
        stub = account_rpc.AccountServiceStub(channel)
        gateway = (
            ("authorization", f"Bearer {GATEWAY_TOKEN}"),
            ("x-openlet-user-id", ACTOR),
        )
        response = await invoke(stub, gateway)
        assert response.users[0].id == ACTOR
        assert response.users[0].display_name == "gateway"

        cases = [
            ((), grpc.StatusCode.UNAUTHENTICATED),
            (
                gateway + (("authorization", f"Bearer {GATEWAY_TOKEN}"),),
                grpc.StatusCode.UNAUTHENTICATED,
            ),
            (
                gateway + (("x-openlet-user-id", ACTOR),),
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
                    ("x-openlet-user-id", ACTOR),
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
                    ("x-openlet-user-id", ACTOR),
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


async def test_typed_leta_delegation_and_invalid_headers(account_server):
    from openlet.rpc import RpcClient

    token = "isolated-leta-method-credential-12345"
    async with RpcClient(account_server, token, allow_plaintext=True) as rpc:
        stub = account_rpc.AccountServiceStub(rpc.channel)
        result = await rpc.invoke(
            stub.GetUserSummaries,
            pb.GetUserSummariesRequest(ids=[ACTOR]),
            actor=Actor("leta", UUID(ACTOR)),
        )
        assert result.users[0].id == ACTOR
        assert result.users[0].display_name == "leta"
        for metadata in (
            (
                ("authorization", f"Bearer {token}"),
                ("x-openlet-user-id", ACTOR),
                ("x-openlet-leta-id", ACTOR),
            ),
            (
                ("authorization", f"Bearer {token}"),
                ("x-openlet-leta-id", ACTOR),
                ("x-openlet-leta-id", ACTOR),
            ),
            (("authorization", f"Bearer {token}"), ("x-openlet-account-id", ACTOR)),
            (
                ("authorization", f"Bearer {GATEWAY_TOKEN}"),
                ("x-openlet-leta-id", ACTOR),
            ),
            (
                ("authorization", f"Bearer {SERVICE_TOKEN}"),
                ("x-openlet-leta-id", ACTOR),
            ),
        ):
            with pytest.raises(grpc.aio.AioRpcError) as caught:
                await invoke(stub, metadata)
            assert caught.value.code() in {
                grpc.StatusCode.UNAUTHENTICATED,
                grpc.StatusCode.PERMISSION_DENIED,
            }


def test_actor_and_delegation_configuration_are_closed():
    for kind, value in (
        ("account", UUID(ACTOR)),
        ("user", UUID(int=0)),
        ("leta", ACTOR),
    ):
        with pytest.raises(ValueError, match="invalid actor identity"):
            Actor(kind, value)
    for options in ({"gateway": True}, {"delegate_actor": False}):
        with pytest.raises(ValueError, match="invalid RPC credential"):
            Authenticator(
                [
                    Credential(
                        "invalid",
                        SERVICE_TOKEN,
                        frozenset({SUMMARIES}),
                        leta_methods=frozenset({SUMMARIES}),
                        **options,
                    )
                ]
            )
