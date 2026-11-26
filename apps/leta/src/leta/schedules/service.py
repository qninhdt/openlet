from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from google.protobuf.timestamp_pb2 import Timestamp
from openlet_sdk.config import JSON
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator
from temporalio.api.workflowservice.v1 import ListScheduleMatchingTimesRequest
from temporalio.client import (
    Client as TemporalClient,
)
from temporalio.client import (
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

from ..activity import ActivityEmitter
from ..db import Pool, get_receipt, hash_request, json_row, save_receipt
from ..inbox import InboxGateway, InboxItem, InboxSender

type CalendarValues = Annotated[
    dict[
        Literal[
            "second", "minute", "hour", "day_of_month", "month", "year", "day_of_week"
        ],
        list[int],
    ],
    Field(
        description="Calendar fields: second/minute 0-59, hour 0-23, day_of_month 1-31, month 1-12, year 1970-9999, day_of_week 0-6 (Sunday=0)."
    ),
]


class Timing(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    at: datetime | None = None
    after_seconds: int | None = Field(default=None, ge=0)
    every_seconds: int | None = Field(default=None, ge=1)
    calendar: CalendarValues | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    timezone: str = "UTC"

    @model_validator(mode="after")
    def validate_timing(self) -> Timing:
        selectors = [self.at, self.after_seconds, self.every_seconds, self.calendar]
        if sum(v is not None for v in selectors) > 1:
            raise ValueError(
                "specify at most one of at, after_seconds, every_seconds, or calendar"
            )
        ZoneInfo(self.timezone)
        for dt in (self.at, self.starts_at, self.ends_at):
            if dt is not None and dt.tzinfo is None:
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
        for key, vals in (self.calendar or {}).items():
            lo, hi = limits[key]
            if not vals or any(v < lo or v > hi for v in vals):
                raise ValueError(f"invalid calendar values for {key}")
        if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
            raise ValueError("ends_at must be after starts_at")
        return self


def normalize_timing(
    timing: Timing, now: datetime
) -> tuple[str, dict[str, JSON]] | None:
    if timing.at is not None or timing.after_seconds is not None:
        at = (
            timing.at
            if timing.at is not None
            else now + timedelta(seconds=timing.after_seconds or 0)
        ).replace(microsecond=0)
        return "at", {"at": at.astimezone(UTC).isoformat()}
    spec: dict[str, JSON] = {"timezone": timing.timezone}
    if timing.starts_at is not None:
        spec["starts_at"] = timing.starts_at.isoformat()
    if timing.ends_at is not None:
        spec["ends_at"] = timing.ends_at.isoformat()
    if timing.every_seconds is not None:
        spec["every_seconds"] = timing.every_seconds
        spec["anchor_at"] = (timing.starts_at or now).isoformat()
        return "interval", spec
    if timing.calendar is not None:
        spec["calendar"] = cast(dict[str, JSON], timing.calendar)
        return "calendar", spec
    return None


def temporal_schedule_id(schedule_id: UUID | str) -> str:
    return f"sched/{schedule_id}"


def build_temporal_schedule(
    *,
    schedule_id: UUID,
    sched_type: str,
    spec: dict[str, JSON],
    paused: bool,
    orchestration_queue: str,
) -> Schedule:
    start_at = (
        datetime.fromisoformat(str(spec["starts_at"]))
        if spec.get("starts_at")
        else None
    )
    end_at = (
        datetime.fromisoformat(str(spec["ends_at"])) if spec.get("ends_at") else None
    )
    tz = str(spec.get("timezone", "UTC"))

    if sched_type == "at":
        at = datetime.fromisoformat(str(spec["at"])).astimezone(UTC)
        t_spec = ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    second=(ScheduleRange(at.second),),
                    minute=(ScheduleRange(at.minute),),
                    hour=(ScheduleRange(at.hour),),
                    day_of_month=(ScheduleRange(at.day),),
                    month=(ScheduleRange(at.month),),
                    year=(ScheduleRange(at.year),),
                )
            ],
            time_zone_name="UTC",
        )
        state = ScheduleState(paused=paused, limited_actions=True, remaining_actions=1)
    elif sched_type == "interval":
        every = timedelta(seconds=int(cast(int, spec["every_seconds"])))
        t_spec = ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=every)],
            start_at=start_at,
            end_at=end_at,
            time_zone_name=tz,
        )
        state = ScheduleState(paused=paused)
    else:
        cal = cast(dict[str, list[int]], spec["calendar"])

        def _ranges(
            field: str, default: tuple[ScheduleRange, ...]
        ) -> tuple[ScheduleRange, ...]:
            vals = cal.get(field)
            if not vals:
                return default
            return tuple(ScheduleRange(v) for v in sorted(set(vals)))

        t_spec = ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    second=_ranges("second", (ScheduleRange(0),)),
                    minute=_ranges("minute", (ScheduleRange(0),)),
                    hour=_ranges("hour", (ScheduleRange(0),)),
                    day_of_month=_ranges("day_of_month", (ScheduleRange(1, 31),)),
                    month=_ranges("month", (ScheduleRange(1, 12),)),
                    year=_ranges("year", ()),
                    day_of_week=_ranges("day_of_week", (ScheduleRange(0, 6),)),
                )
            ],
            start_at=start_at,
            end_at=end_at,
            time_zone_name=tz,
        )
        state = ScheduleState(paused=paused)

    return Schedule(
        action=ScheduleActionStartWorkflow(
            "ScheduleFireWorkflow",
            str(schedule_id),
            id=f"sched-fire/{schedule_id}",
            task_queue=orchestration_queue,
        ),
        spec=t_spec,
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL),
        state=state,
    )


