import asyncio
from uuid import uuid7

import pytest
from openlet.errors import AppError
from psycopg import AsyncCursor
from psycopg.errors import CheckViolation, ForeignKeyViolation
from test_domain import box_input, root_input

from leta.domain import (
    ActivityKind,
    LetiSpec,
    NewActivity,
    NewHumanRequest,
    NewMessage,
    NewSchedule,
    ReplyTo,
    RunStatus,
    SchedulePatch,
    Source,
    TimeCursor,
)
from leta.migrate import migrate, verify_schema

pytestmark = pytest.mark.integration


async def active_root(store):
    value = root_input()
    await store.create_leta(value)
    await store.activate_leta(value.id)
    return value


async def active_box(store, root, **changes):
    value = box_input(root.id, **changes)
    await store.create_box(value)
    await store.activate_box(root.id, value.id)
    return value


async def test_bootstrap_recovers_cursor_run_and_named_yield(store):
    root = await active_root(store)
    await store.receive(message(root))
    boot = await store.bootstrap_agent(root.id, root.id)
    assert (boot["latest_seq"], boot["cursor"], boot["run_id"]) == (1, 0, None)
    run_id = uuid7()
    await store.start_run(root.id, root.id, run_id)
    boot = await store.bootstrap_agent(root.id, root.id)
    assert boot["run_id"] == run_id
    with pytest.raises(AppError):
        await store.request_run_yield(uuid7(), root.id, run_id)
    assert (await store.request_run_yield(root.id, root.id, run_id)) == {
        "status": "running",
        "yield_requested": True,
    }
    await store.save_run(
        root.id,
        root.id,
        run_id,
        status=RunStatus.COMPLETED,
        inbox_cursor=1,
        result={"done": True},
    )
    boot = await store.bootstrap_agent(root.id, root.id)
    assert boot["cursor"] == 1 and boot["run_id"] is None
    assert (await store.request_run_yield(root.id, root.id, run_id)) == {
        "status": "completed",
        "yield_requested": False,
    }
    assert (await store.cancel_unfinished_run(root.id, root.id, run_id))["status"] == (
        "completed"
    )
    next_run = uuid7()
    await store.start_run(root.id, root.id, next_run)
    assert (await store.cancel_unfinished_run(root.id, root.id, next_run)) == {
        "status": "cancelled"
    }
    assert (await store.cancel_unfinished_run(root.id, root.id, next_run)) == {
        "status": "cancelled"
    }


def message(root, target=None, sender=None, **changes):
    return NewMessage.model_validate(
        {
            "id": uuid7(),
            "leta_id": root.id,
            "recipient_agent_id": target or root.id,
            "sender_agent_id": sender,
            "source": Source(type="fixture.event", id="event-1", label="A source"),
            "conversation_key": "owner",
            "content": "New work",
            **changes,
        }
    )


async def wait_for_blocked(store, pid):
    async with asyncio.timeout(1.5):
        async with store.database.connection() as connection:
            while True:
                row = await (
                    await connection.execute(
                        "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                        "WHERE %s=ANY(pg_blocking_pids(pid)))",
                        (pid,),
                    )
                ).fetchone()
                if row[0]:
                    return
                await asyncio.sleep(0)


async def test_actual_migration_reruns_without_losing_domain_or_saver(
    store, postgres_dsn
):
    root = await active_root(store)
    await migrate(postgres_dsn)
    assert (await store.get_agent(root.id, root.id))["name"] == root.name
    async with store.database.connection() as connection:
        tables = await (
            await connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='public'"
            )
        ).fetchall()
        names = {row[0] for row in tables}
        assert {
            "agents",
            "boxes",
            "box_edges",
            "messages",
            "runs",
            "activity_log",
            "hitl_requests",
            "schedules",
            "idempotency_keys",
            "checkpoints",
            "checkpoint_blobs",
            "checkpoint_writes",
            "checkpoint_migrations",
            "goose_db_version",
        } == names


