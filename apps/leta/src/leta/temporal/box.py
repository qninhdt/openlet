import asyncio

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from leta.temporal.agent import local
    from leta.temporal.human_types import SettleHumanRequest
    from leta.temporal.lifecycle import control_agents, lifecycle_loop, remote
    from leta.temporal.lifecycle_types import (
        BoxChange,
        LifecycleSnapshot,
        LifecycleStart,
        ResourceRef,
    )
    from leta.temporal.publication import publish
    from leta.temporal.schedule_types import ScheduleChange
    from leta.temporal.types import AgentRef


@workflow.defn
class BoxLifecycleWorkflow:
    @workflow.init
    def __init__(self, start: LifecycleStart):
        self.start = start
        self.changing = asyncio.Lock()
        self.closed = False

    @workflow.update
    async def change(self, value: BoxChange) -> LifecycleSnapshot:
        async with self.changing:
            snapshot = await local("save_box_change", value, LifecycleSnapshot)
            await publish(value.leta_id, "box", value.box_id)
            ref = ResourceRef(leta_id=value.leta_id, box_id=value.box_id)
            if value.action == "create":
                await remote("ensure_box_home", ref)
                snapshot = await local(
                    "save_box_change",
                    BoxChange(
                        leta_id=value.leta_id, box_id=value.box_id, action="active"
                    ),
                    LifecycleSnapshot,
                )
                for offset in range(0, len(snapshot.agent_ids), 8):
                    await asyncio.gather(
                        *(
                            remote(
                                "start_agent",
                                AgentRef(leta_id=value.leta_id, agent_id=agent_id),
                            )
                            for agent_id in snapshot.agent_ids[offset : offset + 8]
                        )
                    )
            else:
                # Concrete source settlement is supplied by the HITL/schedule phases.
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
                            reason="box_deleted",
                        ),
                    )
                await control_agents(value.leta_id, snapshot.agent_ids, "stop")
                await remote("trash_box_home", ref)
                snapshot = await local(
                    "save_box_change",
                    BoxChange(
                        leta_id=value.leta_id, box_id=value.box_id, action="archived"
                    ),
                    LifecycleSnapshot,
                )
            self.closed = snapshot.status == "archived"
            await publish(value.leta_id, "box", value.box_id)
            return snapshot

    @change.validator
    def validate_change(self, value: BoxChange):
        if (
            value.leta_id != self.start.leta_id
            or value.box_id != self.start.box_id
            or value.action not in {"create", "deleting"}
        ):
            raise ApplicationError(
                "invalid box lifecycle command", type="VALIDATION", non_retryable=True
            )

    @workflow.run
    async def run(self, start: LifecycleStart) -> None:
        if start.box_id is None:
            raise ApplicationError(
                "box coordinator requires a box ID", non_retryable=True
            )
        await lifecycle_loop(start, lambda: self.closed)
