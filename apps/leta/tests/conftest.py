import json
import os
import re
import secrets
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from leta.config import Settings

POSTGRES_IMAGE = (
    "postgres:18.6-trixie@sha256:"
    "e3d24f6906d0760bf4da0dae872415391ededefad23fd471c47dc53b0ddf3c42"
)
REDIS_IMAGE = (
    "redis:8.10.3-trixie@sha256:"
    "1f88291b4c57bdf249f02eb085a8669889b2d2954e91d4de5118a5da6b78dd53"
)


@pytest.fixture
def catalog_data():
    return {
        "models": [
            {
                "model_id": "provider/model",
                "reasoning_efforts": [None, "low", "high"],
                "context_window_tokens": 16384,
                "max_output_tokens": 1000,
            }
        ],
        "default": {"model_id": "provider/model", "reasoning_effort": None},
    }


@pytest.fixture
def configured_env(monkeypatch, tmp_path, catalog_data):
    catalog = tmp_path / "models.json"
    catalog.write_text(json.dumps(catalog_data))
    values = {
        "LISTEN_ADDR": "127.0.0.1:8000",
        "RPC_LISTEN_ADDR": "127.0.0.1:8001",
        "DATABASE_URL": "postgresql://leta:fixture-password@localhost:5432/leta",
        "REDIS_URL": "redis://localhost:6379/0",
        "TEMPORAL_ADDRESS": "localhost:7233",
        "TEMPORAL_NAMESPACE": "default",
        "GATEWAY_TOKEN": "g" * 32,
        "LETA_SERVICE_TOKEN": "l" * 32,
        "WORKSPACE_SERVICE_TOKEN": "w" * 32,
        "ACCOUNT_RPC_ADDRESS": "localhost:9091",
        "WORKSPACE_RPC_ADDRESS": "localhost:9092",
        "LETFS_RPC_ADDRESS": "localhost:9093",
        "SPICEDB_ADDRESS": "localhost:50051",
        "SPICEDB_GRPC_PRESHARED_KEY": "fixture-spicedb-key",
        "ALLOW_PLAINTEXT_RPC": "true",
        "OPENROUTER_API_KEY": "fixture-provider-key",
        "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
        "LETA_MODEL_CATALOG_PATH": str(catalog),
    }
    for key, value in values.items():
        monkeypatch.delenv(f"{key}_FILE", raising=False)
        monkeypatch.setenv(key, value)
    return values


@pytest.fixture
def settings(configured_env):
    return Settings.from_env()


@contextmanager
def container(image, port, *arguments, command=()):
    name = "openlet-leta-test-" + secrets.token_hex(6)
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                name,
                "--publish",
                f"127.0.0.1::{port}",
                *arguments,
                image,
                *command,
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        mapped = (
            subprocess.run(
                ["docker", "port", name, str(port)],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            .stdout.strip()
            .rsplit(":", 1)[1]
        )
        yield name, int(mapped)
    finally:
        subprocess.run(
            ["docker", "rm", "--force", name], capture_output=True, timeout=30
        )


@pytest.fixture
def postgres_dsn():
    import psycopg

    with container(
        POSTGRES_IMAGE,
        5432,
        "--env",
        "POSTGRES_PASSWORD=fixture-password",
        "--env",
        "POSTGRES_DB=leta_test",
    ) as (_, port):
        dsn = f"postgresql://postgres:fixture-password@127.0.0.1:{port}/leta_test"
        deadline = time.monotonic() + 30
        while True:
            try:
                with psycopg.connect(dsn, connect_timeout=1):
                    break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    pytest.fail("owned PostgreSQL did not become ready")
                time.sleep(0.1)
        yield dsn


@pytest.fixture
def redis_url():
    from redis import Redis
    from redis.exceptions import ConnectionError

    with container(REDIS_IMAGE, 6379) as (_, port):
        url = f"redis://127.0.0.1:{port}/0"
        with Redis.from_url(url, socket_connect_timeout=1) as client:
            deadline = time.monotonic() + 15
            while True:
                try:
                    client.ping()
                    break
                except ConnectionError:
                    if time.monotonic() >= deadline:
                        pytest.fail("owned Redis did not become ready")
                    time.sleep(0.1)
        yield url


@pytest.fixture
async def temporal_environment():
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.testing import WorkflowEnvironment

    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter
    ) as environment:
        yield environment


@pytest.fixture
async def persistent_temporal():
    from temporalio.client import Client
    from temporalio.contrib.pydantic import pydantic_data_converter

    # Match the existing Go fixture, without borrowing a developer namespace.
    image = (
        "temporalio/admin-tools:1.32.2@sha256:"
        "4a95866efba29d7e17ab012df5232795e8b0ad0f7d5f9d1ec4df321f7792a754"
    )
    with container(
        image,
        7233,
        "--entrypoint",
        "temporal",
        command=(
            "server",
            "start-dev",
            "--ip",
            "0.0.0.0",
            "--headless",
            "--namespace",
            "leta-test",
            "--port",
            "7233",
        ),
    ) as (name, port):
        import asyncio

        async with asyncio.timeout(45):
            while True:
                process = await asyncio.create_subprocess_exec(
                    "docker",
                    "exec",
                    name,
                    "temporal",
                    "operator",
                    "namespace",
                    "describe",
                    "--namespace",
                    "leta-test",
                    "--address",
                    "127.0.0.1:7233",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    if await process.wait() == 0:
                        break
                finally:
                    if process.returncode is None:
                        process.terminate()
                        await process.wait()
                await asyncio.sleep(0.1)
        yield await Client.connect(
            f"127.0.0.1:{port}",
            namespace="leta-test",
            data_converter=pydantic_data_converter,
        )


@pytest.fixture(scope="session")
def goose_binary(tmp_path_factory):
    existing = shutil.which("goose")
    if existing:
        return Path(existing)
    directory = tmp_path_factory.mktemp("leta-migration-tools")
    bootstrap = Path(__file__).parents[3] / "infra/bootstrap/Dockerfile"
    version = re.search(
        r"github.com/pressly/goose/v3/cmd/goose@(v[\d.]+)", bootstrap.read_text()
    ).group(1)
    subprocess.run(
        [
            "go",
            "install",
            "-tags",
            "no_mysql no_sqlite3 no_ydb no_mssql no_clickhouse no_libsql no_vertica",
            f"github.com/pressly/goose/v3/cmd/goose@{version}",
        ],
        env={**os.environ, "GOBIN": str(directory), "GOWORK": "off"},
        check=True,
        capture_output=True,
        timeout=180,
    )
    return directory / "goose"


@pytest.fixture
async def store(postgres_dsn, goose_binary, monkeypatch, catalog_data):
    from psycopg_pool import AsyncConnectionPool

    from leta.config import ModelCatalog
    from leta.migrate import migrate
    from leta.store import Store

    monkeypatch.setenv(
        "PATH", str(goose_binary.parent) + os.pathsep + os.environ["PATH"]
    )
    await migrate(postgres_dsn)
    async with AsyncConnectionPool(
        postgres_dsn,
        min_size=1,
        max_size=8,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    ) as pool:
        await pool.wait()
        yield Store(pool, ModelCatalog.model_validate(catalog_data))
