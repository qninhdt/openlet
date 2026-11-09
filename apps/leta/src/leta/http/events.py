"""One authorized root SSE connection; reconnect is independent of worker attempts."""

import asyncio
import json
import time
from contextlib import aclosing, suppress
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header
from openlet.authz import Resource, check
from openlet.errors import AppError
from redis.exceptions import RedisError
from starlette.responses import StreamingResponse

from leta.history import activity_entry
from leta.http.common import API
from leta.http.models import agent_view
from leta.store import fault
from leta.streaming import (
    DELTA_TYPES,
    FRAME_BYTES,
    Envelope,
    ReplayLost,
    coalesce_events,
    cursor,
    keys,
    position,
    read_events,
    sse,
    text,
)

router = APIRouter()
AUTH_SECONDS = 30
MERGE_SECONDS = 0.025
SEND_SECONDS = 10


class EventResponse(StreamingResponse):
    media_type = "text/event-stream"

    async def __call__(self, scope, receive, send):
        async def bounded_send(message):
            async with asyncio.timeout(SEND_SECONDS):
                await send(message)

        try:
            await super().__call__(scope, receive, bounded_send)
        finally:
            await self.body_iterator.aclose()


def custom(leta_id, name, value, identity=None):
    envelope = Envelope(
        leta_id=leta_id,
        agent_id=leta_id,
        run_id=None,
        event={"type": "CUSTOM", "name": name, "value": value},
    ).model_dump(mode="json")
    if identity is not None:
        return sse(identity, envelope)
    return (
        "data: "
        + json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        + "\n\n"
    ).encode()


def routes(leta_id):
    base = f"/v1/letas/{leta_id}"
    return {
        name: base + "/" + name
        for name in (
            "agents",
            "boxes",
            "messages",
            "inbox",
            "history",
            "human-requests",
            "schedules",
        )
    }


async def snapshot(context, leta_id, *, history):
    root = await context.root(leta_id)
    roster, entries = await asyncio.gather(
        context.store.api_agents(leta_id, limit=101),
        context.store.bootstrap_history(leta_id, limit=101)
        if history
        else asyncio.sleep(0, result=[]),
    )
    public, omitted, used = [], [], 0
    materialized = set()
    for row in reversed(entries[:100]):
        entry = activity_entry(row).model_dump(mode="json")
        event_id = entry["tool_call_id"] or entry["data"].get("llm_message_id")
        if event_id:
            materialized.add((str(row["agent_id"]), str(row["run_id"]), event_id))
        size = len(json.dumps(entry, ensure_ascii=False).encode())
        if used + size > 1 << 20:
            omitted.append(
                {
                    "id": str(row["id"]),
                    "agent_id": str(row["agent_id"]),
                    "url": (
                        f"/v1/letas/{leta_id}/history/{row['id']}"
                        f"?agent_id={row['agent_id']}"
                    ),
                }
            )
        else:
            public.append(entry)
            used += size
    return {
        "root": agent_view(root),
        "agents": [agent_view(row, paused=root["paused"]) for row in roster[:100]],
        "more_agents": len(roster) > 100,
        "entries": public,
        "entry_refs": omitted,
        "more_history": len(entries) > 100,
        "refresh": routes(leta_id),
    }, materialized


class FreshReplay:
    def __init__(self, materialized, snapshot):
        self.materialized = materialized
        self.starts = set()
        self.limited = False
        self.runs = {
            (a["id"], str(a["run_id"]))
            for a in snapshot["agents"]
            if a["run_id"] and a["run_status"] in {"running", "paused"}
        }

    def accepts(self, envelope, *, historical=False):
        event = envelope["event"]
        kind = event["type"]
        pair = (envelope["agent_id"], str(envelope["run_id"]))
        if historical and kind in {"RUN_STARTED", "RUN_FINISHED", "RUN_ERROR"}:
            return pair in self.runs
        if kind.startswith("TEXT_MESSAGE_") or kind.startswith("TOOL_CALL_"):
            identity = event.get("messageId") or event.get("toolCallId")
            key = (*pair, identity)
            if key in self.materialized:
                return False
            if kind in {"TEXT_MESSAGE_START", "TOOL_CALL_START"}:
                self.starts.add(key)
            elif key not in self.starts:
                self.limited = True
                return False
            if kind in {"TEXT_MESSAGE_END", "TOOL_CALL_END"}:
                self.starts.discard(key)
        return True


async def authorized(context, leta_id):
    if not await check(
        context.authz, context.actor, "read", Resource("leta", str(leta_id))
    ):
        raise fault("FORBIDDEN", "Leta access removed", "forbidden")


