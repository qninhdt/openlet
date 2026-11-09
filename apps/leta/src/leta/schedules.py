"""One schedule definition, normalized once before native Temporal execution."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, TypeAdapter, model_validator
from temporalio.client import (
    ScheduleCalendarSpec,
    ScheduleIntervalSpec,
    ScheduleRange,
    ScheduleSpec,
)

from leta.domain import Input, fault


class AtSchedule(Input):
    type: Literal["at"]
    at: AwareDatetime | None = None
    after_seconds: int | None = Field(default=None, ge=0, strict=True)

    @model_validator(mode="after")
    def one_time(self):
        if (self.at is None) == (self.after_seconds is None):
            raise ValueError("supply at or after_seconds, exactly one")
        return self


class IntervalSchedule(Input):
    type: Literal["interval"]
    every_seconds: int = Field(gt=0, strict=True)
    anchor_at: AwareDatetime | None = None


class CalendarRange(Input):
    start: int = Field(strict=True)
    end: int | None = Field(default=None, strict=True)
    step: int = Field(default=1, gt=0, strict=True)


CalendarInteger = Annotated[int, Field(strict=True)]
CalendarField = (
    Literal["*"]
    | CalendarInteger
    | CalendarRange
    | list[CalendarInteger | CalendarRange]
)
FIELD_BOUNDS = {
    "second": (0, 59),
    "minute": (0, 59),
    "hour": (0, 23),
    "day_of_month": (1, 31),
    "month": (1, 12),
    "year": (1, 9999),
    "day_of_week": (0, 6),
}


class CalendarSchedule(Input):
    type: Literal["calendar"]
    timezone: str
    fields: dict[str, CalendarField]


def ceil_second(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("schedule time requires an offset")
    value = value.astimezone(UTC)
    return value.replace(microsecond=0) + timedelta(seconds=bool(value.microsecond))


ScheduleInputSpec = Annotated[
    AtSchedule | IntervalSchedule | CalendarSchedule, Field(discriminator="type")
]
SCHEDULE = TypeAdapter(ScheduleInputSpec)


def calendar_fields(fields: dict) -> dict:
    if set(fields) - FIELD_BOUNDS.keys():
        raise ValueError("unknown calendar field")
    defaults = ScheduleCalendarSpec()
    result = {}
    for name, (low, high) in FIELD_BOUNDS.items():
        if name not in fields:
            values = [
                CalendarRange(start=r.start, end=r.end, step=r.step)
                for r in getattr(defaults, name)
            ]
        elif fields[name] == "*":
            values = [] if name == "year" else [CalendarRange(start=low, end=high)]
        else:
            raw = fields[name] if isinstance(fields[name], list) else [fields[name]]
            if not raw and name != "year":
                raise ValueError("calendar field must match at least one value")
            values = [
                CalendarRange(start=value)
                if isinstance(value, int)
                else CalendarRange.model_validate(value)
                for value in raw
            ]
        ranges = set()
        for value in values:
            end = value.start if value.end is None else value.end
            if not low <= value.start <= end <= high:
                raise ValueError(f"invalid {name} range")
            ranges.add((value.start, end, value.step))
        result[name] = [
            {"start": start, "end": end, "step": step}
            for start, end, step in sorted(ranges)
        ]
    return result


def canonicalize_schedule(spec: dict, *, now: datetime) -> dict:
    value = SCHEDULE.validate_python(spec)
    if isinstance(value, AtSchedule):
        try:
            when = (
                value.at
                if value.at is not None
                else now + timedelta(seconds=value.after_seconds)
            )
            return {"type": "at", "at": ceil_second(when).isoformat()}
        except OverflowError as error:
            raise ValueError("schedule time out of range") from error
    if isinstance(value, IntervalSchedule):
        try:
            timedelta(seconds=value.every_seconds)
            anchor = ceil_second(value.anchor_at or now)
        except OverflowError as error:
            raise ValueError("schedule interval out of range") from error
        return {
            "type": "interval",
            "every_seconds": value.every_seconds,
            "anchor_at": anchor.isoformat(),
        }
    try:
        ZoneInfo(value.timezone)
    except (KeyError, ValueError) as error:
        raise ValueError("unknown IANA timezone") from error
    return {
        "type": "calendar",
        "timezone": value.timezone,
        "fields": calendar_fields(value.fields),
    }


def validate_schedule(
    spec: dict, *, end_at: datetime | None = None
) -> AtSchedule | IntervalSchedule | CalendarSchedule:
    if end_at is not None:
        TypeAdapter(AwareDatetime).validate_python(end_at)
    value = SCHEDULE.validate_python(spec)
    if isinstance(value, AtSchedule):
        if value.at is None or end_at is not None:
            raise ValueError("canonical one-shot requires at and no end_at")
        canonicalize_schedule(spec, now=value.at)
    elif isinstance(value, IntervalSchedule):
        if value.anchor_at is None:
            raise ValueError("canonical interval requires an anchor")
        canonicalize_schedule(spec, now=value.anchor_at)
    else:
        try:
            ZoneInfo(value.timezone)
        except (KeyError, ValueError) as error:
            raise ValueError("unknown IANA timezone") from error
        calendar_fields(value.fields)
    return value


def compile_schedule(spec: dict, *, end_at: datetime | None = None) -> ScheduleSpec:
    value = validate_schedule(spec, end_at=end_at)
    if end_at is not None:
        end_at = TypeAdapter(AwareDatetime).validate_python(end_at)
    if isinstance(value, AtSchedule):
        when = ceil_second(value.at)
        return ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    second=[ScheduleRange(when.second)],
                    minute=[ScheduleRange(when.minute)],
                    hour=[ScheduleRange(when.hour)],
                    day_of_month=[ScheduleRange(when.day)],
                    month=[ScheduleRange(when.month)],
                    year=[ScheduleRange(when.year)],
                )
            ],
            time_zone_name="UTC",
        )
    if isinstance(value, IntervalSchedule):
        anchor = ceil_second(value.anchor_at)
        seconds = (anchor - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(seconds=1)
        return ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(
                    every=timedelta(seconds=value.every_seconds),
                    offset=timedelta(seconds=seconds % value.every_seconds),
                )
            ],
            start_at=anchor,
            end_at=end_at,
        )
    return ScheduleSpec(
        calendars=[
            ScheduleCalendarSpec(
                **{
                    name: [ScheduleRange(**item) for item in ranges]
                    for name, ranges in calendar_fields(value.fields).items()
                }
            )
        ],
        time_zone_name=value.timezone,
        end_at=end_at,
    )


async def calendar_occurrences(client, definitions, *, start: datetime, end: datetime):
    """Complete forecast for (start, end]; never return a truncated calendar."""
    import asyncio

    from google.protobuf.timestamp_pb2 import Timestamp
    from openlet.errors import AppError
    from temporalio.api.workflowservice.v1 import ListScheduleMatchingTimesRequest
    from temporalio.service import RPCError

    start = TypeAdapter(AwareDatetime).validate_python(start).astimezone(UTC)
    end = TypeAdapter(AwareDatetime).validate_python(end).astimezone(UTC)
    if end <= start or end - start > timedelta(days=366):
        raise fault(
            "VALIDATION",
            "calendar range must be positive and at most 366 days",
            "invalid",
        )
    if len(definitions) > 32:
        raise fault(
            "REQUEST_TOO_LARGE",
            "narrow calendar range or schedule/target filter",
            "limit",
        )
    semaphore = asyncio.Semaphore(4)
    results, rpc_count = [], 0

    def add(row, when):
        if len(results) >= 1000:
            raise fault(
                "REQUEST_TOO_LARGE",
                "narrow calendar range or schedule/target filter",
                "limit",
            )
        results.append(
            {
                "schedule_id": str(row["id"]),
                "title": row["title"],
                "target_agent_id": str(row["target_agent_id"]),
                "box_id": str(row["box_id"]) if row["box_id"] else None,
                "scheduled_at": when.isoformat(),
                "timezone": row["spec"].get("timezone", "UTC"),
                "paused": row["paused"],
            }
        )

    async def forecast(row):
        nonlocal rpc_count
        if row["spec"]["type"] == "at":
            when = datetime.fromisoformat(row["spec"]["at"])
            if start < when <= end:
                add(row, when)
            return
        cursor = start
        while True:
            async with semaphore:
                if rpc_count >= 32:
                    raise fault(
                        "REQUEST_TOO_LARGE",
                        "narrow calendar range or schedule/target filter",
                        "limit",
                    )
                rpc_count += 1
                first, last = Timestamp(), Timestamp()
                first.FromDatetime(cursor)
                last.FromDatetime(end)
                try:
                    response = (
                        await client.workflow_service.list_schedule_matching_times(
                            ListScheduleMatchingTimesRequest(
                                namespace=client.namespace,
                                schedule_id=f"schedule/{row['id']}",
                                start_time=first,
                                end_time=last,
                            ),
                            timeout=timedelta(seconds=10),
                        )
                    )
                except RPCError as error:
                    raise AppError(
                        "calendar forecast unavailable",
                        reason="FORECAST_UNAVAILABLE",
                        kind="unavailable",
                        retryable=True,
                    ) from error
            times = [item.ToDatetime(tzinfo=UTC) for item in response.start_time]
            if times != sorted(set(times)) or any(not cursor < t <= end for t in times):
                raise fault(
                    "FORECAST_INVALID", "native matching times violate range ordering"
                )
            for when in times:
                add(row, when)
            if len(times) < 1000:
                return
            # Native start is exclusive; retain the exact last instant, not +1s.
            cursor = times[-1]

    tasks = [asyncio.create_task(forecast(row)) for row in definitions]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return sorted(
        results,
        key=lambda row: (
            row["scheduled_at"],
            row["schedule_id"],
            row["target_agent_id"],
        ),
    )
