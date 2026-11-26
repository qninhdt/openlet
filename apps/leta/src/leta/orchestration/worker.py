from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from typing import Literal

from openlet_sdk.config import load
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.worker import Worker

from ..config import Services
from ..hitl.workflow import HitlWorkflow
from ..observability import setup_observability
from ..schedules.workflow import ScheduleFireWorkflow
from .activities import OrchestrationActivities, RuntimeActivities
from .agent_workflow import AgentWorkflow
from .lifecycle_workflow import LetaLifecycleWorkflow

logger = logging.getLogger(__name__)


async def run_worker(role: Literal["all", "orchestration", "runtime"] = "all") -> None:
    cfg = load()
    shutdown_obs, lf = setup_observability("openlet-leta-worker", cfg)
    services = await Services.create(cfg, langfuse=lf)
    orch_acts = OrchestrationActivities(services)
    run_acts = RuntimeActivities(services)
    workers: list[Worker] = []

    if role in ("all", "orchestration"):
        workers.append(
            Worker(
                services.temporal,
                task_queue=services.queues.orchestration,
                workflows=[
                    AgentWorkflow,
                    LetaLifecycleWorkflow,
                    HitlWorkflow,
                    ScheduleFireWorkflow,
                ],
                activities=[
                    orch_acts.finish_run,
                    orch_acts.notify_parent_failure,
                    orch_acts.stop_child_agents,
                    orch_acts.prepare_leta_db,
                    orch_acts.provision_leta_resources,
                    orch_acts.mark_leta_deleting,
                    orch_acts.cleanup_leta_schedules,
                    orch_acts.cleanup_leta_hitl,
                    orch_acts.cleanup_leta_agents,
                    orch_acts.cleanup_leta_resources,
                    orch_acts.open_hitl,
                    orch_acts.resolve_hitl,
                    orch_acts.apply_hitl_effect,
                    orch_acts.deliver_hitl_result,
                    orch_acts.fire_schedule,
                ],
                interceptors=[TracingInterceptor()],
                max_concurrent_activities=services.settings.orchestration.max_concurrent_orchestration_activities,
            )
        )

    if role in ("all", "runtime"):
        workers.append(
            Worker(
                services.temporal,
                task_queue=services.queues.runtime,
                activities=[run_acts.run_agent_turn],
                interceptors=[TracingInterceptor()],
                max_concurrent_activities=services.settings.orchestration.max_concurrent_runtime_activities,
            )
        )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    tasks = [asyncio.create_task(w.run()) for w in workers]
    logger.info("leta worker started (role=%s, workers=%d)", role, len(workers))
    try:
        await stop_event.wait()
    finally:
        for w in workers:
            await w.shutdown()
        await asyncio.gather(*tasks, return_exceptions=True)
        await services.close()
        shutdown_obs()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Leta Temporal worker")
    parser.add_argument(
        "--role",
        choices=("all", "orchestration", "runtime"),
        default="all",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker(args.role))


if __name__ == "__main__":
    main()
