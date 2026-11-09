"""Explicit migration job; API and workers never migrate on startup."""

import asyncio
import os
import subprocess
from pathlib import Path

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from openlet.config import secret
from openlet.errors import AppError
from psycopg import AsyncConnection
from psycopg.errors import UndefinedTable


async def verify_schema(connection: AsyncConnection):
    """Readiness checks versions; only the explicit migration job changes them."""
    error = AppError(
        "Leta database migrations are not current",
        reason="DEPENDENCY_UNAVAILABLE",
        kind="unavailable",
    )
    try:
        current = await (
            await connection.execute(
                "SELECT version_id,is_applied,"
                "(SELECT max(v) FROM checkpoint_migrations) "
                "FROM goose_db_version ORDER BY id DESC LIMIT 1"
            )
        ).fetchone()
    except UndefinedTable:
        raise error from None
    if current != (2, True, len(AsyncPostgresSaver.MIGRATIONS) - 1):
        raise error


async def migrate(database_url: str):
    packaged = Path(__file__).parent / "migrations"
    directory = (
        packaged if packaged.is_dir() else Path(__file__).parents[2] / "migrations"
    )
    environment = {
        **os.environ,
        "GOOSE_DRIVER": "postgres",
        "GOOSE_DBSTRING": database_url,
        "GOOSE_MIGRATION_DIR": str(directory),
    }
    # Goose is the same pinned binary used by the existing service migration jobs.
    await asyncio.to_thread(
        subprocess.run, ["goose", "up"], env=environment, check=True
    )
    async with AsyncPostgresSaver.from_conn_string(database_url) as saver:
        await saver.setup()


if __name__ == "__main__":
    asyncio.run(migrate(secret("DATABASE_URL")))
