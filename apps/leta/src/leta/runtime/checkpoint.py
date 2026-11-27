"""Postgres checkpointer factory and schema setup utilities."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from openlet_sdk.config import load

from leta.db import open_pool

if TYPE_CHECKING:
    from openlet_sdk.config import Config

    from leta.db import Pool


def make_checkpointer(pool: Pool) -> AsyncPostgresSaver:
    """Create an ``AsyncPostgresSaver`` bound to an open connection pool."""
    return AsyncPostgresSaver(pool)


async def setup_checkpointer(cfg: Config | None = None) -> None:
    """Create LangGraph checkpoint tables if they do not yet exist."""
    pool = await open_pool(cfg or load(), min_size=1, max_size=2)
    try:
        saver = make_checkpointer(pool)
        await saver.setup()
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(setup_checkpointer())
