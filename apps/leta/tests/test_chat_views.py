"""SQL contracts against an explicitly supplied disposable database."""

import json
import os
from collections.abc import AsyncIterator, Coroutine, Generator
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import LiteralString, cast
from uuid import UUID, uuid4

import httpx
import pytest
from leta import activity, api, events, messages, reactions, sidebar, views
from leta.auth import Actor, Authorization
from leta.config import Services
from leta.db import Pool
from openlet_sdk.config import JSON
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis
from starlette.requests import Request


class TestAuth:
    __test__ = False

    async def require(self, actor: Actor, kind: str, id: UUID, permission: str) -> None:
        if permission in ("manage", "use"):
            raise PermissionError("permission denied")

    async def allowed(self, actor: Actor, kind: str, id: UUID, permission: str) -> bool:
        return permission != "manage"


class UseAuth(TestAuth):
    async def require(self, actor: Actor, kind: str, id: UUID, permission: str) -> None:
        if permission == "manage":
            raise PermissionError("permission denied")


async def test_revoked_stream_does_not_emit_initial_snapshot() -> None:
    class RevokedAuth(TestAuth):
        async def allowed(
            self, actor: Actor, kind: str, id: UUID, permission: str
        ) -> bool:
            return False

    # No DB/Redis is supplied: a revoked subscriber must not reach either.
    services = cast(Services, SimpleNamespace(auth=RevokedAuth()))
    response = await api.event_response(
        uuid4(),
        Request({"type": "http", "headers": []}),
        services,
        Actor("user", uuid4()),
        "use",
        {},
        private=True,
    )
    iterator = cast(AsyncIterator[object], response.body_iterator)  # pyright: ignore[reportUnknownMemberType]  # SSE accepts untyped dict items upstream.
    assert [event async for event in iterator] == []


@pytest.fixture
async def database() -> AsyncIterator[tuple[Pool, UUID, UUID, UUID, UUID]]:
    dsn = os.environ.get("OPENLET_CHAT_TEST_DSN")
    if not dsn:
        pytest.skip("Set OPENLET_CHAT_TEST_DSN to a disposable PostgreSQL database")
    schema = "chat_test_" + uuid4().hex
    admin = await AsyncConnection.connect(dsn, autocommit=True)
    await admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    db: Pool = AsyncConnectionPool(
        dsn,
        open=False,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "options": f"-c search_path={schema}",
        },
    )
    await db.open()
    try:
        async with db.connection() as conn:
            for migration in sorted(
                (Path(__file__).parents[1] / "migrations").glob("*.sql")
            ):
                await conn.execute(
                    sql.SQL(
                        cast(
                            LiteralString,
                            migration.read_text()
                            .split("-- +goose Down")[0]
                            .replace("-- +goose Up", ""),
                        )
                    )
                )
            root, workspace, user, other = (uuid4() for _ in range(4))
            await conn.execute(
                "INSERT INTO letas(id,workspace_id,storage_id,state) VALUES(%s,%s,%s,'active')",
                (root, workspace, uuid4()),
            )
            await conn.execute(
                "INSERT INTO agents(id,leta_id,name,system_prompt,handle) VALUES(%s,%s,'Atlas','private system instruction','atlas-the-agent')",
                (root, root),
            )
        yield db, root, workspace, user, other
    finally:
        await db.close()
        await admin.execute(
            sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
        )
        await admin.close()


async def test_sidebar_chat_reads_are_private_and_bounded(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, _, user, other = database
    first, latest, private = uuid4(), uuid4(), uuid4()
    async with db.connection() as conn:
        for id, recipient, text, stamp in [
            (first, user, "first reply", "2026-11-16T07:00:00Z"),
            (latest, user, "new reply", "2026-11-16T07:01:00Z"),
            (private, other, "private reply", "2026-11-16T07:02:00Z"),
        ]:
            await conn.execute(
                """INSERT INTO user_messages(id,leta_id,recipient_user_id,conversation_id,content,created_at)
                VALUES(%s,%s,%s,%s,%s,%s)""",
                (
                    id,
                    root,
                    recipient,
                    messages.conversation(root, "user", recipient),
                    text,
                    stamp,
                ),
            )
    mine = (await views.chat_summaries(db, [root], user))[root]
    assert mine["preview"] == "new reply" and mine["unread_count"] == 2
    assert mine["latest_reply_id"] == latest
    assert (
        cast(datetime, mine["latest_reply_at"]).isoformat()
        == "2026-11-16T07:01:00+00:00"
    )
    await views.mark_chat_read(db, root, user, first)
    assert (await views.chat_summaries(db, [root], user))[root]["unread_count"] == 1
    await views.mark_chat_read(
        db, root, user, first
    )  # A stale tab cannot consume a later reply.
    assert (await views.chat_summaries(db, [root], user))[root]["unread_count"] == 1
    with pytest.raises(LookupError):
        await views.mark_chat_read(db, root, user, private)
    theirs = (await views.chat_summaries(db, [root], other))[root]
    assert theirs["preview"] == "private reply" and theirs["unread_count"] == 1
    assert theirs["latest_reply_id"] == private
    await views.mark_chat_read(db, root, user, latest)
    assert (await views.chat_summaries(db, [root], user))[root]["unread_count"] == 0
    # A sent message updates the preview, while a silent reaction never becomes a chat preview.
    async with db.connection() as conn:
        await conn.execute(
            """INSERT INTO agent_messages(id,recipient_agent_id,seq,source_kind,source_id,conversation_id,content,input_type,silent)
            VALUES(%s,%s,1,'user',%s,%s,'my follow-up','message',false),
                  (%s,%s,2,'user',%s,%s,'reaction notification','reaction',true)""",
            (
                uuid4(),
                root,
                user,
                messages.conversation(root, "user", user),
                uuid4(),
                root,
                user,
                messages.conversation(root, "user", user),
            ),
        )
    assert (await views.chat_summaries(db, [root], user))[root][
        "preview"
    ] == "my follow-up"
    token = f":file[Budget \\] final]{{name={uuid4()}/{uuid4()}}}"
    content = f"Review {token} then " + "notes " * 80
    async with db.connection() as conn:
        await conn.execute(
            "UPDATE agent_messages SET content=%s WHERE recipient_agent_id=%s AND seq=1",
            (content, root),
        )
    assert (await views.chat_summaries(db, [root], user))[root]["preview"] == (
        "Review Budget ] final then " + "notes " * 80
    )[:240]
    assert await views.chat_summaries(db, [], user) == {}


async def test_directory_and_chat_read_endpoint_use_the_authenticated_recipient(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, workspace, user, other = database

    class DirectoryAuth(UseAuth):
        async def allowed_many(
            self, actor: Actor, kind: str, ids: list[UUID], permission: str
        ) -> set[UUID]:
            return set(ids) if permission == "use" else set()

    own, private = uuid4(), uuid4()
    async with db.connection() as conn:
        for id, recipient, content in [
            (own, user, "mine"),
            (private, other, "private"),
        ]:
            await conn.execute(
                "INSERT INTO user_messages(id,leta_id,recipient_user_id,conversation_id,content) VALUES(%s,%s,%s,%s,%s)",
                (
                    id,
                    root,
                    recipient,
                    messages.conversation(root, "user", recipient),
                    content,
                ),
            )
    services = cast(Services, SimpleNamespace(db=db, auth=DirectoryAuth()))
    api.app.dependency_overrides[api.services] = lambda: services
    base = f"/v1/workspaces/{workspace}/letas"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app),
            base_url="http://test",
            headers={"x-openlet-user-id": str(user)},
        ) as client:
            response = await client.get(base)
            assert response.status_code == 200
            assert response.json()["items"][0]["preview"] == "mine"
            assert response.json()["items"][0]["unread_count"] == 1
            await client.get(f"{base}/{root}/messages")
            assert (await client.get(base)).json()["items"][0]["unread_count"] == 1
            assert (
                await client.put(
                    f"{base}/{root}/messages/read", json={"through": str(private)}
                )
            ).status_code == 404
            assert (
                await client.put(
                    f"{base}/{root}/messages/read", json={"through": str(own)}
                )
            ).status_code == 200
            assert (await client.get(base)).json()["items"][0]["unread_count"] == 0
            theirs = await client.get(base, headers={"x-openlet-user-id": str(other)})
            assert theirs.json()["items"][0]["preview"] == "private"
            assert theirs.json()["items"][0]["unread_count"] == 1
    finally:
        api.app.dependency_overrides.clear()


