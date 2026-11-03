import asyncio
import re
from urllib.parse import urlsplit

import grpc
from google.protobuf.message import DecodeError
from google.rpc import error_details_pb2, status_pb2
from openlet_api.letfs.v1.letfs_pb2_grpc import IngestServiceStub
from temporalio.exceptions import ApplicationError

_TRANSIENT = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.INTERNAL,
}


def _reason(error):
    for key, value in error.trailing_metadata() or ():
        if key != "grpc-status-details-bin":
            continue
        try:
            details = status_pb2.Status.FromString(value)
            for detail in details.details:
                info = error_details_pb2.ErrorInfo()
                if (
                    detail.Unpack(info)
                    and info.domain == "openlet"
                    and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", info.reason)
                ):
                    return info.reason
        except (DecodeError, TypeError):
            break
    return {
        grpc.StatusCode.UNAUTHENTICATED: "UNAUTHENTICATED",
        grpc.StatusCode.PERMISSION_DENIED: "FORBIDDEN",
        grpc.StatusCode.NOT_FOUND: "NOT_FOUND",
        grpc.StatusCode.INVALID_ARGUMENT: "VALIDATION",
        grpc.StatusCode.RESOURCE_EXHAUSTED: "RESOURCE_LIMIT",
    }.get(error.code(), "PROCESSING_FAILED")


class IngestRPC:
    def __init__(self, address: str, token: str, *, allow_plaintext: bool = False):
        try:
            endpoint = urlsplit("//" + address)
            valid = (
                endpoint.hostname
                and endpoint.port is not None
                and 1 <= endpoint.port <= 65535
                and endpoint.username is None
                and endpoint.password is None
                and not endpoint.path
                and not endpoint.query
                and not endpoint.fragment
                and not any(ord(c) <= 32 or ord(c) == 127 for c in address)
            )
        except ValueError:
            valid = False
        if not valid or not re.fullmatch(r"[A-Za-z0-9_-]{32,}", token):
            raise ValueError("invalid ingest RPC configuration")
        options = [
            ("grpc.max_send_message_length", 8 * 1024 * 1024),
            ("grpc.max_receive_message_length", 8 * 1024 * 1024),
        ]
        if allow_plaintext:
            self.channel = grpc.aio.insecure_channel(address, options=options)
        else:
            self.channel = grpc.aio.secure_channel(
                address, grpc.ssl_channel_credentials(), options=options
            )
        self.stub = IngestServiceStub(self.channel)
        self._metadata = (("authorization", f"Bearer {token}"),)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.channel.close()

    async def call(self, method, request):
        method = getattr(self.stub, method)
        for attempt in range(3):
            try:
                return await method(request, metadata=self._metadata, timeout=30)
            except grpc.aio.AioRpcError as error:
                if error.code() not in _TRANSIENT:
                    raise ApplicationError(
                        "processing request refused",
                        type=_reason(error),
                        non_retryable=True,
                    ) from None
                if attempt < 2:
                    await asyncio.sleep(0.25 * (attempt + 1))
        raise ApplicationError("letfs unavailable", type="DEPENDENCY_UNAVAILABLE")
