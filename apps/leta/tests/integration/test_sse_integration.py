"""Real root replay through authenticated ASGI streaming, without TCP daemons."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid7

import pytest
from fastapi import Request
from redis.asyncio import Redis
from test_http import Authorization, headers
from test_store_integration import active_box, active_root

from leta.api import create_app
from leta.domain import NewActivity
from leta.http import events
from leta.http.common import Context, api
from leta.streaming import Publisher, keys, position

pytestmark = pytest.mark.integration


class Client:
    def __init__(self):
        self.input = asyncio.Queue()
        self.output = asyncio.Queue()
        self.frames = []

    async def receive(self):
        return await self.input.get()

    async def send(self, message):
        await self.output.put(message)

    async def until(self, predicate):
        async with asyncio.timeout(5):
            while True:
                message = await self.output.get()
                if message["type"] == "http.response.body":
                    body = message.get("body", b"")
                    for frame in body.decode().split("\n\n"):
                        if not frame or frame.startswith(":"):
                            continue
                        fields = dict(
                            line.split(": ", 1) for line in frame.splitlines()
                        )
                        self.frames.append(
                            (fields.get("id"), json.loads(fields["data"]))
                        )
                if predicate(message):
                    return message

    async def event(self, kind):
        await self.until(
            lambda _: any(
                e["event"].get("name", e["event"]["type"]) == kind
                for _, e in self.frames
            )
        )
        return next(
            (i, e)
            for i, e in reversed(self.frames)
            if e["event"].get("name", e["event"]["type"]) == kind
        )


@pytest.fixture
async def stream(store, redis_url, settings):
    authz = Authorization()
    app = create_app(settings)
    app.state.settings = settings
    async with Redis.from_url(redis_url) as redis:
        app.state.resources = SimpleNamespace(redis=redis)

        def context(request: Request):
            return Context(
                request,
                store,
                None,
                None,
                authz,
                request.state.principal.actor,
                settings.models,
            )

        app.dependency_overrides[api] = context

        @asynccontextmanager
        async def connect(root, *, after=None, user=None):
            client = Client()
            h = headers(settings, user or root.created_by_user_id)
            if after is not None:
                h["last-event-id"] = after
            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": f"/v1/letas/{root.id}/events",
                "query_string": b"",
                "root_path": "",
                "headers": [(k.encode(), v.encode()) for k, v in h.items()],
                "server": ("leta", 80),
                "client": ("127.0.0.1", 1000),
            }
            await client.input.put(
                {"type": "http.request", "body": b"", "more_body": False}
            )
            task = asyncio.create_task(app(scope, client.receive, client.send))
            try:
                start = await client.until(lambda m: m["type"] == "http.response.start")
                client.status = start["status"]
                client.headers = dict(start["headers"])
                yield client
            finally:
                await client.input.put({"type": "http.disconnect"})
                async with asyncio.timeout(5):
                    await task

        yield SimpleNamespace(
            connect=connect, redis=redis, publisher=Publisher(redis, store), authz=authz
        )


async def test_sse_fresh_resume_children_and_committed_dedup(stream, store):
    root = await active_root(store)
    box = await active_box(store, root)
    run = uuid7()
    await store.start_run(root.id, root.id, run)
    publisher = await stream.publisher.agent(root.id, root.id, run)
    child = await stream.publisher.agent(root.id, box.letis[0].id)
    await store.append_activity(
        NewActivity(
            id=uuid7(),
            agent_id=root.id,
            run_id=run,
            kind="final_note",
            dedup_key="saved",
            llm_message_id="saved",
            data={
                "llm_message_id": "saved",
                "content": [{"type": "text", "text": "Committed note"}],
            },
        )
    )
    for identity in ("saved", "partial"):
        await publisher.emit(
            {"type": "TEXT_MESSAGE_START", "messageId": identity, "role": "assistant"}
        )
        await publisher.emit(
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": identity, "delta": "prefix"}
        )
    async with stream.connect(root) as client:
        assert client.status == 200
        assert client.headers[b"content-type"].startswith(b"text/event-stream")
        await client.event("replay_ready")
        bootstrap = client.frames[0][1]["event"]["value"]
        assert len(bootstrap["agents"]) == 3
        assert bootstrap["entries"][0]["data"]["content"][0]["text"] == "Committed note"
        text = [
            e["event"]
            for _, e in client.frames
            if e["event"]["type"].startswith("TEXT_MESSAGE")
        ]
        assert [e["messageId"] for e in text] == ["partial", "partial"]
        after = client.frames[-1][0]
    await child.emit({"type": "CUSTOM", "name": "child_update", "value": {}})
    await publisher.emit(
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "partial", "delta": " suffix"}
    )
    await publisher.emit({"type": "TEXT_MESSAGE_END", "messageId": "partial"})
    async with stream.connect(root, after=after) as client:
        await client.event("TEXT_MESSAGE_END")
        assert [
            e["event"].get("name", e["event"]["type"]) for _, e in client.frames
        ] == [
            "state_refresh",
            "child_update",
            "TEXT_MESSAGE_CONTENT",
            "TEXT_MESSAGE_END",
        ]
        assert client.frames[1][1]["agent_id"] == str(box.letis[0].id)
        assert client.frames[2][1]["event"]["delta"] == " suffix"


async def test_sse_lost_cursor_orphan_and_authorization(stream, store, monkeypatch):
    root = await active_root(store)
    publisher = await stream.publisher.agent(root.id, root.id)
    await publisher.emit(
        {
            "type": "TEXT_MESSAGE_CONTENT",
            "messageId": "orphan",
            "delta": "missing start",
        }
    )
    async with stream.connect(root, after="1-0") as client:
        await client.event("replay_ready")
        assert [e["event"]["name"] for _, e in client.frames] == [
            "resync_required",
            "bootstrap",
            "replay_ready",
        ]
        assert client.frames[-1][1]["event"]["value"]["limited"] is True
    async with stream.connect(root, user=uuid7()) as client:
        assert client.status == 404
    async with stream.connect(root, after="bad") as client:
        assert client.status == 400
    stream.authz.member = False
    async with stream.connect(root) as client:
        assert client.status == 403
    stream.authz.member = True
    monkeypatch.setattr(events, "AUTH_SECONDS", 0)
    async with stream.connect(root) as client:
        await client.event("replay_ready")
        stream.authz.member = False
        await publisher.emit({"type": "CUSTOM", "name": "wake", "value": {}})
        await client.until(
            lambda m: (
                m["type"] == "http.response.body" and not m.get("more_body", False)
            )
        )
    assert await stream.redis.ping()


async def test_live_merge_flushes_without_new_events_and_cleans_reader(
    stream, store, monkeypatch
):
    root = await active_root(store)
    bound = await stream.publisher.agent(root.id, root.id)
    _, after = await position(stream.redis, root.id)
    stopped = asyncio.Event()
    original = events.read_events

    async def reader(*args, **kwargs):
        try:
            return await original(*args, **kwargs)
        finally:
            stopped.set()

    monkeypatch.setattr(events, "read_events", reader)
    context = SimpleNamespace(authz=stream.authz)
    iterator = events.live(context, stream.redis, root.id, after)
    await bound.emit({"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "a"})
    await bound.emit({"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "b"})
    async with asyncio.timeout(2):
        frame = await anext(iterator)
    assert json.loads(frame.decode().split("data: ")[1])["event"]["delta"] == "ab"
    stopped.clear()
    await iterator.aclose()
    assert stopped.is_set()
    assert await stream.redis.xlen(keys(root.id)[0]) == 2


async def test_idle_stream_receives_workflow_sources_and_closes_on_archive(
    stream, store, persistent_temporal
):
    from test_domain import box_input, root_input
    from test_human_requests_integration import ask
    from test_lifecycle_integration import RemoteServices, unused_runtime
    from test_schedules_integration import change

    from leta.temporal.bridges import (
        change_box,
        change_leta,
        change_schedule,
        open_human_request,
    )
    from leta.temporal.human_activities import HumanActivities
    from leta.temporal.human_types import OpenHumanRequest
    from leta.temporal.lifecycle_activities import LifecycleActivities
    from leta.temporal.lifecycle_types import BoxChange, LetaChange
    from leta.temporal.schedule_activities import ScheduleActivities
    from leta.worker import agent_workers

    root = root_input()
    services = RemoteServices(root)
    temporal = persistent_temporal
    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, temporal
    )
    human = HumanActivities(store, services.scopes, temporal)
    schedules = ScheduleActivities(store, temporal)
    async with agent_workers(
        temporal,
        store,
        unused_runtime,
        lifecycle,
        human,
        schedules,
        publisher=stream.publisher,
    ):
        await change_leta(
            temporal, LetaChange(leta_id=root.id, action="create", creation=root)
        )
        await change_leta(temporal, LetaChange(leta_id=root.id, action="pause"))
        async with stream.connect(root) as client:
            await client.event("replay_ready")
            before = len(client.frames)
            box = box_input(root.id)
            await change_box(
                temporal,
                BoxChange(
                    leta_id=root.id, box_id=box.id, action="create", creation=box
                ),
            )
            request = ask(root).model_copy(
                update={"requester_agent_id": box.letis[0].id}
            )
            await open_human_request(
                temporal,
                store,
                OpenHumanRequest(
                    leta_id=root.id,
                    request_id=request.id,
                    creation=request,
                    timeout_seconds=1,
                ),
            )
            await temporal.get_workflow_handle(f"human-request/{request.id}").result()
            command = change(root, spec={"type": "at", "after_seconds": 1})
            await change_schedule(temporal, command, command_id="create")
            await client.until(
                lambda _: any(
                    e["event"].get("name") == "resource"
                    and e["event"]["value"]["kind"] == "message"
                    and e["agent_id"] == str(root.id)
                    for _, e in client.frames[before:]
                )
            )
            # Archive settles schedules, children and their requests before closure.
            await change_leta(temporal, LetaChange(leta_id=root.id, action="deleting"))
            await client.until(
                lambda m: (
                    m["type"] == "http.response.body" and not m.get("more_body", False)
                )
            )
            updates = [
                e
                for _, e in client.frames[before:]
                if e["event"].get("name") == "resource"
            ]
            kinds = {e["event"]["value"]["kind"] for e in updates}
            assert kinds == {"box", "human_request", "message", "schedule", "agent"}
            assert any(
                e["agent_id"] == str(box.letis[0].id)
                and e["event"]["value"]["kind"] == "message"
                for e in updates
            )
            assert any(
                e["event"]["value"]["id"] == str(request.id)
                and e["event"]["value"]["status"] == "expired"
                for e in updates
            )
            assert updates[-1]["event"]["value"]["status"] == "archived"
