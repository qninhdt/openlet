"""Owned process: die after a human decision commits, before its Local marker."""

import asyncio
import json
import os
import signal
from types import SimpleNamespace

from psycopg_pool import AsyncConnectionPool
from temporalio import activity
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker

from leta.config import ModelCatalog
from leta.human import RequestResolution
from leta.store import Store
from leta.temporal.human import HumanRequestWorkflow
from leta.temporal.human_activities import HumanActivities
from leta.temporal.human_types import HumanRequestState
from leta.temporal.publication import PublicationActivities
from leta.temporal.types import ORCHESTRATION_QUEUE


class CrashAfterDecision(HumanActivities):
    @activity.defn
    async def resolve_hitl_request(self, value: RequestResolution) -> HumanRequestState:
        await super().resolve_hitl_request(value)
        os.kill(os.getpid(), signal.SIGKILL)
        raise AssertionError("crash fixture unexpectedly survived SIGKILL")


async def main():
    fixture = json.loads(os.environ["OPENLET_OWNED_HUMAN_CRASH"])
    client = await Client.connect(
        fixture["address"],
        namespace=fixture["namespace"],
        data_converter=pydantic_data_converter,
    )
    async with AsyncConnectionPool(
        fixture["database_url"],
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    ) as pool:
        store = Store(pool, ModelCatalog.model_validate(fixture["models"]))
        human = CrashAfterDecision(store, SimpleNamespace(), client)
        async with Worker(
            client,
            task_queue=ORCHESTRATION_QUEUE,
            workflows=[HumanRequestWorkflow],
            activities=[
                PublicationActivities(None).publish_resource_event,
                *human.registered(),
                human.deliver_agent_input,
            ],
        ):
            await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
