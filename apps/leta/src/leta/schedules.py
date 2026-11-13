from datetime import datetime, timedelta, timezone
from typing import Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from openlet_sdk.config import JSON
from psycopg.types.json import Jsonb
from pydantic import Field, field_serializer, model_validator
from temporalio.api.workflowservice.v1 import ListScheduleMatchingTimesRequest
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleBackfill,
    ScheduleCalendarSpec,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
    ScheduleState,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.service import RPCError, RPCStatusCode

from .agents import Input, gate, get_agent, json_row
from .db import Pool, receipt, save_receipt


class Timing(Input):
    at: datetime | None = None
    after_seconds: int | None = Field(default=None, ge=0)
    every_seconds: int | None = Field(default=None, ge=1)
    calendar: dict[str, list[int]] | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    timezone: str = "UTC"

    @model_validator(mode="after")
    def valid(self) -> "Timing":
        if (
            sum(
                value is not None
                for value in (
                    self.at,
                    self.after_seconds,
                    self.every_seconds,
                    self.calendar,
                )
            )
            > 1
        ):
            raise ValueError("choose one timing selector")
        ZoneInfo(self.timezone)
        for value in (self.at, self.starts_at, self.ends_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("timestamps must include a timezone")
        limits = {
            "second": (0, 59),
            "minute": (0, 59),
            "hour": (0, 23),
            "day_of_month": (1, 31),
            "month": (1, 12),
            "year": (1970, 9999),
            "day_of_week": (0, 6),
        }
        for field, values in (self.calendar or {}).items():
            if (
                field not in limits
                or not values
                or any(
                    value < limits[field][0] or value > limits[field][1]
                    for value in values
                )
            ):
                raise ValueError("invalid calendar values")
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValueError("end must follow start")
        return self


class Change(Timing):
    request_id: UUID
    schedule_id: UUID
    creator_agent_id: UUID
    target_agent_id: UUID
    action: Literal["create", "update", "delete"]
    title: str | None = Field(default=None, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=32000)
    paused: bool | None = None
    supplied: set[str] = Field(default_factory=set)

    @field_serializer("supplied")
    def serialize_fields(self, fields: set[str]) -> list[str]:
        return sorted(fields)

    @model_validator(mode="after")
    def remember_fields(self) -> "Change":
        if not self.supplied:
            self.supplied = self.model_fields_set - {"supplied"}
        return self


class CanonicalChange(Input):
    request: Change
    now: datetime


def normalize(timing: Timing, now: datetime) -> tuple[str, dict[str, JSON]] | None:
    if timing.at is not None or timing.after_seconds is not None:
        at = (
            timing.at or (now + timedelta(seconds=timing.after_seconds or 0))
        ).replace(microsecond=0)
        return "at", {"at": at.astimezone(timezone.utc).isoformat()}
    spec: dict[str, JSON] = {"timezone": timing.timezone}
    if timing.starts_at:
        spec["starts_at"] = timing.starts_at.isoformat()
    if timing.ends_at:
        spec["ends_at"] = timing.ends_at.isoformat()
    if timing.every_seconds is not None:
        spec.update(
            every_seconds=timing.every_seconds,
            anchor_at=(timing.starts_at or now).isoformat(),
        )
        return "interval", spec
    if timing.calendar is not None:
        spec["calendar"] = cast(dict[str, JSON], timing.calendar)
        return "calendar", spec
    return None


async def get(db: Pool, id: UUID) -> dict[str, JSON]:
    async with db.connection() as conn:
        row = await (
            await conn.execute("SELECT * FROM schedules WHERE id=%s", (id,))
        ).fetchone()
    if row is None:
        raise LookupError("schedule not found")
    return json_row(row)


async def upcoming(client: Client, value: dict[str, JSON]) -> dict[str, JSON]:
    if value["deleted_at"] is not None:
        return {"upcoming": [], "forecast_status": "deleted"}
    try:
        result = await client.get_schedule_handle(f"schedule/{value['id']}").describe(
            rpc_timeout=timedelta(seconds=10)
        )
    except RPCError:
        return {"upcoming": None, "forecast_status": "unavailable"}
    return {
        "upcoming": [time.isoformat() for time in result.info.next_action_times[:5]],
        "forecast_status": "available",
    }


async def calendar(
    client: Client, value: dict[str, JSON], start: datetime, end: datetime
) -> list[str]:
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or not start < end <= start + timedelta(days=366)
    ):
        raise ValueError(
            "provide a timezone-aware increasing range of at most 366 days"
        )
    if value["deleted_at"] is not None:
        return []
    if value["type"] == "at":
        at = datetime.fromisoformat(str(cast(dict[str, JSON], value["spec"])["at"]))
        return [at.isoformat()] if start < at <= end else []
    times: list[str] = []
    for _ in range(32):
        query = ListScheduleMatchingTimesRequest(
            namespace=client.namespace, schedule_id=f"schedule/{value['id']}"
        )
        query.start_time.FromDatetime(start)
        query.end_time.FromDatetime(end)
        result = await client.workflow_service.list_schedule_matching_times(query)
        if not result.start_time:
            return times
        batch = [time.ToDatetime(tzinfo=timezone.utc) for time in result.start_time]
        times.extend(time.isoformat() for time in batch if start < time <= end)
        if len(times) > 1000:
            raise ValueError("narrow calendar range to at most 1000 occurrences")
        if batch[-1] >= end:
            return times
        start = batch[-1]
    raise ValueError("narrow calendar range to at most 32 native queries")


