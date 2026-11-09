"""Owned process: die after a real tool result commit, before its graph checkpoint."""

import asyncio
import json
import os
import signal

from langchain_core.tools import tool
from psycopg_pool import AsyncConnectionPool
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from test_runtime import RecordingModel, TestWorkspaces, call

from leta.config import ModelCatalog
from leta.domain import ActivityKind, NewLeta
from leta.runtime import runner as runner_module
from leta.runtime.runner import AgentRunner
from leta.store import Store
from leta.worker import agent_workers


class CrashAfterResult(Store):
    async def append_activity(self, value):
        result = await super().append_activity(value)
        if value.kind == ActivityKind.TOOL_RESULT:
            os.kill(os.getpid(), signal.SIGKILL)
        return result


async def main():
    fixture = json.loads(os.environ["OPENLET_OWNED_RUNTIME_CRASH"])
    client = await Client.connect(
        fixture["address"],
        namespace="leta-test",
        data_converter=pydantic_data_converter,
    )
    async with AsyncConnectionPool(
        fixture["database_url"],
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    ) as pool:
        store = CrashAfterResult(pool, ModelCatalog.model_validate(fixture["models"]))

        @tool
        async def run_shell(command: str) -> str:
            """Represent an opaque command effect using committed SQL."""
            async with store.transaction() as cursor:
                await cursor.execute("INSERT INTO fixture_shell_effects DEFAULT VALUES")
            return "command finished"

        runner_module.build_tools = lambda context: [run_shell]

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def provider():
            yield lambda selection: RecordingModel(
                responses=[call("run_shell", command="do work")]
            )

        runner = AgentRunner(
            store,
            TestWorkspaces(NewLeta.model_validate(fixture["root"])),
            fixture["database_url"],
            provider,
            client,
        )
        async with agent_workers(client, store, runner.run_agent):
            await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
