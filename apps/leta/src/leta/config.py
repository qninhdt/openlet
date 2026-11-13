from __future__ import annotations

from typing import TYPE_CHECKING

from openlet_api.letfs.v1.internal_pb2_grpc import LetFSInternalServiceStub
from openlet_api.letfs.v1.letfs_pb2_grpc import LetFSServiceStub
from openlet_api.platform.v1.internal_pb2_grpc import PlatformInternalServiceStub
from openlet_api.platform.v1.platform_pb2_grpc import PlatformServiceStub

if TYPE_CHECKING:
    from openlet_api.letfs.v1.internal_pb2_grpc import LetFSInternalServiceAsyncStub
    from openlet_api.letfs.v1.letfs_pb2_grpc import LetFSServiceAsyncStub
    from openlet_api.platform.v1.internal_pb2_grpc import (
        PlatformInternalServiceAsyncStub,
    )
    from openlet_api.platform.v1.platform_pb2_grpc import PlatformServiceAsyncStub
else:
    # Generated async stub types share the runtime stub class.
    from openlet_api.letfs.v1.internal_pb2_grpc import (
        LetFSInternalServiceStub as LetFSInternalServiceAsyncStub,
    )
    from openlet_api.letfs.v1.letfs_pb2_grpc import (
        LetFSServiceStub as LetFSServiceAsyncStub,
    )
    from openlet_api.platform.v1.internal_pb2_grpc import (
        PlatformInternalServiceStub as PlatformInternalServiceAsyncStub,
    )
    from openlet_api.platform.v1.platform_pb2_grpc import (
        PlatformServiceStub as PlatformServiceAsyncStub,
    )


from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from urllib.parse import quote

from openlet_sdk.config import Config, ModelEntry, ReasoningEffort, load, secret
from openlet_sdk.rpc import channel
from redis.asyncio import Redis
from temporalio.client import Client
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.runtime import Runtime

from .auth import Authorization
from .db import Pool, pool


def validate(config: Config) -> None:
    models = config["models"]["leta"]
    ids = [item["model_id"] for item in models["catalog"]]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("model catalog must have unique model IDs")
    for item in models["catalog"]:
        if not 0 < item["max_output_tokens"] < item["context_window_tokens"]:
            raise ValueError("model output must fit its context window")
    model(config, models["default"]["model_id"], models["default"]["reasoning_effort"])


def model(config: Config, model_id: str | None, effort: ReasoningEffort) -> ModelEntry:
    if model_id is None:
        effort = config["models"]["leta"]["default"]["reasoning_effort"]
    selected = model_id or config["models"]["leta"]["default"]["model_id"]
    for item in config["models"]["leta"]["catalog"]:
        if item["model_id"] == selected:
            if effort not in item["reasoning_efforts"]:
                raise ValueError("unsupported reasoning effort for model")
            return item
    raise ValueError("unknown model")


settings = load


@dataclass
class Services:
    config: Config
    db: Pool
    auth: Authorization
    files: LetFSServiceAsyncStub
    storage: LetFSInternalServiceAsyncStub
    platform: PlatformServiceAsyncStub
    internal: PlatformInternalServiceAsyncStub
    temporal: Client
    redis: Redis


def redis_url(config: Config) -> str:
    settings = config["dependencies"]["redis"]
    return f"redis://:{quote(secret(settings['password']), safe='')}@{settings['address']}/{settings['database']}"


@asynccontextmanager
async def connect(
    config: Config, *, native: Runtime | None = None
) -> AsyncGenerator[Services]:
    async with AsyncExitStack() as stack:
        db = await stack.enter_async_context(pool())
        auth = Authorization(config)
        stack.push_async_callback(auth.channel.close)
        f = await stack.enter_async_context(
            channel(
                config["services"]["letfs"]["grpc_target"],
                max_bytes=config["grpc"]["max_receive_bytes"],
            )
        )
        p = await stack.enter_async_context(
            channel(
                config["services"]["platform"]["grpc_target"],
                max_bytes=config["grpc"]["max_receive_bytes"],
            )
        )
        redis = Redis.from_url(  # pyright: ignore[reportUnknownMemberType]  # Upstream SDK has an untyped overload or kwargs.
            redis_url(config), socket_connect_timeout=5, socket_timeout=10
        )
        stack.push_async_callback(redis.aclose)
        settings = config["dependencies"]["temporal"]
        temporal = await Client.connect(
            settings["address"],
            namespace=settings["namespace"],
            tls=settings["tls"],
            data_converter=pydantic_data_converter,
            runtime=native,
            interceptors=[TracingInterceptor()],
        )
        yield Services(
            config,
            db,
            auth,
            LetFSServiceStub(f),
            LetFSInternalServiceStub(f),
            PlatformServiceStub(p),
            PlatformInternalServiceStub(p),
            temporal,
            redis,
        )