async def upcoming_times(
    temporal: TemporalClient | None, schedule_id: UUID, count: int = 5
) -> list[str]:
    if temporal is None:
        return []
    try:
        desc = await temporal.get_schedule_handle(
            temporal_schedule_id(schedule_id)
        ).describe()
        return [
            dt.astimezone(UTC).isoformat() for dt in desc.info.next_action_times[:count]
        ]
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            return []
        raise


async def calendar_occurrences(
    temporal: TemporalClient,
    schedule_id: UUID,
    *,
    start: datetime,
    end: datetime,
    max_occurrences: int = 1000,
) -> list[str]:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must include a timezone")
    if end <= start:
        raise ValueError("end must be after start")
    if end - start > timedelta(days=366):
        raise ValueError("calendar window cannot exceed 366 days")
    start_ts = Timestamp()
    start_ts.FromDatetime(start.astimezone(UTC))
    end_ts = Timestamp()
    end_ts.FromDatetime(end.astimezone(UTC))
    try:
        resp = await temporal.workflow_service.list_schedule_matching_times(
            ListScheduleMatchingTimesRequest(
                namespace=temporal.namespace,
                schedule_id=temporal_schedule_id(schedule_id),
                start_time=start_ts,
                end_time=end_ts,
            )
        )
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            return []
        raise
    return [
        t.ToDatetime(tzinfo=UTC).isoformat() for t in resp.start_time[:max_occurrences]
    ]