async def test_readiness_checks_versions_without_running_migrations(store):
    async with store.database.connection() as connection:
        await verify_schema(connection)
        async with connection.transaction(force_rollback=True):
            await connection.execute(
                "UPDATE goose_db_version SET version_id=3 WHERE version_id=2"
            )
            with pytest.raises(AppError, match="not current"):
                await verify_schema(connection)
        async with connection.transaction(force_rollback=True):
            await connection.execute("UPDATE checkpoint_migrations SET v=100 WHERE v=0")
            with pytest.raises(AppError, match="not current"):
                await verify_schema(connection)
        await connection.execute("DROP TABLE checkpoint_migrations")
        with pytest.raises(AppError, match="not current"):
            await verify_schema(connection)
        missing = await (
            await connection.execute("SELECT to_regclass('checkpoint_migrations')")
        ).fetchone()
        assert missing[0] is None


async def test_atomic_graph_constraints_identities_and_model_validation(store):
    root = await active_root(store)
    assert (await store.create_leta(root))["id"] == root.id
    with pytest.raises(AppError, match="different content"):
        await store.create_leta(root.model_copy(update={"name": "Changed"}))
    with pytest.raises(ValueError, match="unsupported"):
        await store.create_leta(
            root_input(model={"model_id": "unknown", "reasoning_effort": None})
        )
    box = await active_box(store, root)
    assert (await store.create_box(box))["id"] == box.id
    loaded = await store.get_box_graph(root.id, box.id)
    assert {a["id"] for a in loaded["letis"]} == {a.id for a in box.letis}
    assert all(
        a["model_id"] is None and a["workspace_id"] is None for a in loaded["letis"]
    )
    assert loaded["representative_agent_id"] == box.letis[0].id
    low, high = sorted(a.id for a in box.letis)
    assert [(e["agent_low_id"], e["agent_high_id"]) for e in loaded["edges"]] == [
        (low, high)
    ]
    with pytest.raises(AppError, match="edges differ"):
        await store.create_box(box.model_copy(update={"edges": []}))
    with pytest.raises(CheckViolation):
        async with store.database.connection() as connection:
            await connection.execute(
                "UPDATE agents SET workspace_id=%s WHERE id=%s",
                (root.workspace_id, box.letis[0].id),
            )
    with pytest.raises(ForeignKeyViolation):
        async with store.database.connection() as connection:
            await connection.execute(
                "UPDATE boxes SET representative_agent_id=%s WHERE id=%s",
                (root.id, box.id),
            )
    # Failed whole-graph insertion leaves neither box nor partial children.
    collision = box_input(root.id, name="Other box")
    with pytest.raises(AppError, match="live name"):
        await store.create_box(collision)
    assert [b["id"] for b in await store.list_boxes(root.id)] == [box.id]
    first = LetiSpec(id=uuid7(), name="New child", system_prompt="Work")
    collision = box_input(
        root.id,
        name="Partial graph",
        representative=first.name,
        letis=[
            first,
            LetiSpec(id=box.letis[0].id, name="Collision", system_prompt="Work"),
        ],
        edges=[(first.name, "Collision")],
    )
    with pytest.raises(AppError, match="live name"):
        await store.create_box(collision)
    with pytest.raises(AppError, match="not found"):
        await store.get_agent(root.id, first.id)
    with pytest.raises(AppError, match="not found"):
        await store.get_box(root.id, collision.id)


async def test_metadata_and_pause_reads_do_not_load_the_box_graph(store, monkeypatch):
    root = await active_root(store)
    small = await active_box(store, root)
    agents = [
        LetiSpec(id=uuid7(), name=f"Extra {i}", system_prompt="x" * 4000)
        for i in range(12)
    ]
    large = await active_box(
        store,
        root,
        name="Larger graph",
        letis=agents,
        representative=agents[0].name,
        edges=[(agents[i - 1].name, agents[i].name) for i in range(1, len(agents))],
    )
    queries = []
    execute = AsyncCursor.execute

    async def record(cursor, query, *args, **kwargs):
        queries.append(str(query))
        return await execute(cursor, query, *args, **kwargs)

    monkeypatch.setattr(AsyncCursor, "execute", record)
    for box in (small, large):
        queries.clear()
        metadata = await store.get_box(root.id, box.id)
        assert metadata["id"] == box.id
        assert not {"letis", "edges"} & metadata.keys()
        assert len(queries) == 2  # One timeout setup and one metadata SELECT.
    queries.clear()
    snapshot = await store.set_paused(root.id, True)
    assert set(snapshot["agent_ids"]) == {
        root.id,
        *(a.id for a in small.letis + large.letis),
    }
    assert len(queries) == 4  # Setup, root lock, update and active-agent SELECT.


