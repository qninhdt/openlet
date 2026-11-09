"""SQL owns definitions; native Schedules own triggering, not product records."""

from dataclasses import fields, replace
from datetime import UTC, datetime
from uuid import uuid5

from openlet.errors import AppError
from openlet.temporal import application_error
from temporalio import activity
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleState,
    ScheduleUpdate,
)
from temporalio.common import (
    WorkflowIDConflictPolicy,
    WorkflowIDReusePolicy,
)
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from leta.domain import NewMessage, Source
from leta.schedules import canonicalize_schedule, compile_schedule
from leta.store import Store
from leta.temporal.schedule_types import (
    ScheduleChange,
    ScheduleDefinition,
    ScheduleOccurrence,
    ScheduleSnapshot,
)
from leta.temporal.schedules import ScheduleDeliveryWorkflow
from leta.temporal.types import ORCHESTRATION_QUEUE, AgentInput


def spec_key(spec):
    """Compare semantic ranges after the server expands SDK range defaults."""

    def calendars(items):
        return tuple(
            tuple(
                (
                    field.name,
                    tuple(
                        (r.start, max(r.start, r.end), r.step or 1)
                        for r in getattr(item, field.name)
                    ),
                )
                for field in fields(item)
                if field.name != "comment"
            )
            for item in items
        )

    return (
        calendars(spec.calendars),
        tuple((v.every, v.offset) for v in spec.intervals),
        tuple(spec.cron_expressions),
        calendars(spec.skip),
        spec.start_at,
        spec.end_at,
        spec.jitter or None,
        spec.time_zone_name or "UTC",
    )


def definition(row):
    return ScheduleDefinition.model_validate(
        {k: row[k] for k in ScheduleDefinition.model_fields}
    )


