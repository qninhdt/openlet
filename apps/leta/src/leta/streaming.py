"""Temporary, bounded AG-UI replay; PostgreSQL remains the product record."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from uuid import UUID

from ag_ui.core import Event
from openlet.errors import AppError
from pydantic import JsonValue, TypeAdapter
from redis.asyncio import Redis
from redis.exceptions import RedisError

from leta.domain import Input
from leta.store import Store

log = logging.getLogger(__name__)
EVENT = TypeAdapter(Event)
TTL_SECONDS = 24 * 60 * 60
MAX_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 20_000
FRAME_BYTES = 16 * 1024
PUBLIC_TYPES = {
    "RUN_STARTED",
    "RUN_FINISHED",
    "RUN_ERROR",
    "TEXT_MESSAGE_START",
    "TEXT_MESSAGE_CONTENT",
    "TEXT_MESSAGE_END",
    "TOOL_CALL_START",
    "TOOL_CALL_ARGS",
    "TOOL_CALL_END",
    "CUSTOM",
}
DELTA_TYPES = {"TEXT_MESSAGE_CONTENT", "TOOL_CALL_ARGS"}

# Missing accounting means eviction: discard the disposable log rather than
# reconstructing its size or trusting an incomplete byte counter.
APPEND = """
local exists = redis.call('EXISTS', KEYS[1])
local total = tonumber(redis.call('GET', KEYS[2]))
if exists == 0 or not total then
    redis.call('DEL', KEYS[1], KEYS[2])
    total = 0
end
local size = string.len(ARGV[1])
if size > tonumber(ARGV[2]) then
    return redis.error_reply('event exceeds root log budget')
end
local id = redis.call('XADD', KEYS[1], '*', 'data', ARGV[1])
total = total + size
local count = redis.call('XLEN', KEYS[1])
while total > tonumber(ARGV[2]) or count > tonumber(ARGV[3]) do
    local first = redis.call('XRANGE', KEYS[1], '-', '+', 'COUNT', 1)[1]
    total = total - string.len(first[2][2])
    redis.call('XDEL', KEYS[1], first[1])
    count = count - 1