async def test_self_schedule_admission_locks_each_agent_once(store, monkeypatch):
    root = await active_root(store)
    box = await active_box(store, root)
    queries = []
    execute = AsyncCursor.execute

    async def record(cursor, query, *args, **kwargs):
        queries.append(str(query))
        return await execute(cursor, query, *args, **kwargs)

    monkeypatch.setattr(AsyncCursor, "execute", record)
    for agent_id in (root.id, box.letis[0].id):
        value = NewSchedule(
            id=uuid7(),
            leta_id=root.id,
            creator_agent_id=agent_id,
            target_agent_id=agent_id,
            box_id=box.id if agent_id != root.id else None,
            title="Reminder",
            content="Work",
            spec={"type": "at", "at": "2030-01-01T00:00:00Z"},
        )
        for change in (False, True):
            queries.clear()
            if change:
                await store.update_schedule(
                    root.id, value.id, agent_id, SchedulePatch(title="Changed")
                )
            else:
                await store.create_schedule(value)
            assert sum("kind='leta'" in q and "FOR " in q for q in queries) == 1


async def test_slug_collision_archive_reuse_and_history_retention(store):
    root = await active_root(store)
    box = await active_box(store, root)
    with pytest.raises(AppError, match="path already reserved"):
        await store.create_box(box_input(root.id, name="Research-team"))
    row = await store.receive(message(root, box.letis[0].id, root.id))
    await store.begin_delete(root.id, box.id)
    await store.archive(root.id, box.id)
    replacement = await active_box(store, root)
    assert replacement.id != box.id
    assert (await store.get_box(root.id, box.id))["status"] == "archived"
    assert (await store.list_inbox(root.id, box.letis[0].id))[0]["id"] == row["id"]


async def test_generic_message_retry_commit_sequence_and_pure_reads(store):
    root = await active_root(store)
    items = [message(root, content=str(i)) for i in range(3)]
    for index, item in enumerate(items, 1):
        assert (await store.receive(item))["seq"] == index
    assert (await store.receive(items[0]))["seq"] == 1
    with pytest.raises(AppError, match="different content"):
        await store.receive(items[0].model_copy(update={"content": "Changed"}))
    selected = await store.list_inbox(root.id, root.id, through=2, limit=1)
    assert selected[0]["read_at"] is None
    assert [
        r["seq"] for r in await store.list_inbox(root.id, root.id, unread_only=True)
    ] == [1, 2, 3]
    assert [
        r["seq"] for r in await store.list_inbox(root.id, root.id, after=1, through=2)
    ] == [2]
    assert (await store.get_agent(root.id, root.id))["inbox_seq"] == 3
    await store.begin_delete(root.id)
    assert (await store.receive(items[0]))[
        "seq"
    ] == 1  # A committed retry is not new input.
    with pytest.raises(AppError, match="not active"):
        await store.receive(message(root))


async def test_real_insert_failure_rolls_back_counter(store):
    root = await active_root(store)
    async with store.database.connection() as connection:
        await connection.execute(
            "ALTER TABLE messages ADD CHECK (content<>'reject-at-insert')"
        )
    with pytest.raises(CheckViolation):
        await store.receive(message(root, content="reject-at-insert"))
    assert (await store.get_agent(root.id, root.id))["inbox_seq"] == 0
    assert (await store.receive(message(root)))["seq"] == 1


