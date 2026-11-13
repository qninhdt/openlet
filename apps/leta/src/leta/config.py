from __future__ import annotations

from typing import TYPE_CHECKING

from openlet_api.letfs.v1.internal_pb2_grpc import LetFSInternalServiceStub
from openlet_api.letfs.v1.letfs_pb2_grpc import LetFSServiceStub
from openlet_api.platform.v1.internal_pb2_grpc import PlatformInternalServiceStub

if TYPE_CHECKING:
    from openlet_api.letfs.v1.internal_pb2_grpc import LetFSInternalServiceAsyncStub
    from openlet_api.letfs.v1.letfs_pb2_grpc import LetFSServiceAsyncStub
    from openlet_api.platform.v1.internal_pb2_grpc import (
        PlatformInternalServiceAsyncStub,
    )
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


from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from urllib.parse import quote

import httpx
from openlet_sdk.config import Config, secret
from openlet_sdk.rpc import channel
from redis.asyncio import Redis
from temporalio.client import Client
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.runtime import Runtime

from .auth import Authorization
from .db import Pool, pool
from .models import Models


def validate(config: Config) -> None:
    compaction = config["services"]["leta"]["compaction"]
    if not 0 < compaction["keep_fraction"] < compaction["trigger_fraction"] < 1:
        raise ValueError("compaction requires 0 < keep_fraction < trigger_fraction < 1")


@dataclass
class Services:
    config: Config
    db: Pool
    auth: Authorization
    files: LetFSServiceAsyncStub
    storage: LetFSInternalServiceAsyncStub
    internal: PlatformInternalServiceAsyncStub
    temporal: Client
    redis: Redis
    models: Models


def redis_url(config: Config) -> str:
    settings = config["dependencies"]["redis"]
    return f"redis://:{quote(secret(settings['password']), safe='')}@{settings['address']}/{settings['database']}"


@asynccontextmanager
async def connect(
    config: Config, *, native: Runtime | None = None
) -> AsyncGenerator[Services]:
    async with AsyncExitStack() as stack:
        db = await stack.enter_async_context(pool(config))
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
        gateway = config["models"]["gateway"]
        http = await stack.enter_async_context(
            httpx.AsyncClient(
                base_url=gateway["base_url"],
                headers={"Authorization": f"Bearer {secret(gateway['api_key'])}"},
                timeout=gateway["timeout_seconds"],
            )
        )
        yield Services(
            config,
            db,
            auth,
            LetFSServiceStub(f),
            LetFSInternalServiceStub(f),
            PlatformInternalServiceStub(p),
            temporal,
            redis,
            Models(http),
        )
