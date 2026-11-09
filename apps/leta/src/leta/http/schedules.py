from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime
from temporalio.service import RPCError

from leta.domain import NewSchedule, SchedulePatch
from leta.http.common import API, Limit, cursor_scope, page, read_cursor
from leta.http.models import CreateSchedule, Occurrence, Page, ScheduleView
from leta.runtime.schedules import projection
from leta.schedules import calendar_occurrences, canonicalize_schedule, compile_schedule
from leta.store import fault
from leta.temporal.bridges import change_schedule
from leta.temporal.schedule_types import ScheduleChange

router = APIRouter()


async def targets(context, leta_id, agent_id, box_id):
    agent = await context.store.get_agent(leta_id, agent_id) if agent_id else None
    box = await context.store.get_box(leta_id, box_id) if box_id else None
    if agent and box and agent["box_id"] != box_id:
        raise fault("VALIDATION", "agent does not belong to selected box", "invalid")
    return agent, box


def validate_spec(spec, end_at, now):
    try:
        compile_schedule(canonicalize_schedule(spec, now=now), end_at=end_at)
    except ValueError as error:
        raise fault("VALIDATION", str(error), "invalid") from error


@router.get("/v1/letas/{leta_id}/schedules", response_model=Page[ScheduleView])
async def schedules(
    leta_id: UUID,
    context: API,
    target_agent_id: UUID | None = None,
    box_id: UUID | None = None,
    limit: Limit = 20,
    cursor: str | None = None,
):
    await context.root(leta_id)
    await targets(context, leta_id, target_agent_id, box_id)
    scope = cursor_scope("schedules", leta_id, target_agent_id, box_id)
    found = await context.store.list_schedules(
        leta_id,
        target_agent_id=target_agent_id,
        box_id=box_id,
        after=read_cursor(cursor, scope),
        limit=limit + 1,
    )
    output = page(found, limit, scope, lambda row: str(row["id"]))
    output["items"] = [projection(row) for row in found[:limit]]
    return output


@router.post(
    "/v1/letas/{leta_id}/schedules", status_code=201, response_model=ScheduleView
)
async def create(leta_id: UUID, body: CreateSchedule, context: API):
    await context.root(leta_id, manage=True)
    agent, box = await targets(context, leta_id, body.target_agent_id, body.box_id)
    target = (
        agent["id"] if agent else box["representative_agent_id"] if box else leta_id
    )
    box_id = agent["box_id"] if agent else body.box_id
    if box_id:
        selected = box or await context.store.get_box(leta_id, box_id)
        if target != selected["representative_agent_id"]:
            raise fault("VALIDATION", "schedule the box representative", "invalid")
    key, saved = await context.command(body)
    if saved["expires_at"] is not None:
        return projection(
            await context.store.get_schedule(leta_id, saved["resource_id"])
        )
    spec = body.spec.model_dump(mode="json")
    validate_spec(spec, body.end_at, saved["created_at"])
    creation = NewSchedule(
        id=saved["resource_id"],
        leta_id=leta_id,
        creator_agent_id=leta_id,
        target_agent_id=target,
        box_id=box_id,
        title=body.title,
        content=body.content,
        spec=spec,
        end_at=body.end_at,
    )
    result = await context.execute(
        change_schedule(
            context.temporal,
            ScheduleChange(
                leta_id=leta_id,
                schedule_id=creation.id,
                action="create",
                requester_agent_id=leta_id,
                requested_at=saved["created_at"],
                creation=creation,
            ),
            command_id=str(key),
        ),
        resource_id=creation.id,
        key=key,
    )
    return (
        result if isinstance(result, JSONResponse) else result.model_dump(mode="json")
    )


@router.get("/v1/letas/{leta_id}/schedules/{schedule_id}", response_model=ScheduleView)
async def get(leta_id: UUID, schedule_id: UUID, context: API):
    await context.root(leta_id)
    row = await context.store.get_schedule(leta_id, schedule_id)
    result = projection(row)
    if row["deleted_at"] is not None:
        return result | {"upcoming": [], "forecast_status": "deleted"}
    try:
        described = await context.temporal.get_schedule_handle(
            f"schedule/{schedule_id}"
        ).describe()
        return result | {
            "upcoming": described.info.next_action_times[:10],
            "forecast_status": "available",
            "upcoming_limit": 10,
        }
    except RPCError:
        return result | {"upcoming": None, "forecast_status": "unavailable"}


@router.patch(
    "/v1/letas/{leta_id}/schedules/{schedule_id}", response_model=ScheduleView
)
async def update(leta_id: UUID, schedule_id: UUID, body: SchedulePatch, context: API):
    await context.root(leta_id, manage=True)
    row = await context.store.get_schedule(leta_id, schedule_id)
    key, saved = await context.command(body, resource_id=schedule_id)
    if saved["expires_at"] is not None:
        return projection(row)
    fields = body.model_dump(exclude_unset=True)
    validate_spec(
        fields.get("spec", row["spec"]),
        fields.get("end_at", row["end_at"]),
        saved["created_at"],
    )
    result = await context.execute(
        change_schedule(
            context.temporal,
            ScheduleChange(
                leta_id=leta_id,
                schedule_id=schedule_id,
                action="update",
                requester_agent_id=leta_id,
                requested_at=saved["created_at"],
                patch=body,
            ),
            command_id=str(key),
        ),
        resource_id=schedule_id,
        key=key,
    )
    return (
        result if isinstance(result, JSONResponse) else result.model_dump(mode="json")
    )


@router.delete(
    "/v1/letas/{leta_id}/schedules/{schedule_id}", response_model=ScheduleView
)
async def delete(leta_id: UUID, schedule_id: UUID, context: API):
    await context.root(leta_id, manage=True)
    row = await context.store.get_schedule(leta_id, schedule_id)
    key, saved = await context.command(resource_id=schedule_id)
    if saved["expires_at"] is not None:
        return projection(row)
    result = await context.execute(
        change_schedule(
            context.temporal,
            ScheduleChange(
                leta_id=leta_id,
                schedule_id=schedule_id,
                action="delete",
                requester_agent_id=leta_id,
                requested_at=saved["created_at"],
            ),
            command_id=str(key),
        ),
        resource_id=schedule_id,
        key=key,
    )
    return (
        result if isinstance(result, JSONResponse) else result.model_dump(mode="json")
    )


@router.get("/v1/letas/{leta_id}/schedule-occurrences", response_model=list[Occurrence])
async def occurrences(
    leta_id: UUID,
    context: API,
    start: AwareDatetime,
    end: AwareDatetime,
    target_agent_id: UUID | None = None,
    box_id: UUID | None = None,
    schedule_id: UUID | None = None,
):
    await context.root(leta_id)
    await targets(context, leta_id, target_agent_id, box_id)
    if schedule_id:
        await context.store.get_schedule(leta_id, schedule_id)
    definitions = await context.store.calendar_schedules(
        leta_id, target_agent_id=target_agent_id, box_id=box_id, schedule_id=schedule_id
    )
    return await calendar_occurrences(
        context.temporal, definitions, start=start, end=end
    )