end
redis.call('SET', KEYS[2], total, 'EX', ARGV[4])
redis.call('EXPIRE', KEYS[1], ARGV[4])
return id
"""


class Envelope(Input):
    leta_id: UUID
    agent_id: UUID
    run_id: UUID | None
    event: dict[str, JsonValue]


def keys(leta_id):
    stream = f"leta:stream:{leta_id}"
    return stream, stream + ":bytes"


def cursor(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{1,20}-[0-9]{1,20}", value
    ):
        raise ValueError("invalid stream cursor")
    result = tuple(int(part) for part in value.split("-"))
    if any(part > (1 << 64) - 1 for part in result):
        raise ValueError("invalid stream cursor")
    return result


def text(value):
    return value.decode() if isinstance(value, bytes) else value


def public_event(event):
    parsed = EVENT.validate_python(event)
    result = parsed.model_dump(
        mode="json", by_alias=True, exclude_none=True, exclude={"raw_event"}
    )
    if result["type"] not in PUBLIC_TYPES:
        raise ValueError("event is not a public agent activity event")
    return result


@dataclass
class AgentPublisher:
    redis: Redis
    leta_id: UUID
    agent_id: UUID
    run_id: UUID | None
    failed: bool = False

    async def emit(self, event):
        envelope = Envelope(
            leta_id=self.leta_id,
            agent_id=self.agent_id,
            run_id=self.run_id,
            event=public_event(event),
        )
        payload = envelope.model_dump_json()
        if self.failed:
            return False
        try:
            async with asyncio.timeout(1):
                # A lost reply can follow a committed XADD; retrying duplicates deltas.
                await self.redis.eval(
                    APPEND,
                    2,
                    *keys(self.leta_id),
                    payload,
                    MAX_BYTES,
                    MAX_EVENTS,
                    TTL_SECONDS,
                )
            return True
        except RedisError, TimeoutError:
            pass
        # One failed publication disables only this invocation's provisional
        # output; repeated token failures must not delay model/checkpoint work.
        self.failed = True
        log.warning(
            "agent event publication unavailable", extra={"leta_id": str(self.leta_id)}
        )
        return False


class Publisher:
    def __init__(self, redis: Redis, store: Store):
        self.redis, self.store = redis, store

    async def agent(self, leta_id, agent_id, run_id=None):
        await self.store.get_agent(leta_id, agent_id)
        if run_id is not None:
            await self.store.get_run(leta_id, agent_id, run_id)
        return AgentPublisher(self.redis, leta_id, agent_id, run_id)

    async def resource(self, leta_id, kind, resource_id):
        """Sparse committed changes; resolve authority from SQL, not event callers."""
        if kind == "message":
            row = await self.store.get_message(leta_id, resource_id)
            agent_id = row["recipient_agent_id"] or row["sender_agent_id"]
            status, path = None, "messages"
        elif kind == "agent":
            row = await self.store.get_agent(leta_id, resource_id)
            agent_id, status, path = row["id"], row["status"], "agents"
        elif kind == "box":
            row = await self.store.get_box(leta_id, resource_id)
            agent_id, status, path = leta_id, row["status"], "boxes"
        elif kind == "human_request":
            row = await self.store.get_request(leta_id, resource_id)
            agent_id, status, path = (
                row["requester_agent_id"],
                row["status"],
                "human-requests",
            )
        elif kind == "schedule":
            row = await self.store.get_schedule(leta_id, resource_id)
            agent_id, status, path = row["target_agent_id"], None, "schedules"
        else:
            raise ValueError("unknown public resource kind")
        bound = await self.agent(leta_id, agent_id)
        return await bound.emit(
            {
                "type": "CUSTOM",
                "name": "resource",
                "value": {
                    "kind": kind,
                    "id": str(resource_id),
                    "status": status,
                    "refresh": f"/v1/letas/{leta_id}/{path}",
                },
            }
        )


class ReplayLost(Exception):
    """The client must reload committed state; provisional prefixes are unavailable."""


async def position(redis, leta_id, after=None):
    if after is not None:
        requested = cursor(after)
    first = await redis.xrange(keys(leta_id)[0], count=1)
    if not first:
        if after is not None:
            raise ReplayLost("root replay is unavailable")
        return "0-0", "0-0"
    last = await redis.xrevrange(keys(leta_id)[0], count=1)
    if not last:
        raise ReplayLost("root replay was lost while connecting")
    oldest, newest = text(first[0][0]), text(last[0][0])
    if after is not None and not cursor(oldest) <= requested <= cursor(newest):
        raise ReplayLost("cursor is outside retained replay")
    return oldest, newest


async def read_events(redis, leta_id, after, *, block=1000, count=128):
    cursor(after)
    try:
        rows = await redis.xread({keys(leta_id)[0]: after}, count=count, block=block)
    except RedisError as error:
        raise AppError(
            "agent replay unavailable",
            reason="DEPENDENCY_UNAVAILABLE",
            kind="unavailable",
        ) from error
    if after != "0-0":
        # Recheck after blocking: trimming during XREAD must cause an explicit reset.
        await position(redis, leta_id, after)
    result = []
    for _, events in rows:
        for identity, fields in events:
            envelope = Envelope.model_validate_json(
                fields.get(b"data", fields.get("data"))
            )
            if str(envelope.leta_id) != str(leta_id):
                raise ReplayLost("replay contains a different root")
            result.append((text(identity), envelope.model_dump(mode="json")))
    return result


def coalesce_events(rows, *, max_bytes=FRAME_BYTES):
    """Preserve byte order, all identities/boundaries, and the last consumed ID."""
    output = []
    for identity, envelope in rows:
        event = envelope["event"]
        if output and event["type"] in DELTA_TYPES:
            previous = output[-1][1]
            old_event = previous["event"]
            if (
                old_event["type"] == event["type"]
                and {k: v for k, v in previous.items() if k != "event"}
                == {k: v for k, v in envelope.items() if k != "event"}
                and {k: v for k, v in old_event.items() if k != "delta"}
                == {k: v for k, v in event.items() if k != "delta"}
                and len((old_event["delta"] + event["delta"]).encode()) <= max_bytes
            ):
                output[-1] = (
                    identity,
                    previous
                    | {
                        "event": old_event
                        | {"delta": old_event["delta"] + event["delta"]}
                    },
                )
                continue
        output.append((identity, envelope))
    return output


def sse(identity, envelope):
    cursor(identity)
    payload = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    return f"id: {identity}\ndata: {payload}\n\n".encode()
