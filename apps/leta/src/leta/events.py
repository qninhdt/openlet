import json
import logging
import re
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID

from ag_ui.core import Event as AgUiEvent
from openlet_sdk.config import JSON
from opentelemetry import metrics
from pydantic import TypeAdapter
from redis.asyncio import Redis
from redis.exceptions import RedisError

from .agents import json_row
from .db import Pool
from .history import search

type Event = dict[str, JSON]
type Records = list[tuple[bytes, dict[bytes, bytes]]]
logger = logging.getLogger(__name__)
ag_ui = TypeAdapter(AgUiEvent)
resyncs = metrics.get_meter("openlet.leta").create_counter("openlet.leta.stream.resync")


def key(root: UUID) -> str:
    return f"leta:events:{root}"


def cursor(value: str) -> tuple[int, int]:
    if not re.fullmatch(r"\d+-\d+", value):
        raise ValueError("invalid event cursor")
    a, b = value.split("-")
    return int(a), int(b)


def event(type: str, agent: UUID, run: UUID | None = None, **fields: JSON) -> Event:
    scope: dict[str, JSON] = {"agentId": str(agent)}
    if run:
        scope["runId"] = str(run)
    return cast(
        Event,
        ag_ui.validate_python(
            {"type": type, "metadata": {"openlet": scope}, **fields}
        ).model_dump(mode="json", by_alias=True, exclude_none=True),
    )


async def publish(redis: Redis, root: UUID, value: Event) -> bool:
    try:
        async with redis.pipeline(transaction=False) as pipe:
            pipe.xadd(
                key(root),
                {"event": json.dumps(value, ensure_ascii=False)},
                maxlen=10000,
                approximate=True,
            )
            pipe.expire(key(root), 86400)
            await pipe.execute()
        return True
    except RedisError:
        logger.warning(
            "public event publication unavailable", extra={"leta_id": str(root)}
        )
        return False


def fold(records: list[tuple[str, Event]]) -> list[tuple[str, Event]]:
    folded: list[tuple[str, Event]] = []
    for id, value in records:
        if folded and value.get("type") in ("TEXT_MESSAGE_CONTENT", "TOOL_CALL_ARGS"):
            last = folded[-1][1]
            if {k: v for k, v in last.items() if k != "delta"} == {
                k: v for k, v in value.items() if k != "delta"
            }:
                delta = str(last.get("delta", "")) + str(value.get("delta", ""))
                if len(delta.encode()) <= 16384:
                    folded[-1] = (id, {**value, "delta": delta})
                    continue
        folded.append((id, value))
    return folded


async def tail(redis: Redis, root: UUID) -> str:
    records = cast(Records, await redis.xrevrange(key(root), count=1))
    return records[0][0].decode() if records else "0-0"


async def snapshot(db: Pool, root: UUID) -> Event:
    async with db.connection() as conn:
        leta = await (
            await conn.execute("SELECT * FROM letas WHERE id=%s", (root,))
        ).fetchone()
        runs = await (
            await conn.execute(
                "SELECT r.* FROM runs r JOIN agents a ON a.id=r.agent_id WHERE a.leta_id=%s AND r.status IN ('running','paused') ORDER BY started_at DESC LIMIT 20",
                (root,),
            )
        ).fetchall()
    if leta is None:
        raise LookupError("Leta not found")
    return event(
        "CUSTOM",
        root,
        name="openlet.snapshot",
        value={
            "leta": json_row(leta),
            "runs": [json_row(row) for row in runs],
            "history": await search(db, root),
        },
    )


async def suffix(
    redis: Redis, root: UUID, after: str
) -> AsyncIterator[tuple[str, Event]]:
    cursor(after)
    stream = key(root)
    position = after
    while True:
        first = cast(Records, await redis.xrange(stream, count=1))
        if position != "0-0" and (
            not first or cursor(first[0][0].decode()) > cursor(position)
        ):
            resyncs.add(1, {"reason": "cursor_gap"})
            yield (
                position,
                event(
                    "CUSTOM",
                    root,
                    name="openlet.resync_required",
                    value={"reason": "cursor_gap"},
                ),
            )
            return
        batches = cast(
            list[tuple[bytes, Records]],
            await redis.xread({stream: position}, count=100, block=5000),
        )
        # Check again: trimming may occur while XREAD is blocked.
        current = cast(Records, await redis.xrange(stream, count=1))
        if position != "0-0" and (
            not current or cursor(current[0][0].decode()) > cursor(position)
        ):
            resyncs.add(1, {"reason": "cursor_gap"})
            yield (
                position,
                event(
                    "CUSTOM",
                    root,
                    name="openlet.resync_required",
                    value={"reason": "cursor_gap"},
                ),
            )
            return
        records: list[tuple[str, Event]] = []
        for _, batch in batches:
            for id, fields in batch:
                records.append((id.decode(), cast(Event, json.loads(fields[b"event"]))))
        if not records:
            yield position, {}
        for id, value in fold(records):
            position = id
            yield id, value
