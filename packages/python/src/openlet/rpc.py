import asyncio
import contextvars
import hmac
import re
from contextlib import contextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

import grpc
from google.protobuf.any_pb2 import Any as AnyMessage
from google.protobuf.message import DecodeError
from google.rpc import error_details_pb2, status_pb2
from opentelemetry import context as otel_context
from opentelemetry import propagate

from openlet.errors import AppError

MAX_MESSAGE_BYTES = 8 * 1024 * 1024
UNARY_TIMEOUT = 120
STREAM_TIMEOUT = 1800
_TRANSIENT = {
    grpc.StatusCode.UNAVAILABLE,
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.INTERNAL,
}
_KINDS = {
    grpc.StatusCode.UNAUTHENTICATED: ("unauthenticated", "UNAUTHENTICATED"),
    grpc.StatusCode.PERMISSION_DENIED: ("forbidden", "FORBIDDEN"),
    grpc.StatusCode.NOT_FOUND: ("missing", "NOT_FOUND"),
    grpc.StatusCode.INVALID_ARGUMENT: ("invalid", "VALIDATION"),
    grpc.StatusCode.OUT_OF_RANGE: ("out_of_range", "VALIDATION"),
    grpc.StatusCode.RESOURCE_EXHAUSTED: ("limit", "RESOURCE_LIMIT"),
    grpc.StatusCode.ALREADY_EXISTS: ("exists", "SCOPE_CONFLICT"),
    grpc.StatusCode.ABORTED: ("conflict", "SCOPE_CONFLICT"),
    grpc.StatusCode.FAILED_PRECONDITION: ("precondition", "SCOPE_CONFLICT"),
    grpc.StatusCode.UNAVAILABLE: ("unavailable", "DEPENDENCY_UNAVAILABLE"),
    grpc.StatusCode.CANCELLED: ("canceled", "CANCELED"),
    grpc.StatusCode.DEADLINE_EXCEEDED: ("timeout", "TIMEOUT"),
    grpc.StatusCode.UNIMPLEMENTED: ("unsupported", "NOT_IMPLEMENTED"),
}
_STATUS = {
    "invalid": grpc.StatusCode.INVALID_ARGUMENT,
    "out_of_range": grpc.StatusCode.OUT_OF_RANGE,
    "unauthenticated": grpc.StatusCode.UNAUTHENTICATED,
    "forbidden": grpc.StatusCode.PERMISSION_DENIED,
    "missing": grpc.StatusCode.NOT_FOUND,
    "exists": grpc.StatusCode.ALREADY_EXISTS,
    "conflict": grpc.StatusCode.ABORTED,
    "precondition": grpc.StatusCode.FAILED_PRECONDITION,
    "limit": grpc.StatusCode.RESOURCE_EXHAUSTED,
    "unavailable": grpc.StatusCode.UNAVAILABLE,
    "canceled": grpc.StatusCode.CANCELLED,
    "timeout": grpc.StatusCode.DEADLINE_EXCEEDED,
    "unsupported": grpc.StatusCode.UNIMPLEMENTED,
}


@dataclass(frozen=True)
class Principal:
    service: str
    actor_id: UUID | None = None
    subject: str = ""
    gateway: bool = False


@dataclass(frozen=True)
class Credential:
    service: str
    token: str
    methods: frozenset[str]
    gateway: bool = False
    delegate_actor: bool = False


_principal = contextvars.ContextVar[Principal | None]("openlet_principal", default=None)


def principal() -> Principal:
    value = _principal.get()
    if value is None:
        raise AppError(
            "authentication required",
            reason="UNAUTHENTICATED",
            kind="unauthenticated",
            retryable=False,
        )
    return value


def validate(address: str, token: str) -> None:
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
            and not any(ord(char) <= 32 or ord(char) == 127 for char in address)
        )
    except ValueError:
        valid = False
    if not valid or not re.fullmatch(r"[A-Za-z0-9_-]{32,}", token):
        raise ValueError("invalid RPC configuration")


def _reason(error: grpc.aio.AioRpcError) -> str:
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
    return _KINDS.get(error.code(), ("internal", "INTERNAL"))[1]


