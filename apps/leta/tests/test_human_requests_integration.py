import asyncio
from uuid import uuid7

import pytest
from openlet.errors import AppError
from test_store_integration import active_box, active_root

from leta.domain import NewHumanRequest
from leta.human import RequestResolution

pytestmark = pytest.mark.integration


def ask(root, **changes):
    return NewHumanRequest(
        id=uuid7(),
        leta_id=root.id,
        requester_agent_id=root.id,
        kind="ask",
        title="Question",
        payload={"questions": [{"id": "q", "type": "text", "text": "Explain"}]},
        approver_user_id=root.created_by_user_id,
        outcome_message_id=uuid7(),
        **changes,
    )


def response(value, action="answer", **changes):
    return RequestResolution(
        leta_id=value.leta_id, request_id=value.id, action=action, **changes
    )


async def test_open_timeout_is_saved_once_and_closed_root_returns_existing_request(
    store,
):
    root = await active_root(store)
    value = ask(root)
    first, duplicate = await asyncio.gather(
        store.create_request(value, timeout_seconds=10),
        store.create_request(value, timeout_seconds=10),
    )
    assert first["id"] == duplicate["id"]
    assert first["expires_at"] == duplicate["expires_at"]
    with pytest.raises(AppError, match="different content"):
        await store.create_request(value, timeout_seconds=11)
    await store.begin_delete(root.id)
    assert (await store.create_request(value, timeout_seconds=10))[
        "expires_at"
    ] == first["expires_at"]
    with pytest.raises(AppError, match="not active"):
        await store.create_request(ask(root))


async def test_ask_normalized_answer_retry_and_late_timer(store):
    root = await active_root(store)
    value = ask(root)
    await store.create_request(value, timeout_seconds=30)
    # Early timers do not manufacture an expiration.
    assert (await store.resolve_request(response(value, action="expire")))[
        "status"
    ] == "pending"
    decision = response(
        value, actor_user_id=root.created_by_user_id, answers={"q": {"text": ""}}
    )
    first = await store.resolve_request(decision)
    assert first["status"] == "resolved" and first["outcome"]["answers"] == {
        "q": {"text": ""}
    }
    assert (await store.resolve_request(decision))["decision"] == first["decision"]
    assert (await store.resolve_request(response(value, action="expire")))[
        "status"
    ] == "resolved"
    with pytest.raises(AppError, match="different decision"):
        await store.resolve_request(
            response(value, action="cancel", requester_agent_id=root.id)
        )