class ScheduleActivities:
    def __init__(self, store: Store, temporal: Client):
        self.store, self.temporal = store, temporal

    @activity.defn
    async def save_schedule_change(self, value: ScheduleChange) -> ScheduleDefinition:
        try:
            if value.action == "create":
                creation = value.creation.model_copy(
                    update={
                        "spec": canonicalize_schedule(
                            value.creation.spec, now=value.requested_at
                        )
                    }
                )
                compile_schedule(creation.spec, end_at=creation.end_at)
                saved = await self.store.create_schedule(creation)
            elif value.action == "delete":
                saved = await self.store.delete_schedule(
                    value.leta_id, value.schedule_id, value.requester_agent_id
                )
            else:
                patch = value.patch
                if patch.spec is not None:
                    patch = patch.model_copy(
                        update={
                            "spec": canonicalize_schedule(
                                patch.spec, now=value.requested_at
                            )
                        }
                    )
                saved = await self.store.update_schedule(
                    value.leta_id, value.schedule_id, value.requester_agent_id, patch
                )
            return definition(saved)
        except ValueError as error:
            raise application_error(
                AppError(
                    str(error), reason="VALIDATION", kind="invalid", retryable=False
                ),
                fallback="SCHEDULE_FAILED",
                message=str(error),
            ) from error
        except AppError as error:
            raise application_error(
                error, fallback="SCHEDULE_FAILED", message=str(error)
            ) from error

    @activity.defn
    async def apply_temporal_schedule(self, value: ScheduleDefinition) -> None:
        native_id = f"schedule/{value.id}"
        handle = self.temporal.get_schedule_handle(native_id)
        if value.deleted_at is not None:
            try:
                await handle.delete()
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    raise
            return
        spec = compile_schedule(value.spec, end_at=value.end_at)
        one_shot = value.spec["type"] == "at"
        at = datetime.fromisoformat(value.spec["at"]) if one_shot else None
        deliver_due = at is not None and at <= datetime.now(UTC) and not value.paused
        desired = Schedule(
            action=ScheduleActionStartWorkflow(
                ScheduleDeliveryWorkflow.run,
                ScheduleOccurrence(leta_id=value.leta_id, schedule_id=value.id),
                id=f"schedule-delivery/{value.id}",
                task_queue=ORCHESTRATION_QUEUE,
            ),
            spec=spec,
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.BUFFER_ONE),
            state=ScheduleState(
                paused=value.paused,
                limited_actions=one_shot,
                remaining_actions=int(one_shot and not deliver_due),
            ),
        )
        # SDK create rejects zero remaining actions. Provision past-at sources
        # paused, then atomically install the consumed state before direct delivery.
        initial = (
            replace(
                desired, state=replace(desired.state, paused=True, remaining_actions=1)
            )
            if deliver_due
            else desired
        )
        try:
            await self.temporal.create_schedule(native_id, initial)
        except ScheduleAlreadyRunningError:
            pass

        def update(input):
            nonlocal deliver_due
            # Native creation/update can cross a one-shot's nominal due time.
            deliver_due = (
                at is not None and at <= datetime.now(UTC) and not value.paused
            )
            current = input.description.schedule
            if not isinstance(current.action, ScheduleActionStartWorkflow) or (
                current.action.workflow != desired.action.workflow
                or current.action.id != desired.action.id
                or current.action.task_queue != desired.action.task_queue
            ):
                raise ValueError("native schedule action differs from owned definition")
            unchanged_spec = spec_key(current.spec) == spec_key(spec)
            state = replace(desired.state)
            if deliver_due:
                state.remaining_actions = 0
            elif one_shot and unchanged_spec:
                state.remaining_actions = current.state.remaining_actions
            if (
                unchanged_spec
                and current.state == state
                and current.policy == desired.policy
            ):
                return None
            return ScheduleUpdate(replace(desired, state=state))

        await handle.update(update)
        if (
            at is not None
            and not value.paused
            and not deliver_due
            and at <= datetime.now(UTC)
        ):
            await handle.update(update)
        if deliver_due:
            # Retry attaches to this occurrence; never reopen a completed snapshot.
            workflow_id = f"schedule-delivery/{value.id}-" + at.isoformat().replace(
                "+00:00", "Z"
            )
            try:
                await self.temporal.start_workflow(
                    ScheduleDeliveryWorkflow.run,
                    ScheduleOccurrence(
                        leta_id=value.leta_id, schedule_id=value.id, scheduled_at=at
                    ),
                    id=workflow_id,
                    task_queue=ORCHESTRATION_QUEUE,
                    id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                    id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                )
            except WorkflowAlreadyStartedError:
                pass

    @activity.defn
    async def load_schedule_occurrence(
        self, value: ScheduleOccurrence
    ) -> ScheduleSnapshot:
        if value.scheduled_at is None:
            raise ValueError("occurrence requires nominal time")
        at = value.scheduled_at.astimezone(UTC).isoformat()
        message_id = uuid5(value.schedule_id, at)
        try:
            row = await self.store.schedule_occurrence(
                value.leta_id, value.schedule_id, message_id
            )
            if row is None:
                return ScheduleSnapshot()
            return ScheduleSnapshot(
                delivery=AgentInput(
                    schedule_id=value.schedule_id,
                    message=NewMessage(
                        id=message_id,
                        leta_id=value.leta_id,
                        recipient_agent_id=row["target_agent_id"],
                        source=Source(
                            type="schedule",
                            id=str(value.schedule_id),
                            label=row["title"],
                        ),
                        content=row["content"],
                        data={
                            "schedule_id": str(value.schedule_id),
                            "scheduled_at": at,
                            "title": row["title"],
                        },
                    ),
                )
            )
        except AppError as error:
            if error.reason in {"NOT_FOUND", "RESOURCE_INACTIVE"}:
                return ScheduleSnapshot()
            raise application_error(
                error, fallback="SCHEDULE_FAILED", message=str(error)
            ) from error

    @activity.defn
    async def change_schedule(self, value: ScheduleChange) -> ScheduleDefinition:
        from leta.temporal.bridges import change_schedule

        return await change_schedule(
            self.temporal,
            value,
            command_id=activity.info().workflow_id + "/" + str(value.schedule_id),
        )

    def registered(self):
        return [
            self.save_schedule_change,
            self.apply_temporal_schedule,
            self.load_schedule_occurrence,
            self.change_schedule,
        ]
