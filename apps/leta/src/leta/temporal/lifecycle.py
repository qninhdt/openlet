import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from leta.temporal.agent import local
    from leta.temporal.human_types import SettleHumanRequest
    from leta.temporal.lifecycle_types import (
        LetaChange,
        LifecycleAgentControl,
        LifecycleSnapshot,
        LifecycleStart,
        ResourceRef,
    )
    from leta.temporal.publication import publish
    from leta.temporal.schedule_types import ScheduleChange
    from leta.temporal.types import AgentControl, AgentRef


async def remote(name, value, result_type=None):
    return await workflow.execute_activity(
        name,
        value,
        result_type=result_type,
        start_to_close_timeout=timedelta(minutes=2),
        heartbeat_timeout=timedelta(seconds=10) if name == "control_agent" else None,
    )


def should_rotate(start: LifecycleStart):
    info = workflow.info()
    return (
        info.is_continue_as_new_suggested()
        or info.get_current_history_length() >= start.history_events
        or info.get_current_history_size() >= start.history_bytes
    )


async def lifecycle_loop(start: LifecycleStart, closed):
    await workflow.wait_condition(lambda: closed() or should_rotate(start))
    await workflow.wait_condition(workflow.all_handlers_finished)
    if not closed():
        workflow.continue_as_new(start)


async def control_agents(leta_id, agent_ids, action):
    # A fixed window bounds remote work without making box size a product limit.
    for offset in range(0, len(agent_ids), 8):
        await asyncio.gather(
            *(
                remote(
                    "control_agent",
                    LifecycleAgentControl(
                        leta_id=leta_id,
                        agent_id=agent_id,
                        control=AgentControl(action=action),
                    ),
                )
                for agent_id in agent_ids[offset : offset + 8]
            )
        )


@workflow.defn
class LetaLifecycleWorkflow:
    @workflow.init
    def __init__(self, start: LifecycleStart):
        self.start = start
        self.changing = asyncio.Lock()
        self.closed = False

    @workflow.update
    async def change(self, value: LetaChange) -> LifecycleSnapshot:
        async with self.changing:
            snapshot = await local("save_leta_change", value, LifecycleSnapshot)
            await publish(value.leta_id, "agent", value.leta_id)
            if value.action == "create":
                ref = ResourceRef(leta_id=value.leta_id)
                await remote("publish_leta_resource", ref)
                try:
                    await remote("ensure_leta_home", ref)
                except ActivityError as error:
                    if (
                        not isinstance(error.cause, ApplicationError)
                        or error.cause.type != "WORKSPACE_DELETING"
                    ):
                        raise
                    await local(
                        "save_leta_change",
                        LetaChange(leta_id=value.leta_id, action="deleting"),
                        LifecycleSnapshot,
                    )
                    await remote(
                        "publish_leta_resource",
                        ResourceRef(leta_id=value.leta_id, remove=True),
                    )
                    await local(
                        "save_leta_change",
                        LetaChange(leta_id=value.leta_id, action="archived"),
                        LifecycleSnapshot,
                    )
                    self.closed = True
                    await publish(value.leta_id, "agent", value.leta_id)
                    raise
                snapshot = await local(
                    "save_leta_change",
                    LetaChange(leta_id=value.leta_id, action="active"),
                    LifecycleSnapshot,
                )
                await remote(
                    "start_agent",
                    AgentRef(leta_id=value.leta_id, agent_id=value.leta_id),
                )
                await publish(value.leta_id, "agent", value.leta_id)
            elif value.action in {"pause", "resume"}:
                await control_agents(value.leta_id, snapshot.agent_ids, value.action)
            elif value.action == "deleting":
                for schedule_id in snapshot.schedule_ids:
                    await remote(
                        "change_schedule",
                        ScheduleChange(
                            leta_id=value.leta_id,
                            schedule_id=schedule_id,
                            requester_agent_id=value.leta_id,
                            action="delete",
                            requested_at=workflow.now(),
                        ),
                    )
                for request_id in snapshot.request_ids:
                    await remote(
                        "settle_hitl",
                        SettleHumanRequest(
                            leta_id=value.leta_id,
                            request_id=request_id,
                            reason="leta_archived",
                        ),
                    )
                await control_agents(value.leta_id, snapshot.agent_ids, "stop")
                for box_id in snapshot.box_ids:
                    try:
                        await workflow.get_external_workflow_handle(
                            f"box-lifecycle/{box_id}"
                        ).cancel()
                    except ApplicationError as error:
                        if error.type != "ExternalWorkflowExecutionNotFound":
                            raise
                ref = ResourceRef(
                    leta_id=value.leta_id, remove=value.workspace_deletion
                )
                await remote("cleanup_leta_access", ref)
                if value.workspace_deletion:
                    await remote("publish_leta_resource", ref)
                snapshot = await local(
                    "save_leta_change",
                    LetaChange(leta_id=value.leta_id, action="archived"),
                    LifecycleSnapshot,
                )
                self.closed = True
                await publish(value.leta_id, "agent", value.leta_id)
            return snapshot

    @change.validator
    def validate_change(self, value: LetaChange):
        if value.leta_id != self.start.leta_id or value.action not in {
            "create",
            "configure",
            "pause",
            "resume",
            "deleting",
        }:
            raise ApplicationError(
                "invalid Leta lifecycle command", type="VALIDATION", non_retryable=True
            )

    @workflow.run
    async def run(self, start: LifecycleStart) -> None:
        if start.box_id is not None:
            raise ApplicationError(
                "root coordinator cannot bind a box", non_retryable=True
            )
        await lifecycle_loop(start, lambda: self.closed)
