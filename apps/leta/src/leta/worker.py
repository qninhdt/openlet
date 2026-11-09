import argparse
import asyncio
import signal
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta

from openlet.clients.letfs import FilesystemClient
from openlet.clients.workspace import WorkspaceClient
from temporalio.client import Client
from temporalio.worker import Worker

from leta.config import Settings
from leta.filesystem.workspace import WorkspaceFactory
from leta.lifespan import resources
from leta.runtime.runner import AgentRunner, openrouter_models
from leta.store import Store
from leta.streaming import Publisher
from leta.temporal.activities import AgentActivities
from leta.temporal.agent import AgentWorkflow
from leta.temporal.box import BoxLifecycleWorkflow
from leta.temporal.human import HumanRequestWorkflow
from leta.temporal.human_activities import HumanActivities
from leta.temporal.lifecycle import LetaLifecycleWorkflow
from leta.temporal.lifecycle_activities import LifecycleActivities
from leta.temporal.publication import PublicationActivities
from leta.temporal.schedule_activities import ScheduleActivities
from leta.temporal.schedules import ScheduleChangesWorkflow, ScheduleDeliveryWorkflow
from leta.temporal.types import ORCHESTRATION_QUEUE, RUNTIME_QUEUE


@asynccontextmanager
async def agent_workers(
    client: Client,
    store: Store,
    run_agent,
    lifecycle: LifecycleActivities | None = None,
    human: HumanActivities | None = None,
    schedules: ScheduleActivities | None = None,
    *,
    publisher: Publisher | None = None,
):
    """A concrete runner is required; there is no placeholder runtime Activity."""
    sql = AgentActivities(store, client)
    publication = PublicationActivities(publisher)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(
            Worker(
                client,
                task_queue=ORCHESTRATION_QUEUE,
                workflows=[
                    AgentWorkflow,
                    *(
                        [ScheduleChangesWorkflow, ScheduleDeliveryWorkflow]
                        if schedules
                        else []
                    ),
                    *([HumanRequestWorkflow] if human else []),
                    *(
                        [LetaLifecycleWorkflow, BoxLifecycleWorkflow]
                        if lifecycle
                        else []
                    ),
                ],
                activities=[
                    publication.publish_resource_event,
                    sql.bootstrap_agent,
                    sql.persist_inbox,
                    human.deliver_agent_input
                    if human is not None
                    else sql.deliver_agent_input,
                    sql.save_run_control,
                    *(lifecycle.registered() if lifecycle is not None else []),
                    *(human.registered() if human is not None else []),
                    *(schedules.registered() if schedules is not None else []),
                ],
                max_cached_workflows=100,
                max_concurrent_local_activities=16,
                max_concurrent_activities=16,
                graceful_shutdown_timeout=timedelta(seconds=15),
            )
        )
        await stack.enter_async_context(
            Worker(
                client,
                task_queue=RUNTIME_QUEUE,
                activities=[run_agent],
                max_concurrent_activities=8,
                max_heartbeat_throttle_interval=timedelta(seconds=1),
                graceful_shutdown_timeout=timedelta(seconds=15),
            )
        )
        yield


async def run(settings: Settings, stopped: asyncio.Event):
    async with resources(settings) as owned:
        store = Store(owned.database, settings.models)
        scopes = WorkspaceClient(owned.workspace)
        native = FilesystemClient(owned.letfs)
        publisher = Publisher(owned.redis, store)
        workspaces = WorkspaceFactory(
            store,
            scopes,
            native,
            owned.redis,
            settings.redis_url,
            settings.temporal_namespace,
        )
        runner = AgentRunner(
            store,
            workspaces,
            settings.database_url,
            lambda: openrouter_models(settings),
            owned.temporal,
            publisher=publisher,
        )
        async with agent_workers(
            owned.temporal,
            store,
            runner.run_agent,
            LifecycleActivities(store, scopes, native, owned.authz, owned.temporal),
            HumanActivities(store, scopes, owned.temporal),
            ScheduleActivities(store, owned.temporal),
            publisher=publisher,
        ):
            await stopped.wait()


async def main():
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    try:
        await run(Settings.from_env(), stopped)
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


if __name__ == "__main__":
    argparse.ArgumentParser(
        description="Run Leta control and agent workers"
    ).parse_args()
    asyncio.run(main())
