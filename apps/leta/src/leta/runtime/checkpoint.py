from __future__ import annotations

import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from openlet_sdk.config import Config, load

from ..db import Pool, open_pool


def make_checkpointer(pool: Pool) -> AsyncPostgresSaver:
    return AsyncPostgresSaver(pool)


async def setup_checkpointer(cfg: Config | None = None) -> None:
    pool = await open_pool(cfg or load(), min_size=1, max_size=2)
    try:
        saver = make_checkpointer(pool)
        await saver.setup()
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(setup_checkpointer())