def decode_error(error: grpc.aio.AioRpcError) -> AppError:
    kind, _ = _KINDS.get(error.code(), ("internal", "INTERNAL"))
    message = {
        "invalid": "invalid request",
        "unauthenticated": "authentication required",
        "forbidden": "permission denied",
        "missing": "resource not found",
        "limit": "resource limit exceeded",
        "unavailable": "dependency unavailable",
        "timeout": "request deadline exceeded",
    }.get(kind, "request failed")
    return AppError(
        message, reason=_reason(error), kind=kind, retryable=error.code() in _TRANSIENT
    )


class RpcClient:
    def __init__(self, address: str, token: str, *, allow_plaintext: bool = False):
        validate(address, token)
        options = [
            ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
            ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
            ("grpc.enable_retries", 0),
        ]
        self.channel = (
            grpc.aio.insecure_channel(address, options=options)
            if allow_plaintext
            else grpc.aio.secure_channel(
                address, grpc.ssl_channel_credentials(), options=options
            )
        )
        self._metadata = (("authorization", f"Bearer {token}"),)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.channel.close()

    async def invoke(
        self,
        method,
        request,
        *,
        actor_id: UUID | str | None = None,
        retry_transient: bool = False,
        timeout: float = UNARY_TIMEOUT,
    ):
        headers: dict[str, str] = {}
        propagate.inject(headers)
        if actor_id is not None:
            headers["x-openlet-user-id"] = str(actor_id)
        attempts = 3 if retry_transient else 1
        for attempt in range(attempts):
            try:
                return await method(
                    request,
                    metadata=self._metadata + tuple(headers.items()),
                    timeout=timeout,
                )
            except grpc.aio.AioRpcError as error:
                if error.code() not in _TRANSIENT:
                    raise decode_error(error) from None
                if attempt == attempts - 1:
                    raise decode_error(error) from None
                await asyncio.sleep(0.25 * (attempt + 1))
        raise AssertionError("unreachable")

    async def invoke_stream(
        self,
        method,
        request,
        *,
        actor_id: UUID | str | None = None,
        timeout: float = STREAM_TIMEOUT,
    ):
        headers: dict[str, str] = {}
        propagate.inject(headers)
        if actor_id is not None:
            headers["x-openlet-user-id"] = str(actor_id)
        call = method(
            request,
            metadata=self._metadata + tuple(headers.items()),
            timeout=timeout,
        )
        try:
            async for item in call:
                yield item
        except grpc.aio.AioRpcError as error:
            raise decode_error(error) from None
        finally:
            call.cancel()


class Authenticator(grpc.aio.ServerInterceptor):
    def __init__(self, credentials: list[Credential]):
        if not credentials or len({item.token for item in credentials}) != len(
            credentials
        ):
            raise ValueError("invalid RPC credential configuration")
        for item in credentials:
            validate("localhost:1", item.token)
            if (
                not item.service
                or not item.methods
                or any(
                    not re.fullmatch(r"/openlet_api\.[^/]+/[^/]+", method)
                    for method in item.methods
                )
            ):
                raise ValueError("invalid RPC credential configuration")
        self._credentials = tuple(credentials)

    async def intercept_service(self, continuation, details):
        handler = await continuation(details)
        if handler is None:
            return None
        value, failure = self.authenticate(
            tuple(details.invocation_metadata or ()), details.method
        )
        if failure is not None:
            return _refused_handler(handler, failure)
        carrier = dict(details.invocation_metadata or ())
        return _authenticated_handler(handler, value, carrier)

    def authenticate(self, metadata, method):
        values: dict[str, list[str]] = {}
        for key, value in metadata:
            values.setdefault(key.lower(), []).append(value)
        authorization = values.get("authorization", [])
        actors = values.get("x-openlet-user-id", [])
        if (
            len(authorization) != 1
            or len(actors) > 1
            or values.get("x-openlet-service")
        ):
            return None, (grpc.StatusCode.UNAUTHENTICATED, "invalid caller metadata")
        raw = authorization[0]
        token = raw[7:] if raw.startswith("Bearer ") else ""
        for credential in self._credentials:
            if not hmac.compare_digest(token, credential.token):
                continue
            if method not in credential.methods:
                return None, (
                    grpc.StatusCode.PERMISSION_DENIED,
                    "caller cannot invoke method",
                )
            actor = None
            if actors:
                if not (credential.gateway or credential.delegate_actor):
                    return None, (
                        grpc.StatusCode.PERMISSION_DENIED,
                        "caller cannot delegate user",
                    )
                try:
                    actor = UUID(actors[0])
                except ValueError:
                    return None, (
                        grpc.StatusCode.UNAUTHENTICATED,
                        "invalid actor identity",
                    )
                if actor.int == 0:
                    return None, (
                        grpc.StatusCode.UNAUTHENTICATED,
                        "invalid actor identity",
                    )
            elif credential.gateway:
                return None, (grpc.StatusCode.UNAUTHENTICATED, "missing actor identity")
            return Principal(
                credential.service, actor, gateway=credential.gateway
            ), None
        return None, (grpc.StatusCode.UNAUTHENTICATED, "invalid caller credential")