async def live(context, redis, leta_id, after, fresh=None):
    """At most one XREAD and one merge buffer; keep the read across timer flushes."""
    pending = None
    buffered = []
    flush_at = None
    heartbeat = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            if pending is None:
                pending = asyncio.create_task(read_events(redis, leta_id, after))
            done, _ = await asyncio.wait(
                {pending},
                timeout=max(0, flush_at - now) if flush_at is not None else None,
            )
            if not done:
                for item in buffered:
                    yield sse(*item)
                buffered = []
                flush_at = None
                continue
            rows = pending.result()
            pending = None
            for identity, envelope in rows:
                after = identity
                if fresh is not None and not fresh.accepts(envelope):
                    continue
                candidate = coalesce_events([*buffered, (identity, envelope)])
                if buffered and len(candidate) > 1:
                    for item in buffered:
                        yield sse(*item)
                    buffered = []
                    flush_at = None
                    candidate = [(identity, envelope)]
                buffered = candidate
                if (
                    envelope["event"]["type"] not in DELTA_TYPES
                    or len(envelope["event"].get("delta", "").encode()) >= FRAME_BYTES
                ):
                    for item in buffered:
                        yield sse(*item)
                    buffered = []
                    flush_at = None
                elif flush_at is None:
                    flush_at = time.monotonic() + MERGE_SECONDS
                event = envelope["event"]
                if (
                    event["type"] == "CUSTOM"
                    and event["name"] == "resource"
                    and event["value"].get("kind") == "agent"
                    and event["value"].get("id") == str(leta_id)
                    and event["value"].get("status") == "archived"
                ):
                    return
            if time.monotonic() - heartbeat >= 15:
                yield b": keep-alive\n\n"
                heartbeat = time.monotonic()
    finally:
        if pending is not None:
            pending.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await pending


async def connection(context, redis, leta_id, after, bounds, lost):
    checked = time.monotonic()
    try:
        async with aclosing(
            stream_connection(context, redis, leta_id, after, bounds, lost)
        ) as source:
            async for frame in source:
                if time.monotonic() - checked >= AUTH_SECONDS:
                    await authorized(context, leta_id)
                    checked = time.monotonic()
                yield frame
    except AppError as error:
        if error.kind == "forbidden":
            return
        if error.kind != "unavailable":
            raise
        yield unavailable(leta_id)
    except RedisError, OSError:
        yield unavailable(leta_id)


def unavailable(leta_id):
    return custom(
        leta_id,
        "resync_required",
        {
            "reason": "Replay unavailable; reconnect and reload committed state.",
            "refresh": routes(leta_id),
        },
    )


async def stream_connection(context, redis, leta_id, after, bounds, lost):
    while True:
        if lost:
            yield custom(
                leta_id,
                "resync_required",
                {
                    "reason": "Replay no longer available; reload committed state.",
                    "refresh": routes(leta_id),
                },
            )
            after = None
        state, materialized = await snapshot(context, leta_id, history=after is None)
        yield custom(leta_id, "bootstrap" if after is None else "state_refresh", state)
        fresh = None
        if after is None:
            _, boundary = bounds
            fresh = FreshReplay(materialized, state)
            retained = (
                await redis.xrange(keys(leta_id)[0], max=boundary, count=20_000)
                if boundary != "0-0"
                else []
            )
            replay = []
            for identity, fields in retained:
                envelope = Envelope.model_validate_json(
                    fields.get(b"data", fields.get("data"))
                )
                if envelope.leta_id != leta_id:
                    raise ReplayLost("replay contains another root")
                if fresh.accepts(envelope.model_dump(mode="json"), historical=True):
                    replay.append((text(identity), envelope.model_dump(mode="json")))
            for item in coalesce_events(replay):
                yield sse(*item)
            yield custom(
                leta_id,
                "replay_ready",
                {"limited": fresh.limited, "refresh": routes(leta_id)},
                boundary if boundary != "0-0" else None,
            )
            after = boundary
        if state["root"]["status"] == "archived":
            return
        try:
            async with aclosing(live(context, redis, leta_id, after, fresh)) as source:
                async for frame in source:
                    yield frame
        except ReplayLost:
            lost = True
            bounds = await position(redis, leta_id)
            continue
        return


@router.get("/v1/letas/{leta_id}/events", response_class=EventResponse)
async def events(
    leta_id: UUID,
    context: API,
    last_event_id: Annotated[str | None, Header()] = None,
):
    """One root/children AG-UI stream with bounded Redis replay.

    Send Last-Event-ID only with the corresponding retained client state.
    state_refresh preserves partial text/args on valid resume. Fresh bootstrap
    supplies recent typed history and replay_ready establishes its cursor.
    resync_required resets unavailable provisional replay using committed PG
    state. CUSTOM activity entries use stable saved IDs; message references
    create chat bubbles only for actual owner/root messages. Compatible adjacent
    deltas are merged after Redis; each SSE id is its final consumed Redis ID.
    """
    await context.root(leta_id)
    headers = context.request.headers.getlist("last-event-id")
    if len(headers) > 1:
        raise fault("VALIDATION", "one Last-Event-ID is allowed", "invalid")
    after = last_event_id
    if after is not None:
        try:
            cursor(after)
        except ValueError as error:
            raise fault("VALIDATION", "invalid Last-Event-ID", "invalid") from error
    redis = context.request.app.state.resources.redis
    lost = False
    try:
        try:
            bounds = await position(redis, leta_id, after)
        except ReplayLost:
            lost = True
            bounds = await position(redis, leta_id)
    except RedisError as error:
        raise fault(
            "DEPENDENCY_UNAVAILABLE", "agent replay unavailable", "unavailable"
        ) from error
    return EventResponse(
        connection(context, redis, leta_id, after, bounds, lost),
        headers={
            "cache-control": "no-store",
            "x-accel-buffering": "no",
        },
    )