async def save(db: Pool, canonical: CanonicalChange) -> dict[str, JSON]:
    change = canonical.request
    agent = await get_agent(db, change.creator_agent_id)
    async with db.connection() as conn, conn.transaction():
        await gate(
            conn, cast(UUID, agent["leta_id"]), cast(UUID | None, agent["box_id"])
        )
        saved = await receipt(
            conn,
            f"agent:{change.creator_agent_id}",
            "schedule.change",
            change.request_id,
            change,
        )
        if saved is not None:
            return {"finalized": True, "result": saved}
        target = await (
            await conn.execute(
                "SELECT box_id,leta_id FROM agents WHERE id=%s",
                (change.target_agent_id,),
            )
        ).fetchone()
        if target is None or target["leta_id"] != agent["leta_id"]:
            raise ValueError("target belongs to another Leta")
        if target["box_id"] is not None:
            await gate(conn, cast(UUID, agent["leta_id"]), cast(UUID, target["box_id"]))
        if change.target_agent_id != change.creator_agent_id:
            box = await (
                await conn.execute(
                    "SELECT 1 FROM boxes WHERE id=%s AND representative_agent_id=%s",
                    (target["box_id"], change.target_agent_id),
                )
            ).fetchone()
            if agent["box_id"] is not None or box is None:
                raise ValueError("only root may schedule an instruction for a box")
        old = await (
            await conn.execute(
                "SELECT * FROM schedules WHERE id=%s FOR UPDATE", (change.schedule_id,)
            )
        ).fetchone()
        if old and (
            old["creator_agent_id"] != change.creator_agent_id
            or old["target_agent_id"] != change.target_agent_id
        ):
            raise PermissionError("schedule scope is immutable")
        timing = normalize(change, canonical.now)
        if change.action == "create":
            if timing is None or change.content is None:
                raise ValueError("schedule requires instruction and timing")
            await conn.execute(
                """INSERT INTO schedules(id,creator_agent_id,target_agent_id,title,content,type,spec,paused)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
                (
                    change.schedule_id,
                    change.creator_agent_id,
                    change.target_agent_id,
                    change.title or "",
                    change.content,
                    timing[0],
                    Jsonb(timing[1]),
                    change.paused or False,
                ),
            )
        elif old is None:
            raise LookupError("schedule not found")
        elif change.action == "delete":
            await conn.execute(
                "UPDATE schedules SET deleted_at=coalesce(deleted_at,%s) WHERE id=%s",
                (canonical.now, change.schedule_id),
            )
        else:
            if old["deleted_at"] is not None:
                raise ValueError("schedule is deleted")
            spec = timing[1] if timing else cast(dict[str, JSON], old["spec"]).copy()
            for field in ("ends_at", "starts_at", "timezone"):
                if field in change.supplied:
                    value = getattr(change, field)
                    spec[field] = (
                        value.isoformat() if isinstance(value, datetime) else value
                    )
            await conn.execute(
                """UPDATE schedules SET title=%s,content=%s,type=%s,spec=%s,paused=%s WHERE id=%s""",
                (
                    change.title if change.title is not None else old["title"],
                    change.content if change.content is not None else old["content"],
                    timing[0] if timing else old["type"],
                    Jsonb(spec),
                    change.paused if change.paused is not None else old["paused"],
                    change.schedule_id,
                ),
            )
        row = await (
            await conn.execute(
                "SELECT * FROM schedules WHERE id=%s", (change.schedule_id,)
            )
        ).fetchone()
        assert row is not None
        native = change.action != "update" or bool(
            change.supplied
            & {
                "at",
                "after_seconds",
                "every_seconds",
                "calendar",
                "starts_at",
                "ends_at",
                "timezone",
                "paused",
            }
        )
        result = json_row(row)
        if not native:
            await save_receipt(
                conn,
                f"agent:{change.creator_agent_id}",
                "schedule.change",
                change.request_id,
                change,
                result,
            )
        return {"finalized": not native, "result": result}


def native_spec(kind: str, spec: dict[str, JSON]) -> ScheduleSpec:
    if kind == "at":
        at = datetime.fromisoformat(str(spec["at"])).astimezone(timezone.utc)
        return ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    second=[ScheduleRange(at.second)],
                    minute=[ScheduleRange(at.minute)],
                    hour=[ScheduleRange(at.hour)],
                    day_of_month=[ScheduleRange(at.day)],
                    month=[ScheduleRange(at.month)],
                    year=[ScheduleRange(at.year)],
                )
            ]
        )
    start = (
        datetime.fromisoformat(str(spec["starts_at"]))
        if spec.get("starts_at")
        else None
    )
    end = datetime.fromisoformat(str(spec["ends_at"])) if spec.get("ends_at") else None
    if kind == "interval":
        every = int(str(spec["every_seconds"]))
        anchor = datetime.fromisoformat(str(spec["anchor_at"]))
        return ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=timedelta(seconds=every),
                    offset=timedelta(seconds=anchor.timestamp() % every),
                )
            ],
            start_at=start,
            end_at=end,
        )
    calendar = cast(dict[str, list[int]], spec["calendar"])
    values = ScheduleCalendarSpec()
    for name, integers in calendar.items():
        setattr(values, name, [ScheduleRange(value) for value in integers])
    return ScheduleSpec(
        calendars=[values],
        time_zone_name=str(spec.get("timezone", "UTC")),
        start_at=start,
        end_at=end,
    )


async def apply(
    db: Pool,
    client: Client,
    queue: str,
    bridge_queue: str,
    canonical: CanonicalChange,
    result: dict[str, JSON],
) -> dict[str, JSON]:
    change = canonical.request
    async with db.connection() as conn:
        saved = await receipt(
            conn,
            f"agent:{change.creator_agent_id}",
            "schedule.change",
            change.request_id,
            change,
        )
    if saved is not None:
        return cast(dict[str, JSON], saved)
    handle = client.get_schedule_handle(f"schedule/{change.schedule_id}")
    if change.action == "delete":
        try:
            await handle.delete()
        except RPCError as error:
            if error.status != RPCStatusCode.NOT_FOUND:
                raise
    else:
        schedule = Schedule(
            action=ScheduleActionStartWorkflow(
                "ScheduleDelivery",
                str(change.schedule_id),
                id=f"schedule-delivery/{change.schedule_id}",
                task_queue=queue,
                memo={"bridge_queue": bridge_queue},
            ),
            spec=native_spec(
                str(result["type"]), cast(dict[str, JSON], result["spec"])
            ),
            state=ScheduleState(paused=bool(result["paused"])),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.BUFFER_ONE),
        )
        try:
            await client.create_schedule(f"schedule/{change.schedule_id}", schedule)
        except ScheduleAlreadyRunningError:

            def update(input: ScheduleUpdateInput) -> ScheduleUpdate:
                current = input.description.schedule
                if change.action == "create" or change.supplied & {
                    "at",
                    "after_seconds",
                    "every_seconds",
                    "calendar",
                    "starts_at",
                    "ends_at",
                    "timezone",
                }:
                    current.spec = schedule.spec
                current.state.paused = schedule.state.paused
                return ScheduleUpdate(schedule=current)

            await handle.update(update)
        if result["type"] == "at" and not result["paused"]:
            at = datetime.fromisoformat(
                str(cast(dict[str, JSON], result["spec"])["at"])
            )
            if at <= canonical.now:
                await handle.backfill(
                    ScheduleBackfill(
                        start_at=at - timedelta(seconds=1),
                        end_at=at,
                        overlap=ScheduleOverlapPolicy.ALLOW_ALL,
                    )
                )
    async with db.connection() as conn, conn.transaction():
        await save_receipt(
            conn,
            f"agent:{change.creator_agent_id}",
            "schedule.change",
            change.request_id,
            change,
            result,
        )
    return result
