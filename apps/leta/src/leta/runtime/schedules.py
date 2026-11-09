"""Agent schedule tools share the native coordinator and persisted definitions."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import TypeAdapter
from temporalio.service import RPCError

from leta.domain import NewSchedule, SchedulePatch
from leta.store import fault
from leta.temporal.bridges import change_schedule
from leta.temporal.schedule_types import ScheduleChange

JSON = TypeAdapter(dict)


def projection(row):
    return JSON.dump_python(
        {
            key: row[key]
            for key in (
                *NewSchedule.model_fields,
                "paused",
                "deleted_at",
                "created_at",
                "updated_at",
            )
        },
        mode="json",
    )


async def get_definition(context, schedule_id):
    row = await context.store.get_schedule(context.request.leta_id, UUID(schedule_id))
    if (
        context.agent["kind"] != "leta"
        and row["target_agent_id"] != context.request.agent_id
    ):
        raise fault("FORBIDDEN", "Leti may inspect only its schedules", "forbidden")
    return row


async def create_schedule(
    context, schedule_id, title, content, spec, target="self", end_at=None
):
    agent_id, box_id = context.request.agent_id, context.agent.get("box_id")
    if target != "self":
        if context.agent["kind"] != "leta":
            raise fault("FORBIDDEN", "Leti may schedule only itself", "forbidden")
        box = await context.store.resolve_box(context.request.leta_id, target)
        agent_id, box_id = box["representative_agent_id"], box["id"]
    creation = NewSchedule(
        id=schedule_id,
        leta_id=context.request.leta_id,
        creator_agent_id=context.request.agent_id,
        target_agent_id=agent_id,
        box_id=box_id,
        title=title,
        content=content,
        spec=spec,
        end_at=end_at,
    )
    result = await change_schedule(
        context.temporal,
        ScheduleChange(
            leta_id=creation.leta_id,
            schedule_id=schedule_id,
            requester_agent_id=context.request.agent_id,
            requested_at=datetime.now(UTC),
            action="create",
            creation=creation,
        ),
        command_id=str(schedule_id),
    )
    return result.model_dump(mode="json")


async def list_schedules(context, box=None, limit=20, cursor=None):
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    target = context.request.agent_id
    if box is not None:
        if context.agent["kind"] != "leta":
            raise fault("FORBIDDEN", "Leti may list only its schedules", "forbidden")
        selected = await context.store.resolve_box(context.request.leta_id, box)
        box_id, target = selected["id"], None
    else:
        box_id = None
    page = await context.store.list_schedules(
        context.request.leta_id,
        target_agent_id=target,
        box_id=box_id,
        after=UUID(cursor) if cursor else None,
        limit=limit + 1,
    )
    return {
        "items": [projection(row) for row in page[:limit]],
        "next_cursor": str(page[limit - 1]["id"]) if len(page) > limit else None,
    }


async def get_schedule(context, schedule_id):
    row = await get_definition(context, schedule_id)
    result = projection(row)
    if row["deleted_at"] is not None:
        return result | {"upcoming": [], "forecast_status": "deleted"}
    try:
        described = await context.temporal.get_schedule_handle(
            f"schedule/{row['id']}"
        ).describe()
        return result | {
            "upcoming": [
                time.isoformat() for time in described.info.next_action_times[:10]
            ],
            "forecast_status": "available",
            "upcoming_limit": 10,
        }
    except RPCError:
        return result | {"upcoming": None, "forecast_status": "unavailable"}


async def update_schedule(context, command_id, schedule_id, patch: SchedulePatch):
    row = await get_definition(context, schedule_id)
    result = await change_schedule(
        context.temporal,
        ScheduleChange(
            leta_id=context.request.leta_id,
            schedule_id=row["id"],
            requester_agent_id=context.request.agent_id,
            requested_at=datetime.now(UTC),
            action="update",
            patch=patch,
        ),
        command_id=str(command_id),
    )
    return result.model_dump(mode="json")


async def delete_schedule(context, command_id, schedule_id):
    row = await get_definition(context, schedule_id)
    result = await change_schedule(
        context.temporal,
        ScheduleChange(
            leta_id=context.request.leta_id,
            schedule_id=row["id"],
            requester_agent_id=context.request.agent_id,
            requested_at=datetime.now(UTC),
            action="delete",
        ),
        command_id=str(command_id),
    )
    return result.model_dump(mode="json")