async def create_schedule(
    *,
    db: Pool,
    temporal: TemporalClient | None,
    orchestration_queue: str,
    activity: ActivityEmitter | None,
    leta_id: UUID,
    creator_agent_id: UUID,
    target_agent_id: UUID,
    title: str,
    content: str,
    timing: Timing,
    paused: bool = False,
    request_id: UUID | None = None,
) -> dict[str, JSON]:
    now = datetime.now(UTC)
    normalized = normalize_timing(timing, now)
    if normalized is None:
        raise ValueError(
            "one timing selector (at, after_seconds, every_seconds, calendar) is required"
        )
    sched_type, spec = normalized

    req_hash = hash_request(
        {
            "leta_id": str(leta_id),
            "target_agent_id": str(target_agent_id),
            "title": title,
            "content": content,
            "type": sched_type,
            "spec": spec,
            "paused": paused,
        }
    )
    if request_id is not None:
        cached = await get_receipt(
            db, f"leta:{leta_id}", "schedule.create", request_id, req_hash
        )
        if cached is not None:
            return cached

    async with db.connection() as conn, conn.transaction():
        target = await (
            await conn.execute(
                "SELECT id FROM agents WHERE id = %s AND leta_id = %s AND state = 'active'",
                (target_agent_id, leta_id),
            )
        ).fetchone()
        if target is None:
            raise LookupError("target agent is not active in this Leta")

        schedule_id = uuid4()
        row = await (
            await conn.execute(
                """
                INSERT INTO schedules(
                    id, leta_id, creator_agent_id, target_agent_id,
                    title, content, type, spec, paused
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    schedule_id,
                    leta_id,
                    creator_agent_id,
                    target_agent_id,
                    title.strip(),
                    content.strip(),
                    sched_type,
                    Jsonb(spec),
                    paused,
                ),
            )
        ).fetchone()
    assert row is not None

    if temporal is not None:
        t_sched = build_temporal_schedule(
            schedule_id=schedule_id,
            sched_type=sched_type,
            spec=spec,
            paused=paused,
            orchestration_queue=orchestration_queue,
        )
        sid = temporal_schedule_id(schedule_id)
        try:
            await temporal.create_schedule(sid, t_sched)
        except ScheduleAlreadyRunningError:
            await temporal.get_schedule_handle(sid).update(
                lambda _: ScheduleUpdate(schedule=t_sched)
            )
        # Immediate backfill if a one-shot 'at' schedule is at or in the past.
        if sched_type == "at" and not paused:
            at = datetime.fromisoformat(str(spec["at"])).astimezone(UTC)
            if at <= datetime.now(UTC):
                await temporal.get_schedule_handle(sid).backfill(
                    ScheduleBackfill(
                        start_at=at - timedelta(seconds=1),
                        end_at=at + timedelta(seconds=1),
                        overlap=ScheduleOverlapPolicy.ALLOW_ALL,
                    )
                )

    result = json_row(row)
    result["upcoming"] = cast(JSON, await upcoming_times(temporal, schedule_id))
    if request_id is not None:
        await save_receipt(
            db, f"leta:{leta_id}", "schedule.create", request_id, req_hash, result
        )
    if activity is not None:
        await activity.emit(
            leta_id=leta_id,
            agent_id=creator_agent_id,
            event_type="schedule.updated",
            data={"action": "created", "schedule": result},
        )
    return result


async def update_schedule(
    *,
    db: Pool,
    temporal: TemporalClient | None,
    orchestration_queue: str,
    activity: ActivityEmitter | None,
    leta_id: UUID,
    schedule_id: UUID,
    title: str | None = None,
    content: str | None = None,
    target_agent_id: UUID | None = None,
    timing: Timing | None = None,
    paused: bool | None = None,
) -> dict[str, JSON]:
    now = datetime.now(UTC)
    async with db.connection() as conn, conn.transaction():
        current = await (
            await conn.execute(
                "SELECT * FROM schedules WHERE id = %s AND leta_id = %s AND deleted_at IS NULL FOR UPDATE",
                (schedule_id, leta_id),
            )
        ).fetchone()
        if current is None:
            raise LookupError("schedule not found")

        new_target = target_agent_id or UUID(str(current["target_agent_id"]))
        if target_agent_id is not None:
            ok = await (
                await conn.execute(
                    "SELECT 1 FROM agents WHERE id = %s AND leta_id = %s AND state = 'active'",
                    (target_agent_id, leta_id),
                )
            ).fetchone()
            if ok is None:
                raise LookupError("target agent is not active in this Leta")

        sched_type = str(current["type"])
        spec = cast(dict[str, JSON], current["spec"])
        if timing is not None:
            normalized = normalize_timing(timing, now)
            if normalized is not None:
                sched_type, spec = normalized

        new_title = title.strip() if title is not None else str(current["title"])
        new_content = (
            content.strip() if content is not None else str(current["content"])
        )
        new_paused = paused if paused is not None else bool(current["paused"])

        row = await (
            await conn.execute(
                """
                UPDATE schedules
                SET target_agent_id = %s, title = %s, content = %s,
                    type = %s, spec = %s, paused = %s
                WHERE id = %s
                RETURNING *
                """,
                (
                    new_target,
                    new_title,
                    new_content,
                    sched_type,
                    Jsonb(spec),
                    new_paused,
                    schedule_id,
                ),
            )
        ).fetchone()
    assert row is not None

    if temporal is not None:
        t_sched = build_temporal_schedule(
            schedule_id=schedule_id,
            sched_type=sched_type,
            spec=spec,
            paused=new_paused,
            orchestration_queue=orchestration_queue,
        )
        sid = temporal_schedule_id(schedule_id)
        try:
            await temporal.get_schedule_handle(sid).update(
                lambda _: ScheduleUpdate(schedule=t_sched)
            )
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                await temporal.create_schedule(sid, t_sched)
            else:
                raise

    result = json_row(row)
    result["upcoming"] = cast(JSON, await upcoming_times(temporal, schedule_id))
    if activity is not None:
        await activity.emit(
            leta_id=leta_id,
            agent_id=UUID(str(row["creator_agent_id"])),
            event_type="schedule.updated",
            data={"action": "updated", "schedule": result},
        )
    return result


async def delete_schedule(
    *,
    db: Pool,
    temporal: TemporalClient | None,
    activity: ActivityEmitter | None,
    leta_id: UUID,
    schedule_id: UUID,
) -> None:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                """
                UPDATE schedules SET deleted_at = now()
                WHERE id = %s AND leta_id = %s AND deleted_at IS NULL
                RETURNING creator_agent_id
                """,
                (schedule_id, leta_id),
            )
        ).fetchone()
    if row is None:
        raise LookupError("schedule not found")

    if temporal is not None:
        try:
            await temporal.get_schedule_handle(
                temporal_schedule_id(schedule_id)
            ).delete()
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise

    if activity is not None:
        await activity.emit(
            leta_id=leta_id,
            agent_id=UUID(str(row["creator_agent_id"])),
            event_type="schedule.updated",
            data={"action": "deleted", "schedule_id": str(schedule_id)},
        )


async def list_schedules(
    db: Pool, leta_id: UUID, *, target_agent_id: UUID | None = None
) -> list[dict[str, JSON]]:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT * FROM schedules
                WHERE leta_id = %s AND deleted_at IS NULL
                  AND (%s::uuid IS NULL OR target_agent_id = %s)
                ORDER BY created_at DESC
                """,
                (leta_id, target_agent_id, target_agent_id),
            )
        ).fetchall()
    return [json_row(r) for r in rows]


