import asyncio
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import UUID

from temporalio import workflow
from temporalio.exceptions import ApplicationError

from .retry import RETRY

with workflow.unsafe.imports_passed_through():
    from openlet_sdk.config import JSON
    from pydantic import BaseModel

    from ..messages import Message
    from ..schedules import CanonicalChange, Change


class ScheduleInput(BaseModel):
    schedule_id: UUID
    bridge_queue: str


@workflow.defn
class ScheduleChanges:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.deleted = False
        self.rotating = False
        self.input: ScheduleInput | None = None

    @workflow.update
    async def change(self, request: Change) -> dict[str, JSON]:
        async with self.lock:
            canonical = CanonicalChange(request=request, now=workflow.now())
            result = await workflow.execute_local_activity(
                "save_schedule_change",
                canonical,
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(seconds=15),
                result_type=dict[str, JSON],
            )
            if not result["finalized"]:
                await workflow.execute_activity(
                    "apply_native_schedule",
                    args=[canonical, result["result"]],
                    retry_policy=RETRY,
                    start_to_close_timeout=timedelta(minutes=2),
                )
            self.deleted = request.action == "delete"
            self.rotating |= workflow.info().is_continue_as_new_suggested()
            return cast(dict[str, JSON], result["result"])

    @change.validator
    def validate_change(self, request: Change) -> None:
        if self.input is None or request.schedule_id != self.input.schedule_id:
            raise ValueError("schedule does not match workflow")
        if self.rotating or self.deleted:
            raise ApplicationError(
                "schedule execution is closed", type="admission_closed"
            )

    @workflow.run
    async def run(self, input: ScheduleInput) -> None:
        self.input = input
        await workflow.wait_condition(lambda: self.deleted or self.rotating)
        await workflow.wait_condition(workflow.all_handlers_finished)
        if not self.deleted:
            workflow.continue_as_new(input)


@workflow.defn
class ScheduleDelivery:
    @workflow.run
    async def run(self, schedule_id: str) -> None:
        fields = workflow.info().search_attributes.get("TemporalScheduledStartTime")
        if not fields or not isinstance(fields[0], datetime):
            raise ApplicationError(
                "native scheduled start time is required", non_retryable=True
            )
        nominal = fields[0].astimezone(timezone.utc)
        message = await workflow.execute_local_activity(
            "load_schedule_occurrence",
            args=[UUID(schedule_id), nominal],
            retry_policy=RETRY,
            start_to_close_timeout=timedelta(seconds=15),
            result_type=cast(type[Message | None], Message | None),
        )
        if message is not None:
            queues = workflow.memo()
            await workflow.execute_activity(
                "deliver_input",
                message,
                task_queue=str(queues["bridge_queue"]),
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(minutes=2),
            )