async def test_saved_inbox_read_cannot_mark_foreign_input_and_rolls_back(store):
    root = await active_root(store)
    box = await active_box(store, root)
    own = message(root)
    child = message(root, target=box.letis[0].id)
    await store.receive(own)
    await store.receive(child)
    result = NewActivity(
        id=uuid7(),
        agent_id=root.id,
        kind=ActivityKind.TOOL_RESULT,
        dedup_key="read-result",
        data={},
    )
    with pytest.raises(AppError, match="another agent"):
        await store.append_activity(result, read_message_ids=[own.id, child.id])
    assert (await store.get_message(root.id, own.id))["read_at"] is None
    assert (await store.get_message(root.id, child.id))["read_at"] is None
    assert await store.list_activity(root.id, root.id) == []
    assert (await store.get_agent(root.id, root.id))["activity_seq"] == 0
    with pytest.raises(AppError, match="invalid inbox"):
        await store.append_activity(
            result.model_copy(update={"agent_id": box.letis[0].id}),
            read_message_ids=[child.id],
        )
    await store.append_activity(result, read_message_ids=[own.id])
    assert (await store.get_message(root.id, own.id))["read_at"] is not None


async def test_concurrent_identical_receive_and_history_writes_deduplicate(store):
    root = await active_root(store)
    item = message(root)
    committed = await asyncio.gather(*(store.receive(item) for _ in range(6)))
    assert {row["seq"] for row in committed} == {1}
    assert len(await store.list_inbox(root.id, root.id)) == 1
    entries = [
        NewActivity(
            id=uuid7(),
            agent_id=root.id,
            kind=ActivityKind.FINAL_NOTE,
            dedup_key=f"note-{index}",
            data={"text": str(index)},
        )
        for index in range(6)
    ]
    await asyncio.gather(*(store.append_activity(entry) for entry in entries))
    await asyncio.gather(*(store.append_activity(entries[0]) for _ in range(3)))
    saved = await store.list_activity(root.id, root.id)
    assert [row["seq"] for row in saved] == [1, 2, 3, 4, 5, 6]
    assert {row["id"] for row in saved} == {entry.id for entry in entries}


@pytest.mark.parametrize("rollback", [False, True])
async def test_later_inbox_commit_cannot_pass_held_lower_sequence(store, rollback):
    root = await active_root(store)
    later = None
    try:
        async with store.database.connection() as connection:
            async with connection.transaction() as transaction:
                await connection.execute(
                    "UPDATE agents SET inbox_seq=1 WHERE id=%s", (root.id,)
                )
                await connection.execute(
                    "INSERT INTO messages "
                    "(id,leta_id,recipient_agent_id,seq,source_type,"
                    "source_id,source_label,content) "
                    "VALUES (%s,%s,%s,1,'fixture','first','','first')",
                    (uuid7(), root.id, root.id),
                )
                pid = (
                    await (
                        await connection.execute("SELECT pg_backend_pid()")
                    ).fetchone()
                )[0]
                later = asyncio.create_task(
                    store.receive(message(root, content="second"))
                )
                await wait_for_blocked(store, pid)
                assert await store.list_inbox(root.id, root.id) == []
                assert not later.done()
                if rollback:
                    transaction.force_rollback = True
        assert (await later)["seq"] == (1 if rollback else 2)
        assert [r["seq"] for r in await store.list_inbox(root.id, root.id)] == (
            [1] if rollback else [1, 2]
        )
    finally:
        if later and not later.done():
            later.cancel()
            await asyncio.gather(later, return_exceptions=True)


