import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta

from openlet.authz import AuthorizationClient
from openlet.clients.workspace import WorkspaceClient
from openlet.rpc import RpcClient
from openlet.telemetry import configure
from openlet.temporal import connect
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis
from temporalio.api.workflowservice.v1 import GetSystemInfoRequest
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter

from leta.config import Settings
from leta.migrate import verify_schema
from leta.store import Store
from leta.transport.grpc import serve


@dataclass
class Resources:
    database: AsyncConnectionPool
    redis: Redis
    temporal: Client
    account: RpcClient
    workspace: RpcClient
    letfs: RpcClient
    authz: AuthorizationClient

    async def check(self):
        async def database_check():
            async with self.database.connection() as connection:
                await verify_schema(connection)

        async with asyncio.timeout(5), asyncio.TaskGroup() as checks:
            checks.create_task(database_check())
            checks.create_task(self.redis.ping())
            checks.create_task(
                self.temporal.workflow_service.get_system_info(
                    GetSystemInfoRequest(), timeout=timedelta(seconds=3)
                )
            )
            for rpc in (self.account, self.workspace, self.letfs):
                checks.create_task(rpc.channel.channel_ready())
            checks.create_task(self.authz._openlet_channel.channel_ready())


@asynccontextmanager
async def resources(settings: Settings):
    async with AsyncExitStack() as stack:
        tracing, runtime = await stack.enter_async_context(configure("openlet-leta"))
        database = await stack.enter_async_context(
            AsyncConnectionPool(
                settings.database_url,
                min_size=1,
                max_size=8,
                open=False,
                timeout=5,
                kwargs={"autocommit": True, "prepare_threshold": 0},
            )
        )
        await database.wait(timeout=5)
        redis = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=3,
            socket_timeout=5,
            max_connections=16,
        )
        stack.push_async_callback(redis.aclose)
        clients = []
        for address in (
            settings.account_rpc_address,
            settings.workspace_rpc_address,
            settings.letfs_rpc_address,
        ):
            clients.append(
                await stack.enter_async_context(
                    RpcClient(
                        address,
                        settings.service_token,
                        allow_plaintext=settings.allow_plaintext,
                    )
                )
            )
        authz = AuthorizationClient(
            settings.spicedb_address,
            settings.spicedb_key,
            allow_plaintext=settings.allow_plaintext,
        )
        stack.push_async_callback(authz.close)
        async with asyncio.timeout(5):
            temporal = await connect(
                settings.temporal_address,
                settings.temporal_namespace,
                interceptor=tracing,
                runtime=runtime,
                tls=not settings.allow_plaintext,
                data_converter=pydantic_data_converter,
            )
        value = Resources(database, redis, temporal, *clients, authz)
        # Bind before remote readiness so Workspace can validate resources at startup.
        await stack.enter_async_context(
            serve(
                settings,
                Store(database, settings.models),
                value.check,
                temporal=temporal,
                scopes=WorkspaceClient(value.workspace),
            )
        )
        await value.check()
        await Store(database, settings.models).verify_models()
        yield value
