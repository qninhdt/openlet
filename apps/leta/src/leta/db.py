import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from openlet_sdk.config import JSON, load, secret
from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

type Row = dict[str, object]
type Connection = AsyncConnection[Row]
type Pool = AsyncConnectionPool[Connection]


def dsn() -> str:
    config = load()
    postgres = config["dependencies"]["postgres"]
    database = config["services"]["leta"]["database"]
    return make_conninfo(
        host=postgres["host"],
        port=postgres["port"],
        sslmode=postgres["sslmode"],
        dbname=database["name"],
        user=database["user"],
        password=secret(database["password"]),
    )


def pool() -> Pool:
    return AsyncConnectionPool(
        dsn(),
        min_size=2,
        max_size=24,
        open=False,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )


def request_hash(request: BaseModel) -> bytes:
    canonical = json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode()).digest()


async def receipt(
    connection: Connection, caller: str, method: str, key: UUID, request: BaseModel
) -> JSON:
    row = await (
        await connection.execute(
            "SELECT request_hash,result FROM idempotency_keys WHERE caller=%s AND method=%s AND key=%s",
            (caller, method, key),
        )
    ).fetchone()
    if row is None:
        return None
    if bytes(cast(bytes, row["request_hash"])) != request_hash(request):
        raise ValueError("request ID was already used with different input")
    result = cast(bytes | None, row["result"])
    return cast(JSON, json.loads(bytes(result))) if result is not None else None


async def save_receipt(
    connection: Connection,
    caller: str,
    method: str,
    key: UUID,
    request: BaseModel,
    result: JSON,
) -> None:
    await connection.execute(
        """INSERT INTO idempotency_keys(caller,method,key,request_hash,result,expires_at)
           VALUES(%s,%s,%s,%s,%s,'infinity'::timestamptz)""",
        (caller, method, key, request_hash(request), json.dumps(result).encode()),
    )


async def setup() -> None:
    async with AsyncPostgresSaver.from_conn_string(dsn()) as saver:
        await saver.setup()


@asynccontextmanager
async def effect(db: Pool, root: UUID) -> AsyncIterator[None]:
    async with db.connection() as connection:
        await connection.execute(
            "SELECT pg_advisory_lock(hashtextextended(%s,1))", (str(root),)
        )
        try:
            yield
        finally:
            await connection.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s,1))", (str(root),)
            )


if __name__ == "__main__":
    asyncio.run(setup())