@contextmanager
def _request_context(value: Principal, carrier: dict[str, str]):
    principal_token = _principal.set(value)
    trace_token = otel_context.attach(propagate.extract(carrier))
    try:
        yield
    finally:
        otel_context.detach(trace_token)
        _principal.reset(principal_token)


async def _abort(context, error: Exception):
    if isinstance(error, AppError):
        detail = AnyMessage()
        detail.Pack(error_details_pb2.ErrorInfo(domain="openlet", reason=error.reason))
        status = _STATUS.get(error.kind, grpc.StatusCode.INTERNAL)
        context.set_trailing_metadata(
            (
                (
                    "grpc-status-details-bin",
                    status_pb2.Status(
                        code=status.value[0], message=str(error), details=[detail]
                    ).SerializeToString(),
                ),
            )
        )
        await context.abort(status, str(error))
    if isinstance(error, TimeoutError):
        await context.abort(
            grpc.StatusCode.DEADLINE_EXCEEDED, "request deadline exceeded"
        )
    await context.abort(grpc.StatusCode.INTERNAL, "internal server error")


def _refused_handler(handler, failure):
    async def unary(request, context):
        await context.abort(*failure)

    async def stream(request, context):
        await context.abort(*failure)
        if False:
            yield None

    options = {
        "request_deserializer": handler.request_deserializer,
        "response_serializer": handler.response_serializer,
    }
    if handler.unary_unary:
        return grpc.unary_unary_rpc_method_handler(unary, **options)
    if handler.unary_stream:
        return grpc.unary_stream_rpc_method_handler(stream, **options)
    if handler.stream_unary:
        return grpc.stream_unary_rpc_method_handler(unary, **options)
    return grpc.stream_stream_rpc_method_handler(stream, **options)


def _authenticated_handler(handler, value: Principal, carrier: dict[str, str]):
    async def unary_unary(request, context):
        with _request_context(value, carrier):
            try:
                async with asyncio.timeout(UNARY_TIMEOUT):
                    return await handler.unary_unary(request, context)
            except grpc.aio.AbortError:
                raise
            except Exception as error:
                await _abort(context, error)

    async def unary_stream(request, context):
        with _request_context(value, carrier):
            try:
                async with asyncio.timeout(STREAM_TIMEOUT):
                    async for response in handler.unary_stream(request, context):
                        yield response
            except grpc.aio.AbortError:
                raise
            except Exception as error:
                await _abort(context, error)

    async def stream_unary(request, context):
        with _request_context(value, carrier):
            try:
                async with asyncio.timeout(STREAM_TIMEOUT):
                    return await handler.stream_unary(request, context)
            except grpc.aio.AbortError:
                raise
            except Exception as error:
                await _abort(context, error)

    async def stream_stream(request, context):
        with _request_context(value, carrier):
            try:
                async with asyncio.timeout(STREAM_TIMEOUT):
                    async for response in handler.stream_stream(request, context):
                        yield response
            except grpc.aio.AbortError:
                raise
            except Exception as error:
                await _abort(context, error)

    options = {
        "request_deserializer": handler.request_deserializer,
        "response_serializer": handler.response_serializer,
    }
    if handler.unary_unary:
        return grpc.unary_unary_rpc_method_handler(unary_unary, **options)
    if handler.unary_stream:
        return grpc.unary_stream_rpc_method_handler(unary_stream, **options)
    if handler.stream_unary:
        return grpc.stream_unary_rpc_method_handler(stream_unary, **options)
    return grpc.stream_stream_rpc_method_handler(stream_stream, **options)


def new_server(authenticator: Authenticator) -> grpc.aio.Server:
    if not isinstance(authenticator, Authenticator):
        raise ValueError("missing RPC authenticator")
    return grpc.aio.server(
        interceptors=[authenticator],
        options=[
            ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
            ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
            ("grpc.max_metadata_size", 16 * 1024),
        ],
    )
