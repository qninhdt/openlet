from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast
from urllib.parse import quote
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from openlet_sdk.config import JSON, Config, load, secret
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

type Pool = AsyncConnectionPool[Any]
type Row = DictRow


class WriterBusyError(RuntimeError):
    """Retryable error raised when another active lease holds the agent writer lock."""


class LeaseLostError(RuntimeError):
    """Raised when a worker loses its DB lease/fencing token mid-run."""


def database_dsn(cfg: Config) -> str:
    pg = cfg["dependencies"]["postgres"]
    db = cfg["services"]["leta"]["database"]
    pw = secret(db["password"])
    return (
        f"postgresql://{quote(db['user'], safe='')}:{quote(pw, safe='')}"
        f"@{pg['host']}:{pg['port']}/{db['name']}?sslmode={pg['sslmode']}"
    )


async def open_pool(cfg: Config, *, min_size: int = 2, max_size: int = 24) -> Pool:
    pool: Pool = AsyncConnectionPool(
        conninfo=database_dsn(cfg),
        min_size=min_size,
        max_size=max_size,
        open=False,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "prepare_threshold": 0,
        },
    )
    await pool.open(wait=True)
    return pool


def make_checkpointer(pool: Pool) -> AsyncPostgresSaver:
    return AsyncPostgresSaver(pool)


async def setup_checkpointer(cfg: Config | None = None) -> None:
    pool = await open_pool(cfg or load(), min_size=1, max_size=2)
    try:
        saver = make_checkpointer(pool)
        await saver.setup()
    finally:
        await pool.close()


async def acquire_lease(
    pool: Pool, agent_id: UUID, lease_token: UUID, ttl_seconds: int = 30
) -> None:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """
                UPDATE agents
                SET lease_token = %s,
                    lease_expires_at = now() + make_interval(secs => %s)
                WHERE id = %s
                  AND state = 'active'
                  AND (lease_expires_at IS NULL OR lease_expires_at < now())
                RETURNING id
                """,
                (lease_token, ttl_seconds, agent_id),
            )
        ).fetchone()
    if row is None:
        raise WriterBusyError(f"agent {agent_id} is currently leased or inactive")


async def renew_lease(
    pool: Pool, agent_id: UUID, lease_token: UUID, ttl_seconds: int = 30
) -> bool:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """
                UPDATE agents
                SET lease_expires_at = now() + make_interval(secs => %s)
                WHERE id = %s AND lease_token = %s
                RETURNING id
                """,
                (ttl_seconds, agent_id, lease_token),
            )
        ).fetchone()
    return row is not None


async def release_lease(pool: Pool, agent_id: UUID, lease_token: UUID) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """
            UPDATE agents
            SET lease_token = NULL, lease_expires_at = NULL
            WHERE id = %s AND lease_token = %s
            """,
            (agent_id, lease_token),
        )


def hash_request(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def get_receipt(
    pool: Pool, scope: str, action: str, request_id: UUID, request_hash: str
) -> dict[str, JSON] | None:
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                """
                SELECT request_hash, response
                FROM idempotency_receipts
                WHERE scope = %s AND action = %s AND request_id = %s
                """,
                (scope, action, request_id),
            )
        ).fetchone()
    if row is None:
        return None
    if row["request_hash"] != request_hash:
        raise ValueError("idempotency_key reused with different request payload")
    return cast(dict[str, JSON], row["response"])


async def save_receipt(
    pool: Pool,
    scope: str,
    action: str,
    request_id: UUID,
    request_hash: str,
    response: dict[str, JSON],
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO idempotency_receipts(scope, action, request_id, request_hash, response)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (scope, action, request_id) DO NOTHING
            """,
            (scope, action, request_id, request_hash, Jsonb(response)),
        )


async def sweep_receipts(pool: Pool, retention_days: int = 7) -> int:
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            DELETE FROM idempotency_receipts
            WHERE created_at < now() - make_interval(days => %s)
            """,
            (retention_days,),
        )
        return int(cur.rowcount or 0)


def json_value(value: object) -> JSON:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(k): json_value(v) for k, v in mapping.items()}
    if isinstance(value, (list, tuple)):
        seq = cast(list[object] | tuple[object, ...], value)
        return [json_value(v) for v in seq]
    return str(value)


def json_row(row: Mapping[str, object]) -> dict[str, JSON]:
    return {str(k): json_value(v) for k, v in row.items()}


if __name__ == "__main__":
    asyncio.run(setup_checkpointer())
