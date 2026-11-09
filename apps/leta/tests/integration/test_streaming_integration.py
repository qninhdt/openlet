import json
from uuid import uuid7

import pytest
from openlet.errors import AppError
from redis.asyncio import Redis
from test_store_integration import active_box, active_root

from leta import streaming
from leta.streaming import APPEND, Publisher, ReplayLost, keys, position, read_events

pytestmark = pytest.mark.integration


async def test_root_stream_interleaves_children_binds_authority_and_resumes_suffix(
    store, redis_url
):
    root, foreign = await active_root(store), await active_root(store)
    box = await active_box(store, root)
    run = uuid7()
    await store.start_run(root.id, root.id, run)
    async with Redis.from_url(redis_url) as redis:
        publisher = Publisher(redis, store)
        with pytest.raises(AppError):
            await publisher.agent(foreign.id, box.letis[0].id)
        bound = await publisher.agent(root.id, root.id, run)
        assert await bound.emit(
            {"type": "RUN_STARTED", "threadId": str(root.id), "runId": str(run)}
        )
        assert await bound.emit(
            {"type": "TEXT_MESSAGE_START", "messageId": "m", "role": "assistant"}
        )
        assert await bound.emit(
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "prefix"}
        )
        rows = await read_events(redis, root.id, "0-0")
        after = rows[-1][0]
        assert await position(redis, root.id, after)
        child = await publisher.agent(root.id, box.letis[1].id)
        assert await child.emit(
            {"type": "CUSTOM", "name": "request", "value": {"id": str(uuid7())}}
        )
        assert await bound.emit(
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": " suffix"}
        )
        assert await bound.emit({"type": "TEXT_MESSAGE_END", "messageId": "m"})
        suffix = await read_events(redis, root.id, after)
        assert len(suffix) == 3 and suffix[0][1]["agent_id"] == str(box.letis[1].id)
        assert suffix[1][1]["event"]["delta"] == " suffix"
        assert suffix[-1][1]["run_id"] == str(run)
        assert await redis.ttl(keys(root.id)[0]) > 86_390
        assert await redis.xlen(keys(foreign.id)[0]) == 0
        await redis.delete(*keys(root.id))
        with pytest.raises(ReplayLost):
            await position(redis, root.id, after)
        assert await position(redis, root.id) == ("0-0", "0-0")


async def test_atomic_root_log_caps_trim_expiry_and_independent_metadata_eviction(
    redis_url,
):
    root = uuid7()
    stream, accounting = keys(root)
    async with Redis.from_url(redis_url) as redis:
        async with redis.pipeline(transaction=False) as batch:
            for i in range(45):
                batch.eval(
                    APPEND,
                    2,
                    stream,
                    accounting,
                    json.dumps({"i": i, "padding": "x" * 20}),
                    1000,
                    20,
                    60,
                )
            identities = await batch.execute()
        rows = await redis.xrange(stream)
        assert len(rows) <= 20
        actual = sum(len(fields[b"data"]) for _, fields in rows)
        assert actual <= 1000 and int(await redis.get(accounting)) == actual
        with pytest.raises(ReplayLost):
            await position(redis, root, identities[0].decode())
        await redis.delete(accounting)
        current = await redis.eval(APPEND, 2, stream, accounting, "new", 1000, 20, 1)
        assert await redis.xrange(stream) == [(current, {b"data": b"new"})]
        assert int(await redis.get(accounting)) == 3
        await redis.pexpire(stream, 1)
        await redis.pexpire(accounting, 1)
        # Wait for observable expiry, bounded by a deadline.
        import asyncio

        async with asyncio.timeout(3):
            while await redis.exists(stream):
                await asyncio.sleep(0.01)
        assert await position(redis, root) == ("0-0", "0-0")
        await redis.eval(APPEND, 2, stream, accounting, "fresh", 1000, 20, 60)
        assert int(await redis.get(accounting)) == 5


async def test_failed_invocation_disables_further_publication_attempts(
    store, redis_url, monkeypatch
):
    root = await active_root(store)
    async with Redis.from_url(redis_url) as redis:
        bound = await Publisher(redis, store).agent(root.id, root.id)
        monkeypatch.setattr(streaming, "MAX_BYTES", 64)
        assert (
            await bound.emit({"type": "CUSTOM", "name": "test", "value": {}}) is False
        )
        assert bound.failed
        monkeypatch.setattr(streaming, "MAX_BYTES", streaming.MAX_BYTES * 1000)
        assert (
            await bound.emit({"type": "CUSTOM", "name": "test", "value": {}}) is False
        )
        assert (await store.get_agent(root.id, root.id))["status"] == "active"
        assert await redis.ping()


async def test_lost_append_reply_never_retries_a_committed_delta(store, redis_url):
    from types import SimpleNamespace

    root = await active_root(store)
    async with Redis.from_url(redis_url) as redis:
        calls = 0

        async def lose_reply(*arguments):
            nonlocal calls
            calls += 1
            await redis.eval(*arguments)
            raise TimeoutError("reply lost after commit")

        bound = await Publisher(SimpleNamespace(eval=lose_reply), store).agent(
            root.id, root.id
        )
        content = {
            "type": "TEXT_MESSAGE_CONTENT",
            "messageId": "m",
            "delta": "one copy",
        }
        assert await bound.emit(content) is False
        assert await bound.emit(content) is False
        assert calls == 1
        rows = await read_events(redis, root.id, "0-0")
        assert len(rows) == 1 and rows[0][1]["event"]["delta"] == "one copy"