async def test_routes_box_representative_peers_and_human_target(store):
    root = await active_root(store)
    box = await active_box(store, root)
    representative, peer = (a.id for a in box.letis)
    for target, sender in (
        (representative, root.id),
        (peer, representative),
        (representative, peer),
        (root.id, representative),
    ):
        assert (await store.receive(message(root, target, sender)))[
            "sender_agent_id"
        ] == sender
    response = message(
        root,
        sender=root.id,
        recipient_agent_id=None,
        recipient_user_id=root.created_by_user_id,
    )
    assert (await store.receive(response))["seq"] is None
    for invalid in (
        message(root, peer, root.id),
        message(root, root.id, peer),
        message(
            root,
            sender=peer,
            recipient_agent_id=None,
            recipient_user_id=root.created_by_user_id,
        ),
        message(
            root, sender=root.id, recipient_agent_id=None, recipient_user_id=uuid7()
        ),
    ):
        with pytest.raises(AppError, match="allowed roster"):
            await store.receive(invalid)
    disconnected = await active_box(
        store,
        root,
        name="Disconnected",
        edges=[],
        letis=[
            a.model_copy(update={"id": uuid7(), "name": f"Isolated-{i}"})
            for i, a in enumerate(box.letis)
        ],
        representative="Isolated-0",
    )
    with pytest.raises(AppError, match="allowed roster"):
        await store.receive(
            message(root, disconnected.letis[1].id, disconnected.letis[0].id)
        )
    with pytest.raises(AppError, match="allowed roster"):
        await store.receive(message(root, disconnected.letis[0].id, representative))


@pytest.mark.parametrize("conversation_key", ["owner", None])
async def test_reply_requires_original_recipient_and_current_address(
    store, conversation_key
):
    root = await active_root(store)
    box = await active_box(store, root)
    representative, peer = (a.id for a in box.letis)
    original = message(
        root,
        representative,
        root.id,
        reply_to=ReplyTo(type="agent", id=root.id),
        conversation_key=conversation_key,
    )
    await store.receive(original)
    reply = message(
        root,
        root.id,
        representative,
        in_reply_to_message_id=original.id,
        conversation_key=conversation_key,
    )
    await store.receive(reply)
    with pytest.raises(AppError, match="original address"):
        await store.receive(
            message(
                root,
                peer,
                representative,
                in_reply_to_message_id=original.id,
                conversation_key=conversation_key,
            )
        )
    with pytest.raises(AppError, match="not replyable"):
        await store.receive(
            message(
                root,
                root.id,
                representative,
                in_reply_to_message_id=original.id,
                conversation_key="another",
            )
        )


async def test_deletion_gate_blocks_late_graph_creation_and_activation(store):
    root = await active_root(store)
    box = box_input(root.id)
    pending = None
    try:
        async with store.database.connection() as connection:
            async with connection.transaction():
                await connection.execute(
                    "UPDATE agents SET status='deleting' WHERE id=%s", (root.id,)
                )
                pid = (
                    await (
                        await connection.execute("SELECT pg_backend_pid()")
                    ).fetchone()
                )[0]
                pending = asyncio.create_task(store.create_box(box))
                await wait_for_blocked(store, pid)
        with pytest.raises(AppError, match="not active"):
            await pending
        with pytest.raises(AppError, match="cannot be activated"):
            await store.activate_leta(root.id)
        assert (await store.begin_delete(root.id))["box_ids"] == []
    finally:
        if pending and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def test_requests_schedules_snapshot_and_target_rules(store):
    root = await active_root(store)
    box = await active_box(store, root)
    representative, peer = (a.id for a in box.letis)
    question = NewHumanRequest(
        id=uuid7(),
        leta_id=root.id,
        requester_agent_id=peer,
        kind="ask",
        title="Choose",
        payload={"questions": [{"id": "q", "type": "text", "text": "Explain"}]},
        approver_user_id=root.created_by_user_id,
        outcome_message_id=uuid7(),
    )
    foreign_owner = uuid7()
    approval = NewHumanRequest(
        id=uuid7(),
        leta_id=root.id,
        requester_agent_id=representative,
        kind="approval",
        title="Access",
        payload={"reason": "Read sources"},
        approver_user_id=foreign_owner,
        outcome_message_id=uuid7(),
        grantee_leta_id=root.id,
        requested_role="viewer",
        resource={
            "type": "personal_scope",
            "user_id": str(foreign_owner),
            "scope_id": str(uuid7()),
        },
        grant_key=uuid7(),
    )
    await store.create_request(question)
    assert (await store.create_request(approval))["approver_user_id"] == foreign_owner
    assert (await store.create_request(question))["id"] == question.id
    assert {row["id"] for row in await store.list_requests(root.id)} == {
        question.id,
        approval.id,
    }
    assert [
        row["id"]
        for row in await store.list_requests(
            root.id,
            requester_agent_id=peer,
        )
    ] == [question.id]
    with pytest.raises(AppError, match="creator"):
        await store.create_request(
            question.model_copy(
                update={"id": uuid7(), "approver_user_id": foreign_owner}
            )
        )
    schedule = NewSchedule(
        id=uuid7(),
        leta_id=root.id,
        creator_agent_id=root.id,
        target_agent_id=representative,
        box_id=box.id,
        title="Report",
        content="Write it",
        spec={"type": "interval", "every_seconds": 3600},
    )
    await store.create_schedule(schedule)
    assert (await store.create_schedule(schedule))["id"] == schedule.id
    assert [
        row["id"]
        for row in await store.list_schedules(
            root.id,
            target_agent_id=representative,
        )
    ] == [schedule.id]
    assert await store.list_schedules(root.id, after=schedule.id) == []
    with pytest.raises(AppError, match="representative"):
        await store.create_schedule(
            schedule.model_copy(update={"id": uuid7(), "target_agent_id": peer})
        )
    with pytest.raises(AppError, match="only itself"):
        await store.create_schedule(
            schedule.model_copy(update={"id": uuid7(), "creator_agent_id": peer})
        )
    snapshot = await store.begin_delete(root.id, box.id)
    assert set(snapshot["agent_ids"]) == {representative, peer}
    assert set(snapshot["request_ids"]) == {question.id, approval.id}
    assert snapshot["schedule_ids"] == [schedule.id]
    for operation in (
        store.create_request(question.model_copy(update={"id": uuid7()})),
        store.create_schedule(schedule.model_copy(update={"id": uuid7()})),
        store.receive(message(root, representative, root.id)),
    ):
        with pytest.raises(AppError, match="not active"):
            await operation
    with pytest.raises(AppError, match="active work"):
        await store.archive(root.id, box.id)


