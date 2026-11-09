import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from leta import api, lifespan


@pytest.fixture
def dependency_boundaries(monkeypatch):
    opened = []
    closed = []

    def context(name, value):
        @asynccontextmanager
        async def owned(*args, **kwargs):
            opened.append(name)
            try:
                yield value
            finally:
                closed.append(name)

        return owned

    database_cursor = SimpleNamespace(
        fetchone=AsyncMock(
            return_value=(2, True, len(AsyncPostgresSaver.MIGRATIONS) - 1),
        )
    )
    connection = SimpleNamespace(execute=AsyncMock(return_value=database_cursor))
    pool = SimpleNamespace(
        wait=AsyncMock(), connection=context("connection", connection)
    )
    monkeypatch.setattr(lifespan, "AsyncConnectionPool", context("database", pool))
    monkeypatch.setattr(lifespan, "configure", context("telemetry", (None, None)))
    monkeypatch.setattr(lifespan, "serve", context("grpc", None))
    model_check = AsyncMock()
    monkeypatch.setattr(lifespan.Store, "verify_models", model_check)
    redis = SimpleNamespace(ping=AsyncMock(), aclose=AsyncMock())
    monkeypatch.setattr(
        lifespan, "Redis", SimpleNamespace(from_url=lambda *args, **kwargs: redis)
    )
    channels = []

    @asynccontextmanager
    async def rpc(*args, **kwargs):
        channel = SimpleNamespace(
            channel_ready=AsyncMock(), close=AsyncMock(), unary_unary=Mock()
        )
        channels.append(channel)
        try:
            yield SimpleNamespace(channel=channel)
        finally:
            await channel.close()

    monkeypatch.setattr(lifespan, "RpcClient", rpc)
    authz = SimpleNamespace(
        _openlet_channel=SimpleNamespace(channel_ready=AsyncMock()), close=AsyncMock()
    )
    monkeypatch.setattr(lifespan, "AuthorizationClient", lambda *args, **kwargs: authz)
    temporal = SimpleNamespace(
        workflow_service=SimpleNamespace(get_system_info=AsyncMock())
    )
    connect = AsyncMock(return_value=temporal)
    monkeypatch.setattr(lifespan, "connect", connect)
    return SimpleNamespace(
        opened=opened,
        closed=closed,
        redis=redis,
        channels=channels,
        authz=authz,
        pool=pool,
        connect=connect,
        database_cursor=database_cursor,
        model_check=model_check,
    )


@pytest.mark.parametrize(
    "failure", ["database", "temporal", "redis", "schema", "models", "cancel", None]
)
async def test_cleanup_after_startup_failure_and_cancel(
    settings, dependency_boundaries, failure
):
    dependencies = dependency_boundaries
    if failure == "database":
        dependencies.pool.wait.side_effect = RuntimeError("database unavailable")
    elif failure == "temporal":
        dependencies.connect.side_effect = RuntimeError("temporal unavailable")
    elif failure == "redis":
        dependencies.redis.ping.side_effect = RuntimeError("redis unavailable")
    elif failure == "schema":
        dependencies.database_cursor.fetchone.return_value = (0, True, 0)
    elif failure == "models":
        dependencies.model_check.side_effect = RuntimeError("unsupported saved model")

    async def run():
        async with lifespan.resources(settings):
            if failure == "cancel":
                raise asyncio.CancelledError

    if failure:
        with pytest.raises((RuntimeError, ExceptionGroup, asyncio.CancelledError)):
            await run()
    else:
        await run()
    assert dependencies.closed[-2:] == ["database", "telemetry"]
    if failure in {"redis", "schema", "models", "cancel", None}:
        assert "grpc" in dependencies.opened
        assert dependencies.opened.index("grpc") < dependencies.opened.index(
            "connection"
        )
        assert dependencies.closed.index("grpc") < dependencies.closed.index("database")
    if failure != "database":
        dependencies.redis.aclose.assert_awaited_once()
        dependencies.authz.close.assert_awaited_once()
        assert len(dependencies.channels) == 3
        for channel in dependencies.channels:
            channel.close.assert_awaited_once()


def test_http_health_and_gateway(settings, monkeypatch):
    check = AsyncMock()
    closed = []

    @asynccontextmanager
    async def owned(config):
        assert config is settings
        try:
            yield SimpleNamespace(check=check)
        finally:
            closed.append(True)

    monkeypatch.setattr(api, "resources", owned)
    with TestClient(api.create_app(settings)) as client:
        assert client.get("/live").json() == {"status": "ok"}
        assert client.get("/ready").status_code == 200
        response = client.get("/v1/unknown")
        assert response.status_code == 401
        assert response.headers["content-type"].startswith("application/problem+json")
        headers = {
            "x-gateway-token": settings.gateway_token,
            "x-clerk-sub": "fixture-human",
            "x-openlet-user-id": str(uuid4()),
        }
        assert client.get("/v1/unknown", headers=headers).status_code == 404
        duplicated = list(headers.items()) + [
            ("x-gateway-token", settings.gateway_token)
        ]
        assert client.get("/v1/unknown", headers=duplicated).status_code == 401
        check.side_effect = RuntimeError("sensitive dependency details")
        response = client.get("/ready")
        assert response.status_code == 503
        assert "sensitive" not in response.text
        assert client.get("/live").status_code == 200
    assert closed == [True]
