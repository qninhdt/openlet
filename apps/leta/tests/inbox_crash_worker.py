"""Owned crash-test process: die after SQL commit, before a Local Activity marker."""

import asyncio
import json
import os
import signal

from psycopg_pool import AsyncConnectionPool
from temporalio import activity
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from leta.config import ModelCatalog
from leta.store import Store
from leta.temporal.activities import AgentActivities
from leta.temporal.agent import AgentWorkflow
from leta.temporal.publication import PublicationActivities
from leta.temporal.types import ORCHESTRATION_QUEUE, AgentInput, InboxReceipt


class CrashAfterCommit(AgentActivities):
    @activity.defn
    async def persist_inbox(self, value: AgentInput) -> InboxReceipt:
        await super().persist_inbox(value)
        os.kill(os.getpid(), signal.SIGKILL)
        raise AssertionError("crash fixture unexpectedly survived SIGKILL")


async def main():
    fixture = json.loads(os.environ["OPENLET_OWNED_INBOX_CRASH"])
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
        sql = CrashAfterCommit(
            Store(pool, ModelCatalog.model_validate(fixture["models"])), client
        )
        async with Worker(
            client,
            task_queue=ORCHESTRATION_QUEUE,
            workflows=[AgentWorkflow],
            activities=[
                PublicationActivities(None).publish_resource_event,
                sql.bootstrap_agent,
                sql.persist_inbox,
                sql.save_run_control,
            ],
        ):
            await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