async def test_box_deletion_wins_against_waiting_child_request(store):
    root = await active_root(store)
    box = await active_box(store, root)
    request = NewHumanRequest(
        id=uuid7(),
        leta_id=root.id,
        requester_agent_id=box.letis[0].id,
        kind="ask",
        title="Question",
        payload={"questions": [{"id": "q", "type": "text", "text": "Explain"}]},
        approver_user_id=root.created_by_user_id,
        outcome_message_id=uuid7(),
    )
    pending = None
    try:
        async with store.database.connection() as connection:
            async with connection.transaction():
                await connection.execute(
                    "UPDATE boxes SET status='deleting' WHERE id=%s",
                    (box.id,),
                )
                pid = (
                    await (
                        await connection.execute("SELECT pg_backend_pid()")
                    ).fetchone()
                )[0]
                pending = asyncio.create_task(store.create_request(request))
                await wait_for_blocked(store, pid)
        with pytest.raises(AppError, match="not active"):
            await pending
        assert (await store.begin_delete(root.id, box.id))["request_ids"] == []
        with pytest.raises(AppError, match="cannot be activated"):
            await store.activate_box(root.id, box.id)
    finally:
        if pending and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def test_schedule_tombstone_blocks_delivery_without_retracting_inbox(store):
    root = await active_root(store)
    schedule = NewSchedule(
        id=uuid7(),
        leta_id=root.id,
        creator_agent_id=root.id,
        target_agent_id=root.id,
        title="Reminder",
        content="Remember",
        spec={"type": "at", "at": "2026-11-09T00:00:00Z"},
    )
    await store.create_schedule(schedule)
    delivered = message(root)
    await store.receive(delivered, schedule_id=schedule.id)
    async with store.database.connection() as connection:
        await connection.execute(
            "UPDATE schedules SET deleted_at=now() WHERE id=%s", (schedule.id,)
        )
    assert (await store.receive(delivered, schedule_id=schedule.id))["seq"] == 1
    with pytest.raises(AppError, match="no longer admits"):
        await store.receive(message(root), schedule_id=schedule.id)
    assert len(await store.list_inbox(root.id, root.id)) == 1