async def get_schedule(
    db: Pool, temporal: TemporalClient | None, leta_id: UUID, schedule_id: UUID
) -> dict[str, JSON]:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT * FROM schedules WHERE id = %s AND leta_id = %s AND deleted_at IS NULL",
                (schedule_id, leta_id),
            )
        ).fetchone()
    if row is None:
        raise LookupError("schedule not found")
    out = json_row(row)
    out["upcoming"] = cast(JSON, await upcoming_times(temporal, schedule_id))
    return out


async def fire_schedule(
    *, db: Pool, inbox: InboxGateway, schedule_id: UUID, nominal_time: datetime
) -> None:
    async with db.connection() as conn:
        row = await (
            await conn.execute("SELECT * FROM schedules WHERE id = %s", (schedule_id,))
        ).fetchone()
    if row is None or row["deleted_at"] is not None or row["paused"]:
        return
    target_id = UUID(str(row["target_agent_id"]))
    await inbox.deliver(
        InboxItem(
            agent_id=target_id,
            idempotency_key=f"sched:{schedule_id}:{nominal_time.astimezone(UTC).isoformat()}",
            kind="schedule",
            channel="schedule",
            reply_address=None,
            sender=InboxSender(type="system", id=str(schedule_id), name="schedule"),
            content=str(row["content"]),
            metadata={
                "schedule_id": str(schedule_id),
                "title": str(row["title"]),
                "scheduled_for": nominal_time.astimezone(UTC).isoformat(),
            },
        )
    )


_ = ScheduleUpdateInput