async def test_expired_answer_and_cancel_answer_race_have_one_terminal_decision(store):
    root = await active_root(store)
    value = ask(root)
    await store.create_request(value)
    async with store.transaction() as cursor:
        await cursor.execute(
            "UPDATE hitl_requests SET expires_at=clock_timestamp()-interval '1 second' "
            "WHERE id=%s",
            (value.id,),
        )
    expired = await store.resolve_request(
        response(
            value,
            actor_user_id=root.created_by_user_id,
            answers={"q": {"text": "Too late"}},
        )
    )
    assert expired["status"] == "expired" and expired["decision"] == {
        "action": "expire"
    }
    pending = ask(root)
    await store.create_request(pending)
    results = await asyncio.gather(
        store.resolve_request(
            response(
                pending,
                actor_user_id=root.created_by_user_id,
                answers={"q": {"text": "Answer"}},
            )
        ),
        store.resolve_request(
            response(pending, action="cancel", requester_agent_id=root.id)
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(result, AppError) for result in results) == 1
    terminal = await store.get_request(root.id, pending.id)
    assert (
        terminal["status"] in {"resolved", "cancelled"}
        and terminal["outcome"] is not None
    )


async def test_resource_owner_decides_root_grant_and_outcome_is_separate(store):
    root = await active_root(store)
    box = await active_box(store, root)
    resource_owner = uuid7()
    value = NewHumanRequest(
        id=uuid7(),
        leta_id=root.id,
        requester_agent_id=box.letis[0].id,
        kind="approval",
        title="Read personal files",
        payload={"reason": "Research"},
        approver_user_id=resource_owner,
        outcome_message_id=uuid7(),
        grantee_leta_id=root.id,
        resource={
            "type": "personal_scope",
            "scope_id": str(uuid7()),
            "user_id": str(resource_owner),
        },
        requested_role="viewer",
        grant_key=uuid7(),
    )
    await store.create_request(value)
    for malformed in (
        {"type": "personal_scope", "user_id": str(resource_owner)},
        {**value.resource, "user_id": str(uuid7())},
    ):
        with pytest.raises(AppError, match="invalid personal resource"):
            await store.create_request(
                value.model_copy(update={"id": uuid7(), "resource": malformed})
            )
    with pytest.raises(AppError, match="another actor"):
        await store.resolve_request(
            response(value, action="accept", actor_user_id=root.created_by_user_id)
        )
    accepted = await store.resolve_request(
        response(value, action="accept", actor_user_id=resource_owner)
    )
    assert accepted["status"] == "resolved" and accepted["outcome"] is None
    assert accepted["grantee_leta_id"] == root.id
    # Closing an agent does not rewrite an accepted decision as cancellation.
    await store.begin_delete(root.id, box.id)
    outcome = {"granted": False, "reason": "RESOURCE_INACTIVE"}
    assert (await store.save_request_outcome(root.id, value.id, outcome))[
        "outcome"
    ] == outcome
    assert (await store.save_request_outcome(root.id, value.id, outcome))["decision"][
        "action"
    ] == "accept"
    with pytest.raises(AppError, match="different content"):
        await store.save_request_outcome(root.id, value.id, {"granted": True})


async def test_answer_deadline_is_checked_after_waiting_for_request_lock(store):
    from test_store_integration import wait_for_blocked

    root = await active_root(store)
    value = ask(root)
    await store.create_request(value)
    async with store.database.connection() as connection:
        deadline = (
            await (
                await connection.execute(
                    "UPDATE hitl_requests SET "
                    "expires_at=clock_timestamp()+interval '0.5 second' "
                    "WHERE id=%s RETURNING expires_at",
                    (value.id,),
                )
            ).fetchone()
        )[0]
        pending = None
        try:
            async with connection.transaction():
                await connection.execute(
                    "SELECT id FROM hitl_requests WHERE id=%s FOR UPDATE", (value.id,)
                )
                pid = (
                    await (
                        await connection.execute("SELECT pg_backend_pid()")
                    ).fetchone()
                )[0]
                pending = asyncio.create_task(
                    store.resolve_request(
                        response(
                            value,
                            actor_user_id=root.created_by_user_id,
                            answers={"q": {"text": "Before waiting"}},
                        )
                    )
                )
                await wait_for_blocked(store, pid)
                # Prove now() in the blocked transaction would still accept this answer.
                started_early = await (
                    await connection.execute(
                        "SELECT bool_and(xact_start < %s) FROM pg_stat_activity "
                        "WHERE %s=ANY(pg_blocking_pids(pid))",
                        (deadline, pid),
                    )
                ).fetchone()
                assert started_early[0]
                await connection.execute(
                    "SELECT pg_sleep(GREATEST(0,extract(epoch FROM "
                    "(%s-clock_timestamp()))+0.05)::double precision)",
                    (deadline,),
                )
            assert (await pending)["status"] == "expired"
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)


async def test_ask_admission_rejects_forms_that_cannot_be_answered(store):
    root = await active_root(store)
    valid = ask(root)
    text = {"id": "q", "type": "text", "text": "Explain"}
    for payload in (
        {},
        {"questions": []},
        {"questions": [text, text]},
        {"questions": [text | {"options": []}]},
        {"questions": [text | {"type": "unsupported"}]},
    ):
        malformed = valid.model_copy(update={"id": uuid7(), "payload": payload})
        with pytest.raises(AppError, match="invalid ask form"):
            await store.create_request(malformed)
    assert await store.list_requests(root.id) == []