async def test_runs_public_history_and_foreign_root_boundaries(store):
    root = await active_root(store)
    foreign = await active_root(store)
    await store.receive(message(root))
    run_id = uuid7()
    await store.start_run(root.id, root.id, run_id)
    with pytest.raises(AppError, match="already exists"):
        await store.start_run(root.id, root.id, uuid7())
    item = NewActivity(
        id=uuid7(),
        agent_id=root.id,
        run_id=run_id,
        kind=ActivityKind.FINAL_NOTE,
        dedup_key="note-1",
        data={"text": "Waiting for owner"},
    )
    assert (await store.append_activity(item))["seq"] == 1
    assert (await store.append_activity(item))["seq"] == 1
    with pytest.raises(AppError, match="different content"):
        await store.append_activity(
            item.model_copy(update={"data": {"text": "Changed"}})
        )
    with pytest.raises(AppError, match="invalid run inbox progress"):
        await store.save_run(
            root.id, root.id, run_id, status=RunStatus.COMPLETED, inbox_cursor=2
        )
    await store.save_run(
        root.id,
        root.id,
        run_id,
        status=RunStatus.PAUSED,
        inbox_cursor=1,
        continuation={"resume": True},
    )
    result = await store.save_run(
        root.id,
        root.id,
        run_id,
        status=RunStatus.COMPLETED,
        inbox_cursor=1,
        result={"note": "Done"},
        checkpoint_id="checkpoint-1",
    )
    assert result["finished_at"] is not None
    assert (
        await store.save_run(
            root.id,
            root.id,
            run_id,
            status=RunStatus.COMPLETED,
            inbox_cursor=1,
            result={"note": "Done"},
            checkpoint_id="checkpoint-1",
        )
    )["id"] == run_id
    assert (await store.list_activity(root.id, root.id))[0]["data"] == item.data
    assert await store.list_activity(foreign.id, root.id) == []
    assert await store.list_runs(foreign.id, root.id) == []
    assert await store.list_inbox(foreign.id, root.id) == []
    with pytest.raises(AppError, match="not found"):
        await store.get_agent(foreign.id, root.id)
    with pytest.raises(AppError, match="not found"):
        await store.receive(message(foreign, root.id))
    await store.begin_delete(root.id)
    await store.archive(root.id)
    assert (await store.list_activity(root.id, root.id))[0]["id"] == item.id


async def test_owner_read_pages_preserve_order_and_actor_scope(store):
    root = await active_root(store)
    for index in range(3):
        await store.receive(
            message(
                root,
                content=str(index),
                source={
                    "type": "owner",
                    "id": str(root.created_by_user_id),
                    "label": "Owner",
                },
            )
        )
    await store.receive(message(root, content="Internal"))
    first = await store.api_messages(root.id, root.created_by_user_id, limit=1)
    rest = await store.api_messages(
        root.id,
        root.created_by_user_id,
        after=TimeCursor(at=first[0]["created_at"], id=first[0]["id"]),
        limit=2,
    )
    assert [row["content"] for row in first + rest] == ["0", "1", "2"]
    assert await store.api_messages(root.id, uuid7()) == []
    sibling = root_input(
        created_by_user_id=root.created_by_user_id, workspace_id=root.workspace_id
    )
    await store.create_leta(sibling)
    await active_root(store)
    assert [
        r["id"]
        for r in await store.api_roots(
            root.created_by_user_id, workspace_id=root.workspace_id, limit=1
        )
    ] == [root.id]
    assert [
        r["id"]
        for r in await store.api_roots(
            root.created_by_user_id, workspace_id=root.workspace_id, after=root.id
        )
    ] == [sibling.id]
    assert await store.api_roots(root.created_by_user_id, after=sibling.id) == []
    assert [
        r["id"] for r in await store.api_roots(root.created_by_user_id, status="active")
    ] == [root.id]
    assert await store.api_roots(root.created_by_user_id, workspace_id=uuid7()) == []
    for limit in (0, 201):
        with pytest.raises(AppError, match="limit"):
            await store.list_boxes(root.id, limit=limit)