async def test_private_chat_reply_roles_and_nonmutating_inbox(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, _, user, other = database
    auth = cast(Authorization, UseAuth())
    collision = uuid4()
    for actor, text, id in [(user, "mine", collision), (other, "secret", uuid4())]:
        await messages.admit(
            db,
            auth,
            [
                messages.Message(
                    id=id,
                    recipient_agent_id=root,
                    source_kind="user",
                    source_id=actor,
                    conversation_id=messages.conversation(root, "user", actor),
                    content=text,
                )
            ],
        )
    await messages.deliver_user(
        db,
        root,
        user,
        messages.conversation(root, "user", user),
        collision,
        [messages.Outgoing(collision, "agent reply", [])],
    )
    reply = messages.Message(
        id=uuid4(),
        recipient_agent_id=root,
        source_kind="user",
        source_id=user,
        conversation_id=messages.conversation(root, "user", user),
        content="reply to agent",
        in_reply_to_message_id=collision,
        in_reply_to_role="assistant",
    )
    await messages.admit(db, auth, [reply])
    assert await messages.admit(db, auth, [reply]) == await messages.admit(
        db, auth, [reply]
    )
    chat = await views.chat(db, root, user)
    items = cast(list[dict[str, object]], chat["items"])
    assert {item["content"] for item in items} == {
        "mine",
        "agent reply",
        "reply to agent",
    }
    assert len({(item["role"], item["id"]) for item in items}) == 3
    quoted = next(item for item in items if item["content"] == "reply to agent")
    assert quoted["reply"] == {
        "id": str(collision),
        "role": "assistant",
        "content": "agent reply",
    }
    token = f":file[Budget]{{name={uuid4()}/{uuid4()}}}"
    content = f"Read {token} " + "more " * 80
    async with db.connection() as conn:
        await conn.execute(
            "UPDATE user_messages SET content=%s WHERE id=%s", (content, collision)
        )
    items = cast(list[dict[str, object]], (await views.chat(db, root, user))["items"])
    quoted = next(item for item in items if item["content"] == "reply to agent")
    assert (
        cast(dict[str, object], quoted["reply"])["content"]
        == ("Read Budget " + "more " * 80)[:240]
    )
    assert any(item["content"] == content for item in items)
    foreign = reply.model_copy(
        update={
            "id": uuid4(),
            "source_id": other,
            "conversation_id": messages.conversation(root, "user", other),
        }
    )
    with pytest.raises(ValueError, match="this conversation"):
        await messages.admit(db, auth, [foreign])
    inbox = await views.inbox(db, root)
    assert len(cast(list[object], inbox["items"])) == 2
    detail = await views.conversation(
        db, root, messages.conversation(root, "user", user)
    )
    assert len(cast(list[object], detail["items"])) == 3
    async with db.connection() as conn:
        unread = await (
            await conn.execute(
                "SELECT count(*) AS n FROM agent_messages WHERE read_at IS NULL"
            )
        ).fetchone()
    assert unread and unread["n"] == 3


async def test_activity_suffix_pagination_does_not_skip_bursts(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, _, _, _ = database
    run = uuid4()
    async with db.connection() as conn:
        await conn.execute(
            "INSERT INTO runs(id,agent_id,status) VALUES(%s,%s,'running')", (run, root)
        )
        for seq in range(1, 47):
            await conn.execute(
                "INSERT INTO history(id,agent_id,run_id,seq,kind,payload) VALUES(%s,%s,%s,%s,'final_note',%s::jsonb)",
                (uuid4(), root, run, seq, json.dumps({"text": "note"})),
            )
    seqs: list[int] = []
    after = 0
    while True:
        page = await views.activity(db, root, after=after)
        items = cast(list[dict[str, int]], page["items"])
        seqs.extend(item["seq"] for item in items)
        if not page["next_cursor"]:
            break
        after = int(str(page["next_cursor"]))
    assert seqs == list(range(1, 47))
    text, snapshot = await activity.search_tool(db, root, 4, "note")
    entries = cast(list[dict[str, object]], snapshot["entries"])
    assert [entry["seq"] for entry in entries] == [3, 2, 1]
    assert entries[0]["text_preview"] == "note" and "Entry 3" in text
    assert snapshot["next_cursor"] is None


async def test_public_profile_and_all_inspection_routes_are_owner_only(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, workspace, user, other = database
    services = cast(Services, SimpleNamespace(db=db, auth=UseAuth()))
    api.app.dependency_overrides[api.services] = lambda: services
    request = uuid4()
    async with db.connection() as conn:
        await conn.execute(
            "INSERT INTO hitl_requests(id,requester_agent_id,recipient_user_id,type,title,payload) VALUES(%s,%s,%s,'ask','Private question','{\"questions\": []}')",
            (request, root, user),
        )
    base = f"/v1/workspaces/{workspace}/letas/{root}"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app),
            base_url="http://test",
            headers={"x-openlet-user-id": str(user)},
        ) as client:
            profile = await client.get(base)
            assert profile.status_code == 200
            assert (
                not {"system_prompt", "storage_id", "inbox_seq", "history_seq"}
                & profile.json().keys()
            )
            assert profile.json()["capabilities"]["can_view_activity"] is False
            for path in [
                "/events",
                f"/agents/{root}/history",
                f"/agents/{root}/history/1",
                f"/agents/{root}/settings",
                f"/agents/{root}/activity",
                "/inbox",
                "/boxes",
                "/schedules",
                "/hitl-requests",
                "/access",
            ]:
                assert (await client.get(base + path)).status_code == 403, path
            assert (
                await client.get(
                    f"/v1/hitl-requests/{request}",
                    headers={"x-openlet-user-id": str(other)},
                )
            ).status_code == 403
            # Recipient requests work even without agent.use.
            services.auth = cast(Authorization, TestAuth())
            assert (await client.get(f"/v1/hitl-requests/{request}")).status_code == 200
            own = await client.get(
                f"/v1/hitl-requests?workspace_id={workspace}&leta_id={root}"
            )
            assert own.status_code == 200 and len(own.json()["items"]) == 1
    finally:
        api.app.dependency_overrides.clear()


async def test_private_stream_isolation_and_trim_recovery() -> None:
    url = os.environ.get("OPENLET_CHAT_TEST_REDIS")
    if not url:
        pytest.skip("Set OPENLET_CHAT_TEST_REDIS to a disposable Redis")
    redis = Redis.from_url(url)  # pyright: ignore[reportUnknownMemberType]  # Redis kwargs are untyped.
    root, user, other = uuid4(), uuid4(), uuid4()
    try:
        await events.changed(redis, root, "messages", uuid4(), user)
        assert await redis.xlen(events.key(root)) == 1
        assert await redis.xlen(events.key(root, user)) == 1
        assert await redis.xlen(events.key(root, other)) == 0
        first = await events.tail(redis, root, user)
        await events.changed(redis, root, "requests", uuid4(), user)
        await redis.xtrim(events.key(root, user), maxlen=1, approximate=False)
        stream = events.suffix(redis, root, first, user)
        _, event = await anext(stream)
        assert event["name"] == "openlet.resync_required"

    finally:
        await redis.delete(
            events.key(root), events.key(root, user), events.key(root, other)
        )
        await redis.aclose()


async def test_reactions_are_private_idempotent_and_silent(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, _, user, other = database
    auth = cast(Authorization, UseAuth())
    original = uuid4()
    conv = messages.conversation(root, "user", user)
    await messages.deliver_user(
        db,
        root,
        user,
        conv,
        None,
        [messages.Outgoing(original, "The launch is ready", [])],
    )
    change = reactions.React(request_id=uuid4(), emoji="🎉")
    first = await reactions.react(
        db, auth, root, original, "outgoing", Actor("user", user), change
    )
    assert (
        await reactions.react(
            db, auth, root, original, "outgoing", Actor("user", user), change
        )
        == first
    )
    assert not await messages.has_pending(db, root, 0)
    assert await messages.pending(db, root, 0) == []
    assert (await views.chat(db, root, user))["items"]
    assert (await views.chat(db, root, other))["items"] == []
    with pytest.raises(LookupError):
        await reactions.react(
            db,
            auth,
            root,
            original,
            "outgoing",
            Actor("user", other),
            reactions.React(request_id=uuid4(), emoji="👍"),
        )
    async with db.connection() as conn:
        count = await (
            await conn.execute("SELECT count(*) AS n FROM agent_messages")
        ).fetchone()
    assert count and count["n"] == 1
    wake = messages.Message(
        id=uuid4(),
        recipient_agent_id=root,
        source_kind="user",
        source_id=user,
        conversation_id=conv,
        content="Continue",
    )
    await messages.admit(db, auth, [wake])
    batch = await messages.pending(db, root, 0, root=True)
    assert [r["input_type"] for r in batch] == ["reaction", "message"]
    assert "Reaction from user" in messages.input_batch(batch, root=True)
    assert not await messages.has_pending(db, root, 2)
    # Later silent feedback must not slip into an already running turn.
    await reactions.react(
        db,
        auth,
        root,
        original,
        "outgoing",
        Actor("user", user),
        reactions.React(request_id=uuid4(), emoji="❤️"),
    )
    assert await messages.pending(db, root, 2, silent_after=1) == []
    rows = await messages.read(db, root, user, "user")
    text = messages.input_batch(rows, root=False)
    assert any(r["input_type"] == "reaction" for r in rows) and "❤️" in text
    await messages.admit(db, auth, [wake.model_copy(update={"id": uuid4()})])
    # Explicitly reading a later reaction never skips another ordinary input.
    assert [
        r["input_type"] for r in await messages.pending(db, root, 2, silent_after=1)
    ] == ["message"]


async def test_agent_reaction_targets_received_message_and_roles_do_not_collide(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, _, user, other = database
    auth = cast(Authorization, UseAuth())
    id = uuid4()
    await messages.admit(
        db,
        auth,
        [
            messages.Message(
                id=id,
                recipient_agent_id=root,
                source_kind="user",
                source_id=user,
                conversation_id=messages.conversation(root, "user", user),
                content="We shipped!",
            )
        ],
    )
    await messages.deliver_user(
        db,
        root,
        user,
        messages.conversation(root, "user", user),
        None,
        [messages.Outgoing(id, "Great", [])],
    )
    await reactions.react(
        db,
        auth,
        root,
        id,
        "incoming",
        Actor("agent", root),
        reactions.React(request_id=uuid4(), emoji="🎉"),
    )
    page = await views.chat(db, root, user)
    items = cast(list[dict[str, object]], page["items"])
    assert next(i for i in items if i["role"] == "user")["reactions"]
    assert next(i for i in items if i["role"] == "assistant")["reactions"] == []
    with pytest.raises(LookupError):
        await reactions.react(
            db,
            auth,
            root,
            id,
            "incoming",
            Actor("user", other),
            reactions.React(request_id=uuid4(), emoji="👍"),
        )
    for invalid in ("hello", "👍🎉", "", "a"):
        with pytest.raises(ValueError):
            reactions.React(request_id=uuid4(), emoji=invalid)
    for valid in ("👍", "👨‍👩‍👧‍👦", "🇻🇳", "1️⃣", "👍🏽"):
        assert reactions.React(request_id=uuid4(), emoji=valid).emoji == valid


async def test_silent_backlog_does_not_skip_across_bounded_batches(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, _, user, _ = database
    auth = cast(Authorization, UseAuth())
    conv = messages.conversation(root, "user", user)
    for i in range(45):
        await messages.admit(
            db,
            auth,
            [
                messages.Message(
                    id=uuid4(),
                    recipient_agent_id=root,
                    source_kind="user",
                    source_id=user,
                    conversation_id=conv,
                    content=str(i),
                    silent=True,
                )
            ],
        )

    async def wake() -> None:
        await messages.admit(
            db,
            auth,
            [
                messages.Message(
                    id=uuid4(),
                    recipient_agent_id=root,
                    source_kind="user",
                    source_id=user,
                    conversation_id=conv,
                    content="wake",
                )
            ],
        )

    await wake()
    normal_cursor = quiet_cursor = 0
    seen: list[int] = []
    for _ in range(3):
        batch = await messages.pending(
            db, root, normal_cursor, silent_after=quiet_cursor
        )
        assert any(not r["silent"] for r in batch)
        quiet = [int(str(r["seq"])) for r in batch if r["silent"]]
        seen.extend(quiet)
        quiet_cursor = max(quiet, default=quiet_cursor)
        normal_cursor = max(int(str(r["seq"])) for r in batch if not r["silent"])
        assert not await messages.has_pending(db, root, normal_cursor)
        await wake()
    assert seen == list(range(1, 46))


async def test_sidebar_is_personal_and_rejects_stale_writes(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, workspace, user, other = database
    folder = uuid4()
    layout = sidebar.Layout(
        folders=[sidebar.Folder(id=folder, name="Work")],
        assignments={root: folder},
        pins=[root],
    )
    await sidebar.save(db, workspace, user, sidebar.Update(revision=0, layout=layout))
    assert (await sidebar.read(db, workspace, user))["revision"] == 1
    assert (await sidebar.read(db, workspace, other))["revision"] == 0
    with pytest.raises(sidebar.StaleLayout):
        await sidebar.save(
            db, workspace, user, sidebar.Update(revision=0, layout=layout)
        )
    with pytest.raises(ValueError):
        sidebar.Layout(
            folders=[sidebar.Folder(id=folder, name="Loop", parent_id=folder)]
        )


async def test_activity_and_inbox_use_canonical_reactions(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, _, user, _ = database
    auth = cast(Authorization, UseAuth())
    original, run, entry = uuid4(), uuid4(), uuid4()
    conv = messages.conversation(root, "user", user)
    await messages.admit(
        db,
        auth,
        [
            messages.Message(
                id=original,
                recipient_agent_id=root,
                source_kind="user",
                source_id=user,
                conversation_id=conv,
                content="Approved",
            )
        ],
    )
    await reactions.react(
        db,
        auth,
        root,
        original,
        "incoming",
        Actor("agent", root),
        reactions.React(request_id=uuid4(), emoji="👍"),
    )
    async with db.connection() as conn:
        await conn.execute(
            "INSERT INTO runs(id,agent_id,status) VALUES(%s,%s,'running')", (run, root)
        )
        await conn.execute(
            "INSERT INTO history(id,agent_id,run_id,seq,kind,payload) VALUES(%s,%s,%s,1,'inbox_input',%s::jsonb)",
            (
                entry,
                root,
                run,
                json.dumps(
                    {
                        "ui": {
                            "kind": "inbox_batch",
                            "items": [
                                {
                                    "id": str(original),
                                    "source_kind": "user",
                                    "content": "Approved",
                                }
                            ],
                        }
                    }
                ),
            ),
        )
        await conn.execute(
            "INSERT INTO history(id,agent_id,run_id,seq,kind,payload) VALUES(%s,%s,%s,2,'tool_result',%s::jsonb)",
            (
                uuid4(),
                root,
                run,
                json.dumps(
                    {
                        "ui": {
                            "kind": "schedule_list",
                            "items": [{"id": "not-a-message-uuid"}],
                        }
                    }
                ),
            ),
        )
    page = await views.activity(db, root)
    # UI identities are strings in JSONB; they must match SQL UUID reaction identities.
    assert "👍" in json.dumps(page, ensure_ascii=False)
    assert "👍" in json.dumps(
        await views.activity_entry(db, root, entry), ensure_ascii=False
    )
    assert "👍" in json.dumps(
        await views.conversation(db, root, conv), ensure_ascii=False
    )


async def test_sidebar_routes_scope_ids_and_emit_only_personal_events(
    database: tuple[Pool, UUID, UUID, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    db, root, workspace, user, other = database

    class ScopedAuth(UseAuth):
        async def require(
            self, actor: Actor, kind: str, id: UUID, permission: str
        ) -> None:
            if kind == "workspace" and id != workspace:
                raise PermissionError("wrong workspace")

        async def allowed_many(
            self, actor: Actor, kind: str, ids: list[UUID], permission: str
        ) -> set[UUID]:
            return set(ids) & {root} if actor.id == user else set()

    published: list[UUID | None] = []

    async def publish(
        redis: object, root: UUID, value: dict[str, JSON], user: UUID | None = None
    ) -> bool:
        published.append(user)
        return True

    monkeypatch.setattr(events, "publish", publish)
    services = cast(Services, SimpleNamespace(db=db, auth=ScopedAuth(), redis=None))
    api.app.dependency_overrides[api.services] = lambda: services
    path = f"/v1/workspaces/{workspace}/letas/sidebar"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app),
            base_url="http://test",
            headers={"x-openlet-user-id": str(user)},
        ) as client:
            folder = str(uuid4())
            layout = {
                "folders": [{"id": folder, "name": "Work", "parent_id": None}],
                "pins": [str(root)],
                "assignments": {str(root): folder},
                "order": [],
                "collapsed": [],
            }
            first = await client.put(path, json={"revision": 0, "layout": layout})
            assert first.status_code == 200 and first.json()["revision"] == 1
            assert published == [user]
            assert (
                await client.put(path, json={"revision": 0, "layout": layout})
            ).status_code == 409
            foreign = {**layout, "pins": [str(uuid4())]}
            assert (
                await client.put(path, json={"revision": 1, "layout": foreign})
            ).status_code == 403
            assert (
                await client.get(f"/v1/workspaces/{uuid4()}/letas/sidebar")
            ).status_code == 403
            own = await client.get(path)
            assert own.json()["layout"]["pins"] == [str(root)]
            shared = await client.get(path, headers={"x-openlet-user-id": str(other)})
            assert shared.json()["revision"] == 0
            assert (
                await client.put(
                    path,
                    json={"revision": 0, "layout": layout},
                    headers={"x-openlet-user-id": str(other)},
                )
            ).status_code == 403
    finally:
        api.app.dependency_overrides.clear()


async def test_agent_reactions_follow_graph_and_roll_back_invalid_delivery(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, _, _, _ = database
    box, scout, forge, leader = uuid4(), uuid4(), uuid4(), uuid4()
    auth = cast(Authorization, UseAuth())
    low, high = sorted((scout, forge))
    async with db.connection() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO boxes(id,leta_id,name,leader_agent_id,home_node_id,state,handle) VALUES(%s,%s,'review',%s,%s,'active','review')",
            (box, root, leader, uuid4()),
        )
        for id, name in ((scout, "Scout"), (forge, "Forge"), (leader, "Vega")):
            await conn.execute(
                "INSERT INTO agents(id,leta_id,box_id,name,system_prompt,handle) VALUES(%s,%s,%s,%s,'Work',%s)",
                (id, root, box, name, name.lower()),
            )
        await conn.execute(
            "INSERT INTO box_links(box_id,agent_low_id,agent_high_id) VALUES(%s,%s,%s)",
            (box, low, high),
        )
    original = uuid4()
    await messages.admit(
        db,
        auth,
        [
            messages.Message(
                id=original,
                recipient_agent_id=scout,
                source_kind="agent",
                source_id=forge,
                conversation_id=uuid4(),
                content="Checks passed",
            )
        ],
    )
    await reactions.react(
        db,
        auth,
        root,
        original,
        "incoming",
        Actor("agent", scout),
        reactions.React(request_id=uuid4(), emoji="✅"),
    )
    assert not await messages.has_pending(db, forge, 0)
    async with db.connection() as conn:
        notification = await (
            await conn.execute(
                "SELECT * FROM agent_messages WHERE recipient_agent_id=%s", (forge,)
            )
        ).fetchone()
        assert (
            notification
            and notification["silent"]
            and notification["input_type"] == "reaction"
        )
        await conn.execute("DELETE FROM box_links WHERE box_id=%s", (box,))
    with pytest.raises(ValueError, match="communication graph"):
        await reactions.react(
            db,
            auth,
            root,
            original,
            "incoming",
            Actor("agent", scout),
            reactions.React(request_id=uuid4(), emoji="👍"),
        )
    async with db.connection() as conn:
        canonical = await (
            await conn.execute(
                "SELECT emoji FROM message_reactions WHERE message_id=%s", (original,)
            )
        ).fetchone()
        assert canonical and canonical["emoji"] == "✅"
    with pytest.raises(PermissionError, match="received messages"):
        await reactions.react(
            db,
            auth,
            root,
            original,
            "incoming",
            Actor("agent", root),
            reactions.React(request_id=uuid4(), emoji="👍"),
        )


async def test_reaction_endpoint_publishes_only_authorized_user_changes(
    database: tuple[Pool, UUID, UUID, UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    db, root, workspace, user, other = database
    original = uuid4()
    await messages.deliver_user(
        db,
        root,
        user,
        messages.conversation(root, "user", user),
        None,
        [messages.Outgoing(original, "Ready for review", [])],
    )
    published: list[tuple[UUID, UUID | None]] = []

    async def publish(
        redis: object, root: UUID, value: dict[str, JSON], user: UUID | None = None
    ) -> bool:
        published.append((root, user))
        return True

    monkeypatch.setattr(events, "publish", publish)
    services = cast(Services, SimpleNamespace(db=db, auth=UseAuth(), redis=None))
    api.app.dependency_overrides[api.services] = lambda: services
    path = f"/v1/workspaces/{workspace}/letas/{root}/messages/assistant/{original}/reaction"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app),
            base_url="http://test",
            headers={"x-openlet-user-id": str(user)},
        ) as client:
            assert (
                await client.put(path, json={"request_id": str(uuid4()), "emoji": "👍"})
            ).status_code == 200
            assert published == [(root, None), (root, user)]
            assert (
                await client.put(
                    path,
                    json={"request_id": str(uuid4()), "emoji": "❤️"},
                    headers={"x-openlet-user-id": str(other)},
                )
            ).status_code == 404
            assert len(published) == 2
            assert (
                await client.put(
                    path, json={"request_id": str(uuid4()), "emoji": "not emoji"}
                )
            ).status_code == 422
            assert (
                await client.get(
                    path.replace(str(workspace), str(uuid4())).split("/messages/")[0]
                )
            ).status_code == 404
            assert not await messages.has_pending(db, root, 0)
    finally:
        api.app.dependency_overrides.clear()


def test_provisioning_profile_does_not_offer_chat() -> None:
    for state in ("provisioning", "deleting", "archived", "active"):
        capabilities = cast(
            dict[str, JSON], views.profile({"state": state}, False)["capabilities"]
        )
        assert capabilities["can_chat"] == (state == "active")


async def test_box_identity_graph_and_runtime_state(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    from leta import box_views, boxes
    from leta.agents import Appearance, ConfigureAgent, appearance
    from pydantic import ValidationError

    db, root, _, _, _ = database
    box_id = uuid4()
    creation = boxes.BoxCreation(
        leta_id=root,
        box_id=box_id,
        request_id=uuid4(),
        request=boxes.CreateBox(
            name="research",
            leader="Iris",
            letis=[
                boxes.LetiDefinition(
                    name="Iris", title="Researcher", system_prompt="private iris"
                ),
                boxes.LetiDefinition(
                    name="Milo", title="Researcher", system_prompt="private milo"
                ),
            ],
        ),
    )
    first = await boxes.prepare(db, creation, uuid4(), creation.request.name)
    assert await boxes.prepare(db, creation, uuid4(), creation.request.name) == first
    detail = await boxes.get(db, root, box_id)
    members = cast(list[dict[str, JSON]], detail["letis"])
    assert len(members) == 2 and {str(m["title"]) for m in members} == {"Researcher"}
    iris = next(m for m in members if m["name"] == "Iris")
    milo = next(m for m in members if m["name"] == "Milo")
    assert iris["appearance"] == appearance(UUID(str(iris["id"])))
    assert all("system_prompt" not in m for m in members)
    with pytest.raises(ValidationError):
        Appearance(shape="square", color="unknown")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ConfigureAgent(title=None)
    with pytest.raises(ValidationError):
        ConfigureAgent(appearance=None)
    assert ConfigureAgent(title="").title == ""

    from leta.runtime.agent import box_context, runtime_agent
    from psycopg.errors import CheckViolation

    services = cast(Services, SimpleNamespace(db=db))
    context = await box_context(
        services, await runtime_agent(services, UUID(str(iris["id"])))
    )
    assert "You are the Box Leader" in context and "Milo The Researcher" in context
    async with db.connection() as conn:
        with pytest.raises(CheckViolation):
            await conn.execute(
                'UPDATE agents SET appearance=\'{"shape":null,"color":"bleu"}\' WHERE id=%s',
                (iris["id"],),
            )

    run, stale = uuid4(), uuid4()
    async with db.connection() as conn:
        await conn.execute(
            "INSERT INTO runs(id,agent_id,status,heartbeat_at) VALUES(%s,%s,'running',now()),(%s,%s,'running',now()-interval '1 minute')",
            (run, iris["id"], stale, milo["id"]),
        )
    graph = await box_views.graph(db, [root])
    agents = cast(list[dict[str, JSON]], graph["agents"])
    assert next(a for a in agents if a["id"] == iris["id"])["status"] == "working"
    assert next(a for a in agents if a["id"] == milo["id"])["status"] == "unknown"
    assert "private iris" not in json.dumps(graph)
    assert len(cast(list[JSON], graph["additional_links"])) == 0
    assert (await box_views.graph(db, []))["agents"] == []
    async with db.connection() as conn:
        await conn.execute("UPDATE letas SET paused=true WHERE id=%s", (root,))
    assert all(
        a["status"] == "paused"
        for a in cast(
            list[dict[str, JSON]], (await box_views.graph(db, [root]))["agents"]
        )
    )


async def test_box_view_filters_management_and_workspace(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, workspace, user, other = database

    class BoxAuth(TestAuth):
        async def require(
            self, actor: Actor, kind: str, id: UUID, permission: str
        ) -> None:
            if kind != "workspace" or id != workspace:
                raise PermissionError("wrong workspace")

        async def allowed_many(
            self, actor: Actor, kind: str, ids: list[UUID], permission: str
        ) -> set[UUID]:
            assert permission == "manage"
            return {root} & set(ids) if actor.id == user else set()

    services = cast(Services, SimpleNamespace(db=db, auth=BoxAuth()))
    api.app.dependency_overrides[api.services] = lambda: services
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app),
            base_url="http://test",
            headers={"x-openlet-user-id": str(user)},
        ) as client:
            path = f"/v1/workspaces/{workspace}/letas/box-view"
            response = await client.get(path)
            assert response.status_code == 200
            assert response.json()["letas"] == [str(root)]
            assert response.json()["agents"][0]["name"] == "Atlas"
            denied = await client.get(path, headers={"x-openlet-user-id": str(other)})
            assert denied.status_code == 200 and denied.json()["agents"] == []
            assert (
                await client.get(f"/v1/workspaces/{uuid4()}/letas/box-view")
            ).status_code == 403
    finally:
        api.app.dependency_overrides.clear()


async def test_leti_inbox_includes_sent_messages_without_marking_read(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    from leta import boxes

    db, root, workspace, user, _ = database
    creation = boxes.BoxCreation(
        leta_id=root,
        box_id=uuid4(),
        request_id=uuid4(),
        request=boxes.CreateBox(
            name="reporters",
            leader="Iris",
            letis=[
                boxes.LetiDefinition(
                    name="Iris", title="Reporter", system_prompt="Iris"
                ),
                boxes.LetiDefinition(
                    name="Milo", title="Researcher", system_prompt="Milo"
                ),
            ],
        ),
    )
    await boxes.prepare(db, creation, uuid4(), creation.request.name)
    detail = await boxes.get(db, root, creation.box_id)
    members = cast(list[dict[str, JSON]], detail["letis"])
    iris = UUID(str(next(m["id"] for m in members if m["name"] == "Iris")))
    milo = UUID(str(next(m["id"] for m in members if m["name"] == "Milo")))
    peer, parent = uuid4(), uuid4()
    async with db.connection() as conn:
        await conn.execute(
            """INSERT INTO agent_messages(id,recipient_agent_id,seq,source_kind,source_id,conversation_id,content)
            VALUES(%s,%s,1,'agent',%s,%s,'findings for Milo'),(%s,%s,1,'agent',%s,%s,'report to Atlas')""",
            (uuid4(), milo, iris, peer, uuid4(), root, iris, parent),
        )
    inbox = await views.inbox(db, iris)
    assert {str(i["content"]) for i in cast(list[dict[str, JSON]], inbox["items"])} == {
        "findings for Milo",
        "report to Atlas",
    }
    conversation = await views.conversation(db, iris, peer)
    assert cast(list[dict[str, JSON]], conversation["items"])[0]["direction"] == "out"
    async with db.connection() as conn:
        rows = await (
            await conn.execute("SELECT read_at FROM agent_messages")
        ).fetchall()
    assert all(r["read_at"] is None for r in rows)

    class ManageAuth(TestAuth):
        async def require(
            self, actor: Actor, kind: str, id: UUID, permission: str
        ) -> None:
            if actor.id != user or kind != "agent" or id != root:
                raise PermissionError("permission denied")

    services = cast(Services, SimpleNamespace(db=db, auth=ManageAuth()))
    api.app.dependency_overrides[api.services] = lambda: services
    try:
        async with db.connection() as conn:
            await conn.execute(
                "UPDATE boxes SET state='active' WHERE id=%s", (creation.box_id,)
            )
            foreign = uuid4()
            await conn.execute(
                "INSERT INTO letas(id,workspace_id,storage_id,state) VALUES(%s,%s,%s,'active')",
                (foreign, workspace, uuid4()),
            )
            await conn.execute(
                "INSERT INTO agents(id,leta_id,name,system_prompt,handle) VALUES(%s,%s,'Other','secret','other-the-agent')",
                (foreign, foreign),
            )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app),
            base_url="http://test",
            headers={"x-openlet-user-id": str(user)},
        ) as client:
            path = f"/v1/workspaces/{workspace}/letas/{root}"
            response = await client.get(f"{path}/inbox?agent_id={iris}")
            assert response.status_code == 200
            assert {i["content"] for i in response.json()["items"]} == {
                "findings for Milo",
                "report to Atlas",
            }
            assert (
                await client.get(f"{path}/agents/{iris}/activity")
            ).status_code == 200
            assert (
                await client.get(f"{path}/agents/{foreign}/activity")
            ).status_code == 404
            assert (
                await client.get(f"{path}/inbox?agent_id={foreign}")
            ).status_code == 404
            assert (
                await client.get(f"{path}/schedules?agent_id={foreign}")
            ).status_code == 404
            avatar = {"shape": "goutte", "color": "bleu"}
            response = await client.patch(
                f"{path}/agents/{iris}",
                json={"title": "Reporter", "appearance": avatar},
            )
            assert (
                response.status_code == 200 and response.json()["appearance"] == avatar
            )
            assert (
                await client.patch(f"{path}/agents/{iris}", json={"name": "Iris Prime"})
            ).status_code == 200
            saved = (await client.get(f"{path}/agents/{iris}/settings")).json()
            assert (
                saved["name"] == "Iris Prime"
                and saved["title"] == "Reporter"
                and saved["appearance"] == avatar
            )
    finally:
        api.app.dependency_overrides.clear()


async def test_conversation_storage_is_lazy_serialized_and_retries_failed_acl(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from leta import conversations

    db, root, workspace, user, _other = database
    auth = UseAuth()
    auth.write = AsyncMock()  # type: ignore[attr-defined]

    class Creation:
        def __init__(self, result: Coroutine[object, object, object]) -> None:
            self.result = result

        def __await__(self) -> Generator[object, object, object]:
            return self.result.__await__()

        async def initial_metadata(self) -> tuple[tuple[str, str], ...]:
            return (("x-openlet-zed-token", "created-revision"),)

    create = AsyncMock(side_effect=RuntimeError("ACL unavailable"))

    def create_storage(*args: object, **kwargs: object) -> Creation:
        return Creation(create(*args, **kwargs))

    remote = SimpleNamespace(CreateStorage=create_storage)
    services = cast(Services, SimpleNamespace(db=db, auth=auth, storage=remote))
    async with db.connection() as conn:
        count = await (
            await conn.execute("SELECT count(*) AS n FROM conversations")
        ).fetchone()
        assert count is not None and count["n"] == 0
    with pytest.raises(RuntimeError, match="ACL unavailable"):
        await conversations.storage(services, root, user)
    create.side_effect = None
    values = await asyncio.gather(
        conversations.storage(services, root, user),
        conversations.storage(services, root, user),
    )
    assert values[0]["storage_id"] == values[1]["storage_id"]
    assert values[0]["ready"] is True
    assert {value["zed_token"] for value in values} == {"", "created-revision"}
    assert create.await_count == 2
    assert create.await_args is not None
    request = create.await_args.args[0]
    assert request.owner.conversation_id == str(
        messages.conversation(root, "user", user)
    )
    assert request.workspace_id == str(workspace)
    async with db.connection() as conn:
        count = await (
            await conn.execute("SELECT count(*) AS n FROM conversations")
        ).fetchone()
        assert count is not None and count["n"] == 1
    create.reset_mock()
    await conversations.storage(services, root, user)
    create.assert_not_awaited()


async def test_chat_and_inbox_preserve_file_metadata_without_prompt_inventory(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, _workspace, user, other = database
    file_id, storage = uuid4(), uuid4()
    token = f":file[estimate]{{name={storage}/{file_id}}}"
    refs: list[JSON] = [
        {
            "storage_id": str(storage),
            "node_id": str(file_id),
            "label": "estimate",
            "name": "Budget.csv",
            "mime": "text/csv",
            "size": 20,
            "version": 1,
        }
    ]
    message = messages.Message(
        id=uuid4(),
        recipient_agent_id=root,
        source_kind="user",
        source_id=user,
        conversation_id=messages.conversation(root, "user", user),
        content=token,
        file_refs=refs,
    )
    await messages.admit(db, cast(Authorization, UseAuth()), [message])
    await messages.deliver_user(
        db,
        root,
        user,
        message.conversation_id,
        None,
        [messages.Outgoing(uuid4(), token, refs)],
    )
    chat = await views.chat(db, root, user)
    assert all(
        item["file_refs"] == refs for item in cast(list[dict[str, JSON]], chat["items"])
    )
    assert (await views.chat(db, root, other))["items"] == []
    inbox = await views.conversation(db, root, message.conversation_id)
    assert all(
        item["file_refs"] == refs
        for item in cast(list[dict[str, JSON]], inbox["items"])
    )
    rows = await messages.read(db, root, user, "user")
    prompt = messages.input_batch(rows, root=False)
    assert token in prompt
    assert "\nfiles:" not in prompt
    items = cast(list[dict[str, JSON]], messages.input_data(rows, root=False)["items"])
    assert items[0]["file_refs"] == refs


async def test_injected_full_messages_are_read_but_previews_remain_unread(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, _, user, _ = database
    auth = cast(Authorization, UseAuth())
    contents = [
        "xin quyền đi",
        "a" * 120,
        "\n\t" + " " * 117 + "x",
        "long " * 80,
        "ok bye",
    ]
    for text in contents:
        await messages.admit(
            db,
            auth,
            [
                messages.Message(
                    id=uuid4(),
                    recipient_agent_id=root,
                    source_kind="user",
                    source_id=user,
                    conversation_id=messages.conversation(root, "user", user),
                    content=text,
                )
            ],
        )
    batch = await messages.pending(db, root, 0, root=True)
    body = messages.input_batch(batch, root=True)
    assert all(f"message={i}" in body for i in range(1, 6))
    assert body.count("Full message:") == 4
    assert "From User | message=1" in body
    assert contents[2] in body
    async with db.connection() as conn:
        rows = await (
            await conn.execute("SELECT seq,read_at FROM agent_messages ORDER BY seq")
        ).fetchall()
    assert [row["seq"] for row in rows if row["read_at"] is None] == [4]
    unread = await messages.read(db, root, user, "user")
    text = messages.input_batch(unread, root=False)
    assert [row["seq"] for row in unread] == [4]
    assert contents[3] in text and "ok bye" not in text
    # A failed checkpoint may replay the batch; read marks never suppress delivery.
    replay = await messages.pending(db, root, 0, root=True)
    assert [row["seq"] for row in replay] == list(range(1, 6))
    assert await messages.pending(db, root, 5, root=True) == []


async def test_inbox_listing_marks_only_complete_returned_message_read(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, _, user, _ = database
    auth = cast(Authorization, UseAuth())
    for text in ("long " * 80, "a short follow-up"):
        await messages.admit(
            db,
            auth,
            [
                messages.Message(
                    id=uuid4(),
                    recipient_agent_id=root,
                    source_kind="user",
                    source_id=user,
                    conversation_id=messages.conversation(root, "user", user),
                    content=text,
                )
            ],
        )
    rows = await messages.list_inbox(db, root)
    text = messages.input_batch(rows, root=True)
    assert [row["seq"] for row in rows] == [2] and "Full message:" in text
    unread = await messages.read(db, root, user, "user")
    assert [row["seq"] for row in unread] == [1]


async def test_chat_context_and_processing_stay_in_the_requesters_conversation(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, workspace, user, other = database
    own, private, run = uuid4(), uuid4(), uuid4()
    async with db.connection() as conn:
        for index in range(25):
            await conn.execute(
                "INSERT INTO user_messages(id,leta_id,recipient_user_id,conversation_id,content) VALUES(%s,%s,%s,%s,%s)",
                (
                    own if index == 0 else uuid4(),
                    root,
                    user,
                    messages.conversation(root, "user", user),
                    f"báo cáo budget {index}",
                ),
            )
        await conn.execute(
            "INSERT INTO user_messages(id,leta_id,recipient_user_id,conversation_id,content) VALUES(%s,%s,%s,%s,'private budget')",
            (private, root, other, messages.conversation(root, "user", other)),
        )
        await conn.execute(
            "INSERT INTO runs(id,agent_id,status,heartbeat_at) VALUES(%s,%s,'running',now())",
            (run, root),
        )
        await conn.execute(
            "INSERT INTO agent_messages(id,recipient_agent_id,seq,source_kind,source_id,conversation_id,content,processing_run_id) VALUES(%s,%s,1,'user',%s,%s,'budget request',%s)",
            (uuid4(), root, user, messages.conversation(root, "user", user), run),
        )
    services = cast(Services, SimpleNamespace(db=db, auth=UseAuth()))
    api.app.dependency_overrides[api.services] = lambda: services
    base = f"/v1/workspaces/{workspace}/letas/{root}"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api.app),
            base_url="http://test",
            headers={"x-openlet-user-id": str(user)},
        ) as client:
            context = await client.get(f"{base}/messages/assistant/{own}/context")
            assert context.status_code == 200
            assert any(item["id"] == str(own) for item in context.json()["items"])
            assert all(
                item["content"] != "private budget" for item in context.json()["items"]
            )
            assert (
                await client.get(f"{base}/messages/assistant/{private}/context")
            ).status_code == 404
            assert (await client.get(f"{base}/processing")).json() == {
                "working": True,
                "run_id": None,
            }
            assert (
                await client.get(
                    f"{base}/processing", headers={"x-openlet-user-id": str(other)}
                )
            ).json() == {"working": False, "run_id": None}
            async with db.connection() as conn:
                await conn.execute(
                    "UPDATE runs SET heartbeat_at=now()-interval '1 minute' WHERE id=%s",
                    (run,),
                )
            assert (await client.get(f"{base}/processing")).json() == {
                "working": False,
                "run_id": None,
            }
    finally:
        api.app.dependency_overrides.clear()


async def test_two_way_conversation_history_is_chronological_and_read_only(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, _, user, other = database
    auth = cast(Authorization, UseAuth())
    conv = messages.conversation(root, "user", user)
    msg1, msg2, reply1 = uuid4(), uuid4(), uuid4()
    await messages.admit(
        db,
        auth,
        [
            messages.Message(
                id=msg1,
                recipient_agent_id=root,
                source_kind="user",
                source_id=user,
                conversation_id=conv,
                content="Gửi anh báo cáo Q4 nhé.",
            )
        ],
    )
    await messages.deliver_user(
        db,
        root,
        user,
        conv,
        msg1,
        [
            messages.Outgoing(
                reply1,
                "Dạ đây là file báo cáo Q4 ạ.",
                [
                    {
                        "storage_id": str(uuid4()),
                        "node_id": str(uuid4()),
                        "label": "bao-cao-q4.pdf",
                    }
                ],
            )
        ],
    )
    await messages.admit(
        db,
        auth,
        [
            messages.Message(
                id=msg2,
                recipient_agent_id=root,
                source_kind="user",
                source_id=user,
                conversation_id=conv,
                in_reply_to_message_id=reply1,
                in_reply_to_role="assistant",
                content="Ok em, chuẩn rồi.",
            )
        ],
    )
    await reactions.react(
        db,
        auth,
        root,
        msg1,
        "incoming",
        Actor("agent", root),
        reactions.React(request_id=uuid4(), emoji="👀"),
    )
    await reactions.react(
        db,
        auth,
        root,
        reply1,
        "outgoing",
        Actor("user", user),
        reactions.React(request_id=uuid4(), emoji="👍"),
    )

    page1, older = await messages.conversation_history(
        db, root, root, user, "user", peer_label="Ethan#ethan", limit=2
    )
    assert older is not None
    assert [r["content"] for r in page1] == [
        "Dạ đây là file báo cáo Q4 ạ.",
        "Ok em, chuẩn rồi.",
    ]
    assert cast(dict[str, object], page1[0]["reply"])["seq"] == 1
    assert cast(list[dict[str, object]], page1[0]["reactions"])[0]["emoji"] == "👍"
    assert (
        cast(dict[str, object], page1[1]["reply"])["content"]
        == "Dạ đây là file báo cáo Q4 ạ."
    )

    page2, end = await messages.conversation_history(
        db, root, root, user, "user", peer_label="Ethan#ethan", cursor=older, limit=2
    )
    assert end is None and len(page2) == 1
    assert (
        page2[0]["seq"] == 1
        and cast(list[dict[str, object]], page2[0]["reactions"])[0]["emoji"] == "👀"
    )

    filtered, filtered_cursor = await messages.conversation_history(
        db,
        root,
        root,
        user,
        "user",
        peer_label="Ethan#ethan",
        query="bao-cao-q4",
        limit=20,
    )
    assert filtered_cursor is None and len(filtered) == 1
    assert filtered[0]["id"] == reply1

    async with db.connection() as conn:
        unread = await (
            await conn.execute(
                "SELECT count(*) AS n FROM agent_messages WHERE recipient_agent_id=%s AND input_type='message' AND read_at IS NULL AND processing_run_id IS NULL",
                (root,),
            )
        ).fetchone()
    assert unread and unread["n"] == 2

    # Agent <-> agent two-way history + incoming reactions on both directions
    box_id, leti = uuid4(), uuid4()
    async with db.connection() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO boxes(id,leta_id,name,leader_agent_id,home_node_id,state,handle) VALUES(%s,%s,'team',%s,%s,'active','team')",
            (box_id, root, leti, uuid4()),
        )
        await conn.execute(
            "INSERT INTO agents(id,leta_id,box_id,name,title,handle,system_prompt) VALUES(%s,%s,%s,'Leti','Analyst','leti-the-analyst','Work.')",
            (leti, root, box_id),
        )
    pair_conv = messages.agent_conversation(root, leti)
    a_out, a_in = uuid4(), uuid4()
    await messages.admit(
        db,
        auth,
        [
            messages.Message(
                id=a_out,
                recipient_agent_id=leti,
                source_kind="agent",
                source_id=root,
                conversation_id=pair_conv,
                content="Check revenue.",
            )
        ],
    )
    await messages.admit(
        db,
        auth,
        [
            messages.Message(
                id=a_in,
                recipient_agent_id=root,
                source_kind="agent",
                source_id=leti,
                conversation_id=pair_conv,
                in_reply_to_message_id=a_out,
                content="Revenue verified: $1.2M.",
            )
        ],
    )
    await reactions.react(
        db,
        auth,
        root,
        a_out,
        "incoming",
        Actor("agent", leti),
        reactions.React(request_id=uuid4(), emoji="✅"),
    )
    await reactions.react(
        db,
        auth,
        root,
        a_in,
        "incoming",
        Actor("agent", root),
        reactions.React(request_id=uuid4(), emoji="🎉"),
    )
    agent_thread, agent_cursor = await messages.conversation_history(
        db, root, root, leti, "agent", peer_label="Leti#leti-the-analyst", limit=10
    )
    assert agent_cursor is None
    assert [r["direction"] for r in agent_thread] == ["out", "in"]
    assert (
        cast(list[dict[str, object]], agent_thread[0]["reactions"])[0]["emoji"] == "✅"
    )
    assert (
        cast(list[dict[str, object]], agent_thread[1]["reactions"])[0]["emoji"] == "🎉"
    )
    assert (
        cast(dict[str, object], agent_thread[1]["reply"])["content"] == "Check revenue."
    )
    other_rows, _ = await messages.conversation_history(
        db, root, root, other, "user", peer_label="Other#other"
    )
    assert other_rows == []


async def test_activity_search_and_read_filters_reasoning_and_tool_pairing(
    database: tuple[Pool, UUID, UUID, UUID, UUID],
) -> None:
    db, root, _, _, _ = database
    run = uuid4()
    async with db.connection() as conn:
        await conn.execute(
            "INSERT INTO runs(id,agent_id,status) VALUES(%s,%s,'running')", (run, root)
        )
        rows = [
            (1, "final_note", {"text": "", "reasoning": "Internal milestone note"}),
            (
                2,
                "tool_call",
                {"tool_call_id": "t1", "name": "execute", "args": {"command": "ls"}},
            ),
            (
                3,
                "tool_result",
                {
                    "tool_call_id": "t1",
                    "name": "execute",
                    "status": "error",
                    "text": "Boom",
                },
            ),
            (
                4,
                "tool_call",
                {
                    "tool_call_id": "t2",
                    "name": "activity_search",
                    "args": {"query": "ls"},
                },
            ),
        ]
        for seq, kind, payload in rows:
            await conn.execute(
                "INSERT INTO history(id,agent_id,run_id,seq,kind,payload) VALUES(%s,%s,%s,%s,%s,%s::jsonb)",
                (uuid4(), root, run, seq, kind, json.dumps(payload)),
            )

    notes_text, notes_data = await activity.search_tool(db, root, kind="final_note")
    assert "Internal milestone note" in notes_text
    assert [e["seq"] for e in cast(list[dict[str, object]], notes_data["entries"])] == [
        1
    ]

    exec_text, exec_data = await activity.search_tool(db, root, tool="execute")
    assert [e["seq"] for e in cast(list[dict[str, object]], exec_data["entries"])] == [
        3,
        2,
    ]
    assert "Entry 3 | tool_result | execute | error" in exec_text

    all_text, all_data = await activity.search_tool(db, root, query="   ")
    assert "activity_search" not in all_text
    assert [e["seq"] for e in cast(list[dict[str, object]], all_data["entries"])] == [
        3,
        2,
        1,
    ]

    read_text, read_data = await activity.read_entry(db, root, 3)
    assert "Call entry: 2 | execute(" in read_text
    assert read_data["paired_entry"] == 2 and read_data["status"] == "error"
