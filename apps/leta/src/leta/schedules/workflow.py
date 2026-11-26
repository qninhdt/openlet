from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from temporalio import workflow
from temporalio.common import RetryPolicy


@workflow.defn(name="ScheduleFireWorkflow")
class ScheduleFireWorkflow:
    @workflow.run
    async def run(self, schedule_id: str) -> None:
        attrs = workflow.info().search_attributes
        raw_times = attrs.get("TemporalScheduledStartTime")
        if raw_times and isinstance(raw_times[0], datetime):
            nominal_time = raw_times[0]
        else:
            nominal_time = workflow.now()
        await workflow.execute_activity(
            "fire_schedule",
            args=[UUID(schedule_id), nominal_time],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
