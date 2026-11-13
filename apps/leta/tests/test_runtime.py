import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from leta.events import event, fold
from leta.runtime.agent import protected
from leta.schedules import Timing, native_spec, normalize


async def test_cancellation_waits_for_boundary_to_settle() -> None:
    entered, finish = asyncio.Event(), asyncio.Event()
    durable = False

    async def boundary() -> None:
        nonlocal durable
        entered.set()
        await finish.wait()
        durable = True

    task = asyncio.create_task(protected(boundary()))
    await entered.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert durable


def test_stream_folding_preserves_agent_scope_and_terminal_events() -> None:
    agent, other, run = uuid4(), uuid4(), uuid4()
    first = event("TEXT_MESSAGE_CONTENT", agent, run, messageId="text", delta="first")
    second = event(
        "TEXT_MESSAGE_CONTENT", agent, run, messageId="text", delta=" second"
    )
    child = event("TEXT_MESSAGE_CONTENT", other, run, messageId="text", delta="child")
    end = event("TEXT_MESSAGE_END", agent, run, messageId="text")
    result = fold([("1-0", first), ("2-0", second), ("3-0", child), ("4-0", end)])
    assert [cursor for cursor, _ in result] == ["2-0", "3-0", "4-0"]
    assert result[0][1]["delta"] == "first second"
    assert result[1][1]["metadata"] != result[0][1]["metadata"]
    assert result[2][1]["type"] == "TEXT_MESSAGE_END"


def test_relative_schedule_uses_workflow_time_and_native_spec() -> None:
    now = datetime(2026, 1, 2, 3, 4, 5, 123, tzinfo=timezone.utc)
    result = normalize(Timing(after_seconds=10), now)
    assert result is not None
    kind, fields = result
    expected = (now + timedelta(seconds=10)).replace(microsecond=0)
    assert fields["at"] == expected.isoformat()
    spec = native_spec(kind, fields)
    assert spec.calendars[0].second[0].start == expected.second
    assert spec.calendars[0].year[0].start == expected.year
    with pytest.raises(ValueError, match="one timing"):
        Timing(at=now, after_seconds=10)
