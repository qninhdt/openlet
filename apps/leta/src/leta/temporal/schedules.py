"""Serialized definition changes and independent occurrence delivery."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import SearchAttributeKey
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from leta.temporal.agent import local
    from leta.temporal.lifecycle import remote, should_rotate
    from leta.temporal.publication import publish
    from leta.temporal.schedule_types import (
        ScheduleChange,
        ScheduleDefinition,
        ScheduleOccurrence,
        ScheduleSnapshot,
        ScheduleStart,
    )


@workflow.defn
class ScheduleChangesWorkflow:
    @workflow.init
    def __init__(self, start: ScheduleStart):
        self.start = start
        self.changing = asyncio.Lock()
        self.deleted = False
        self.saved = None

    @workflow.update
    async def change(self, value: ScheduleChange) -> ScheduleDefinition:
        async with self.changing:
            saved = await local("save_schedule_change", value, ScheduleDefinition)
            await remote("apply_temporal_schedule", saved)
            await publish(value.leta_id, "schedule", value.schedule_id)
            self.saved = saved
            self.deleted = saved.deleted_at is not None
            return saved

    @change.validator
    def validate_change(self, value: ScheduleChange):
        if (
            value.leta_id != self.start.leta_id
            or value.schedule_id != self.start.schedule_id
        ):
            raise ApplicationError(
                "change targets another schedule", type="VALIDATION", non_retryable=True
            )

    @workflow.run
    async def run(self, start: ScheduleStart) -> ScheduleDefinition:
        await workflow.wait_condition(lambda: self.deleted or should_rotate(start))
        await workflow.wait_condition(workflow.all_handlers_finished)
        if not self.deleted:
            workflow.continue_as_new(start)
        return self.saved


@workflow.defn
class ScheduleDeliveryWorkflow:
    @workflow.run
    async def run(self, value: ScheduleOccurrence) -> str:
        if value.scheduled_at is None:
            attributes = workflow.info().typed_search_attributes
            scheduled_at = attributes.get(
                SearchAttributeKey.for_datetime("TemporalScheduledStartTime")
            )
            source = attributes.get(
                SearchAttributeKey.for_keyword("TemporalScheduledById")
            )
            if scheduled_at is None or source != f"schedule/{value.schedule_id}":
                raise ApplicationError(
                    "missing or mismatched native schedule metadata",
                    type="VALIDATION",
                    non_retryable=True,
                )
            value = value.model_copy(update={"scheduled_at": scheduled_at})
        snapshot = await local("load_schedule_occurrence", value, ScheduleSnapshot)
        if snapshot.delivery is None:
            return "skipped"
        return await workflow.execute_activity(
            "deliver_agent_input",
            snapshot.delivery,
            result_type=str,
            start_to_close_timeout=timedelta(seconds=45),
        )
