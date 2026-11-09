from datetime import UTC, datetime, timedelta

import pytest
from temporalio.client import ScheduleCalendarSpec, ScheduleRange

from leta.schedules import canonicalize_schedule, compile_schedule

NOW = datetime(2026, 11, 8, 9, 0, 0, 500000, tzinfo=UTC)


@pytest.mark.parametrize("seconds", [0, 5, 3600, 432000])
def test_relative_at_rounds_up_and_canonical_retry_keeps_original_time(seconds):
    canonical = canonicalize_schedule({"type": "at", "after_seconds": seconds}, now=NOW)
    when = datetime.fromisoformat(canonical["at"])
    assert when == NOW.replace(microsecond=0) + timedelta(seconds=seconds + 1)
    assert canonicalize_schedule(canonical, now=NOW + timedelta(days=9)) == canonical
    compiled = compile_schedule(canonical)
    assert compiled.time_zone_name == "UTC" and not compiled.intervals
    assert compiled.calendars[0].year == [ScheduleRange(2026)]
    assert compiled.calendars[0].second == [ScheduleRange((seconds + 1) % 60)]


def test_specific_timestamp_keeps_instant_across_offset_and_subseconds():
    canonical = canonicalize_schedule(
        {"type": "at", "at": "2026-11-09T09:01:02.001+07:00"}, now=NOW
    )
    assert canonical == {"type": "at", "at": "2026-11-09T02:01:03+00:00"}
    with pytest.raises(ValueError, match="no end_at"):
        compile_schedule(canonical, end_at=NOW)


@pytest.mark.parametrize("seconds", [5, 3600, 432000])
def test_intervals_preserve_explicit_anchor_across_month_and_year_boundaries(seconds):
    anchor = datetime(2026, 12, 31, 9, 3, 2, tzinfo=UTC)
    canonical = canonicalize_schedule(
        {
            "type": "interval",
            "every_seconds": seconds,
            "anchor_at": anchor,
        },
        now=NOW,
    )
    compiled = compile_schedule(canonical)
    interval = compiled.intervals[0]
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    offset = interval.offset or timedelta()
    assert interval.every == timedelta(seconds=seconds)
    assert (anchor - epoch - offset) % interval.every == timedelta()
    assert compiled.start_at == anchor
    assert canonicalize_schedule(canonical, now=NOW + timedelta(days=20)) == canonical


def test_default_interval_anchor_is_persistable_and_end_time_passes_through():
    canonical = canonicalize_schedule({"type": "interval", "every_seconds": 5}, now=NOW)
    assert canonical["anchor_at"] == "2026-11-08T09:00:01+00:00"
    end = NOW + timedelta(days=1)
    assert compile_schedule(canonical, end_at=end).end_at == end


def test_calendar_expands_actual_sdk_defaults_and_supports_monthly_and_ranges():
    canonical = canonicalize_schedule(
        {
            "type": "calendar",
            "timezone": "Asia/Ho_Chi_Minh",
            "fields": {
                "hour": [9],
                "day_of_month": [1, 31],
                "second": "*",
                "minute": [{"start": 0, "end": 55, "step": 5}],
            },
        },
        now=NOW,
    )
    assert canonical["fields"]["month"] == [{"start": 1, "end": 12, "step": 1}]
    assert canonical["fields"]["year"] == []
    compiled = compile_schedule(canonical)
    calendar = compiled.calendars[0]
    assert compiled.time_zone_name == "Asia/Ho_Chi_Minh"
    assert calendar.minute == [ScheduleRange(0, 55, 5)]
    assert calendar.second == [ScheduleRange(0, 59)]
    assert calendar.day_of_month == [ScheduleRange(1), ScheduleRange(31)]
    assert tuple(calendar.day_of_week) == ScheduleCalendarSpec().day_of_week
    assert canonicalize_schedule(canonical, now=NOW) == canonical


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "at"},
        {"type": "at", "at": NOW, "after_seconds": 5},
        {"type": "at", "at": "2026-11-09T09:00:00"},
        {"type": "at", "after_seconds": -1},
        {"type": "at", "after_seconds": True},
        {"type": "interval", "every_seconds": 0},
        {"type": "interval", "every_seconds": 0.5},
        {"type": "calendar", "timezone": "Unknown/Zone", "fields": {}},
        {"type": "calendar", "timezone": "UTC", "fields": {"hours": [9]}},
        {"type": "calendar", "timezone": "UTC", "fields": {"hour": [24]}},
        {"type": "calendar", "timezone": "UTC", "fields": {"hour": [True]}},
        {"type": "calendar", "timezone": "UTC", "fields": {"minute": []}},
        {
            "type": "calendar",
            "timezone": "UTC",
            "fields": {"month": {"start": 5, "end": 2}},
        },
        {
            "type": "calendar",
            "timezone": "UTC",
            "fields": {"month": {"start": 1, "step": 0}},
        },
    ],
)
def test_invalid_schedule_has_an_explicit_validation_error(spec):
    with pytest.raises(ValueError):
        canonicalize_schedule(spec, now=NOW)


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "at", "after_seconds": 10**30},
        {"type": "interval", "every_seconds": 10**30},
        {"type": "at", "at": "9999-12-31T23:59:59.999999Z"},
    ],
)
def test_time_overflow_is_a_validation_error(spec):
    with pytest.raises(ValueError, match="out of range"):
        canonicalize_schedule(spec, now=NOW)


def test_recurring_cutoff_requires_an_offset():
    spec = canonicalize_schedule({"type": "interval", "every_seconds": 5}, now=NOW)
    with pytest.raises(ValueError):
        compile_schedule(spec, end_at=datetime(2026, 11, 9))


async def test_calendar_outage_is_explicit_and_definition_remains_readable():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from uuid import uuid7

    from openlet.errors import AppError
    from temporalio.service import RPCError, RPCStatusCode

    from leta.runtime.schedules import get_schedule
    from leta.schedules import calendar_occurrences

    row = {
        "id": uuid7(),
        "leta_id": uuid7(),
        "creator_agent_id": uuid7(),
        "target_agent_id": uuid7(),
        "box_id": None,
        "title": "Report",
        "content": "Write",
        "spec": canonicalize_schedule(
            {"type": "interval", "every_seconds": 3600}, now=NOW
        ),
        "end_at": None,
        "paused": False,
        "deleted_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    unavailable = RPCError("offline", RPCStatusCode.UNAVAILABLE, b"")
    client = SimpleNamespace(
        namespace="test",
        workflow_service=SimpleNamespace(
            list_schedule_matching_times=AsyncMock(side_effect=unavailable)
        ),
        get_schedule_handle=lambda _: SimpleNamespace(
            describe=AsyncMock(side_effect=unavailable)
        ),
    )
    with pytest.raises(AppError, match="forecast unavailable") as failure:
        await calendar_occurrences(
            client, [row], start=NOW, end=NOW + timedelta(days=1)
        )
    assert failure.value.reason == "FORECAST_UNAVAILABLE"
    context = SimpleNamespace(
        request=SimpleNamespace(leta_id=row["leta_id"]),
        agent={"kind": "leta"},
        store=SimpleNamespace(get_schedule=AsyncMock(return_value=row)),
        temporal=client,
    )
    output = await get_schedule(context, str(row["id"]))
    assert (
        output["title"] == "Report"
        and output["forecast_status"] == "unavailable"
        and output["upcoming"] is None
    )
