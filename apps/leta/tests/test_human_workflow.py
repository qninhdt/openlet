import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from openlet.errors import AppError
from openlet.rpc import Actor
from openlet_api.workspace.v1 import workspace_pb2 as pb
from temporalio import activity
from test_agent_workflow import retain_history
from test_human_requests_integration import ask, response
from test_lifecycle_integration import unused_runtime
from test_store_integration import active_box, active_root

from leta.domain import NewHumanRequest
from leta.temporal.bridges import (
    open_human_request,
    resolve_human_request,
    settle_hitl,
)
from leta.temporal.human import HumanRequestWorkflow
from leta.temporal.human_activities import HumanActivities
from leta.temporal.human_types import OpenHumanRequest, SettleHumanRequest
from leta.worker import agent_workers

pytestmark = pytest.mark.integration


def opening(value, timeout_seconds=None):
    return OpenHumanRequest(
        leta_id=value.leta_id,
        request_id=value.id,
        creation=value,
        timeout_seconds=timeout_seconds,
    )


def handle(client, request):
    return client.get_workflow_handle_for(
        HumanRequestWorkflow.run, f"human-request/{request.id}"
    )


async def test_child_question_is_idle_until_answer_then_delivered_to_exact_child(
    store, temporal_environment
):
    root = await active_root(store)
    box = await active_box(store, root)
    await store.set_paused(root.id, True)
    request = ask(root).model_copy(update={"requester_agent_id": box.letis[0].id})
    client = temporal_environment.client
    human = HumanActivities(store, SimpleNamespace(), client)
    async with agent_workers(client, store, unused_runtime, human=human):
        async with asyncio.timeout(20):
            state = await open_human_request(client, store, opening(request))
            assert state.status == "pending" and state.delivery is None
            # Pending human requests have no Activity holding a worker slot.
            assert not (
                await handle(client, request).describe()
            ).raw_description.pending_activities
            with pytest.raises(AppError, match="another actor"):
                await resolve_human_request(
                    client,
                    store,
                    response(
                        request, actor_user_id=uuid7(), answers={"q": {"text": "x"}}
                    ),
                )
            answer = response(
                request,
                actor_user_id=root.created_by_user_id,
                answers={"q": {"text": "Proceed"}},
            )
            assert (
                await resolve_human_request(client, store, answer)
            ).status == "resolved"
            result = await handle(client, request).result()
            await retain_history(handle(client, request), "human-answer")
            assert result.outcome["answers"] == {"q": {"text": "Proceed"}}
            saved = await store.get_message(root.id, request.outcome_message_id)
            assert saved["recipient_agent_id"] == box.letis[0].id
            assert saved["reply_to"] is None
            assert (await store.bootstrap_agent(root.id, root.id))["latest_seq"] == 0
            # Completed-request retries neither reopen nor redeliver.
            assert (
                await open_human_request(client, store, opening(request))
            ).status == "resolved"
            assert (
                await resolve_human_request(client, store, answer)
            ).status == "resolved"
            assert (await store.bootstrap_agent(root.id, box.letis[0].id))[
                "latest_seq"
            ] == 1
            with pytest.raises(AppError, match="different content"):
                await open_human_request(
                    client,
                    store,
                    opening(request.model_copy(update={"title": "Changed"})),
                )


async def test_pending_settlement_cancels_and_skips_deleted_recipient(
    store, temporal_environment
):
    root = await active_root(store)
    box = await active_box(store, root)
    request = ask(root).model_copy(update={"requester_agent_id": box.letis[0].id})
    client = temporal_environment.client
    human = HumanActivities(store, SimpleNamespace(), client)
    async with agent_workers(client, store, unused_runtime, human=human):
        async with asyncio.timeout(20):
            await open_human_request(client, store, opening(request))
            await store.begin_delete(root.id, box.id)
            settlement = SettleHumanRequest(
                leta_id=root.id, request_id=request.id, reason="box_deleted"
            )
            assert (await settle_hitl(client, settlement)).status == "cancelled"
            await handle(client, request).result()
            await retain_history(handle(client, request), "human-cancel")
            assert (await settle_hitl(client, settlement)).status == "cancelled"
            with pytest.raises(AppError, match="another Leta"):
                await settle_hitl(
                    client, settlement.model_copy(update={"leta_id": uuid7()})
                )
            with pytest.raises(AppError, match="resource not found"):
                await store.get_message(root.id, request.outcome_message_id)
            await store.archive(root.id, box.id)
            assert (await store.get_box(root.id, box.id))["status"] == "archived"


async def test_real_deadline_expires_without_active_agent(store, temporal_environment):
    root = await active_root(store)
    await store.set_paused(root.id, True)
    request = ask(root)
    client = temporal_environment.client
    human = HumanActivities(store, SimpleNamespace(), client)
    with temporal_environment.auto_time_skipping_disabled():
        async with agent_workers(client, store, unused_runtime, human=human):
            async with asyncio.timeout(15):
                opened = await open_human_request(client, store, opening(request, 1))
                assert opened.status == "pending" and opened.expires_at is not None
                assert (await handle(client, request).result()).status == "expired"
                await retain_history(handle(client, request), "human-expiry")
                saved = await store.get_message(root.id, request.outcome_message_id)
                assert saved["data"]["outcome"]["action"] == "expire"


async def test_accepted_grant_ack_is_independent_and_settlement_waits_for_actual_grant(
    store, temporal_environment
):
    root = await active_root(store)
    box = await active_box(store, root)
    await store.set_paused(root.id, True)
    owner, scope_id = uuid7(), uuid7()
    request = NewHumanRequest(
        id=uuid7(),
        leta_id=root.id,
        requester_agent_id=box.letis[0].id,
        kind="approval",
        title="Read sources",
        payload={"reason": "Research"},
        approver_user_id=owner,
        outcome_message_id=uuid7(),
        grantee_leta_id=root.id,
        requested_role="viewer",
        resource={
            "type": "personal_scope",
            "user_id": str(owner),
            "scope_id": str(scope_id),
        },
    )
    entered, release = asyncio.Event(), asyncio.Event()

    async def change_scope_access(value, *, actor):
        assert actor == Actor("user", owner)
        assert value.personal_owner_user_id == str(owner)
        assert value.grantee_kind == "leta" and value.grantee_id == str(root.id)
        saved = await store.get_request(root.id, request.id)
        assert value.idempotency_key == str(saved["grant_key"])
        assert saved["grant_key"].version == 7
        entered.set()
        await release.wait()
        return pb.ChangeScopeAccessResponse(rights=pb.ScopeRights(read_content=True))

    scopes = SimpleNamespace(
        resolve_personal_scope=AsyncMock(
            return_value=pb.ResolvePersonalScopeResponse(
                workspace_id=str(root.workspace_id),
                scope_id=str(scope_id),
                owner_user_id=str(owner),
            )
        ),
        list_accessible_scopes=AsyncMock(
            return_value=pb.ListAccessibleScopesResponse()
        ),
        change_scope_access=AsyncMock(side_effect=change_scope_access),
    )
    client = temporal_environment.client
    human = HumanActivities(store, scopes, client)
    async with agent_workers(client, store, unused_runtime, human=human):
        async with asyncio.timeout(25):
            await open_human_request(client, store, opening(request))
            first_key = (await store.get_request(root.id, request.id))["grant_key"]
            await open_human_request(client, store, opening(request))
            assert (await store.get_request(root.id, request.id))[
                "grant_key"
            ] == first_key
            accepted = await resolve_human_request(
                client, store, response(request, action="accept", actor_user_id=owner)
            )
            assert accepted.needs_grant and accepted.outcome is None
            await entered.wait()
            # Accept returned while the remote grant is still outstanding.
            settlement = asyncio.create_task(
                settle_hitl(
                    client,
                    SettleHumanRequest(
                        leta_id=root.id,
                        request_id=request.id,
                        reason="box_deleted",
                    ),
                )
            )
            try:
                # Duplicate decisions acknowledge before the remote call finishes.
                assert (
                    await resolve_human_request(
                        client,
                        store,
                        response(request, action="accept", actor_user_id=owner),
                    )
                ).needs_grant
                assert not settlement.done()
                release.set()
                result = await settlement
                await handle(client, request).result()
                await retain_history(handle(client, request), "human-approval")
                assert result.status == "resolved" and result.outcome["granted"] is True
                assert result.outcome["mount_path"] == f"/users/{owner}"
                saved = await store.get_message(root.id, request.outcome_message_id)
                assert saved["recipient_agent_id"] == box.letis[0].id
                scopes.change_scope_access.assert_awaited_once()
            finally:
                release.set()
                if not settlement.done():
                    settlement.cancel()
                await asyncio.gather(settlement, return_exceptions=True)


async def test_ask_tool_checkpoint_retry_and_unrelated_run_do_not_wait_for_human(
    store,
    postgres_dsn,
    temporal_environment,
    monkeypatch,
):
    from langchain_core.messages import AIMessage, ToolMessage
    from test_runtime import RecordingModel, call, harness
    from test_store_integration import message

    from leta.domain import ActivityKind
    from leta.temporal.types import RunInput

    model = RecordingModel(
        responses=[
            call(
                "ask_user",
                title="Need a decision",
                questions=[
                    {"id": "q", "type": "text", "text": "Which source?"},
                ],
            ),
            AIMessage(content="Waiting for a human answer"),
            AIMessage(content="Handled the unrelated input"),
        ]
    )
    client = temporal_environment.client
    runner, run, root, _ = await harness(store, postgres_dsn, model, client=client)
    await store.receive(message(root))
    human = HumanActivities(store, SimpleNamespace(), client)
    original, lost = store.append_activity, False

    async def crash(value):
        nonlocal lost
        if value.kind == ActivityKind.TOOL_RESULT and not lost:
            lost = True
            raise RuntimeError("lost after request opened before result checkpoint")
        return await original(value)

    monkeypatch.setattr(store, "append_activity", crash)
    async with agent_workers(client, store, runner.run_agent, human=human):
        async with asyncio.timeout(25):
            with pytest.raises(RuntimeError, match="request opened"):
                await runner.execute(run)
            assert (await runner.execute(run)).outcome == "completed"
            requests = await store.list_requests(root.id)
            assert len(requests) == 1 and requests[0]["status"] == "pending"
            first_key = requests[0]["id"]
            results = [m for m in model.calls[-1] if isinstance(m, ToolMessage)]
            assert len(results) == 1 and '"pending"' in results[0].content
            await store.receive(message(root, content="Unrelated work"))
            second = RunInput(leta_id=root.id, agent_id=root.id, run_id=uuid7())
            await store.start_run(**second.model_dump())
            assert (await runner.execute(second)).outcome == "completed"
            assert len(model.calls) == 3
            assert (await store.get_request(root.id, first_key))["status"] == "pending"
            await store.set_paused(root.id, True)
            await settle_hitl(
                client,
                SettleHumanRequest(
                    leta_id=root.id,
                    request_id=first_key,
                    reason="test_complete",
                ),
            )


async def test_committed_decision_outcome_and_inbox_retry_after_lost_completion(
    store,
    temporal_environment,
):
    from leta.human import RequestResolution
    from leta.temporal.human_types import HumanRequestOutcome, HumanRequestState
    from leta.temporal.types import AgentInput

    root = await active_root(store)
    await store.set_paused(root.id, True)
    owner, scope_id = uuid7(), uuid7()
    request = NewHumanRequest(
        id=uuid7(),
        leta_id=root.id,
        requester_agent_id=root.id,
        kind="approval",
        title="Read",
        payload={"reason": "Research"},
        approver_user_id=owner,
        outcome_message_id=uuid7(),
        grantee_leta_id=root.id,
        requested_role="viewer",
        resource={
            "type": "personal_scope",
            "user_id": str(owner),
            "scope_id": str(scope_id),
        },
    )
    attempts = {"decision": 0, "outcome": 0, "delivery": 0}

    def lose_once(boundary):
        attempts[boundary] += 1
        if attempts[boundary] == 1:
            raise RuntimeError("lost completion after " + boundary)

    class LoseCompletion(HumanActivities):
        @activity.defn
        async def resolve_hitl_request(
            self, value: RequestResolution
        ) -> HumanRequestState:
            result = await super().resolve_hitl_request(value)
            lose_once("decision")
            return result

        @activity.defn
        async def save_hitl_outcome(
            self, value: HumanRequestOutcome
        ) -> HumanRequestState:
            result = await super().save_hitl_outcome(value)
            lose_once("outcome")
            return result

        @activity.defn
        async def deliver_agent_input(self, value: AgentInput) -> str:
            result = await super().deliver_agent_input(value)
            lose_once("delivery")
            return result

    scopes = SimpleNamespace(
        resolve_personal_scope=AsyncMock(
            return_value=pb.ResolvePersonalScopeResponse(scope_id=str(scope_id))
        ),
        list_accessible_scopes=AsyncMock(
            return_value=pb.ListAccessibleScopesResponse()
        ),
        change_scope_access=AsyncMock(
            return_value=pb.ChangeScopeAccessResponse(
                rights=pb.ScopeRights(read_content=True)
            )
        ),
    )
    client = temporal_environment.client
    human = LoseCompletion(store, scopes, client)
    async with (
        agent_workers(client, store, unused_runtime, human=human),
        asyncio.timeout(25),
    ):
        await open_human_request(client, store, opening(request))
        await resolve_human_request(
            client, store, response(request, action="accept", actor_user_id=owner)
        )
        result = await handle(client, request).result()
        assert result.outcome["granted"] is True
        assert attempts == {"decision": 2, "outcome": 2, "delivery": 2}
        scopes.change_scope_access.assert_awaited_once()
        assert (await store.bootstrap_agent(root.id, root.id))["latest_seq"] == 1
        assert len(await store.list_requests(root.id)) == 1


async def test_sql_decision_recovers_after_actual_worker_sigkill(
    store,
    persistent_temporal,
    postgres_dsn,
    catalog_data,
):
    root = await active_root(store)
    await store.set_paused(root.id, True)
    request = ask(root)
    client = persistent_temporal
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("human_crash_worker.py")),
        env={
            **os.environ,
            "OPENLET_OWNED_HUMAN_CRASH": json.dumps(
                {
                    "address": client.service_client.config.target_host,
                    "namespace": client.namespace,
                    "database_url": postgres_dsn,
                    "models": catalog_data,
                }
            ),
        },
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    decision = None
    try:
        async with asyncio.timeout(20):
            await open_human_request(client, store, opening(request))
            answer = response(
                request,
                actor_user_id=root.created_by_user_id,
                answers={"q": {"text": "Continue"}},
            )
            decision = asyncio.create_task(resolve_human_request(client, store, answer))
            _, errors = await process.communicate()
            assert process.returncode == -signal.SIGKILL, errors.decode(
                errors="replace"
            )
            row = await store.get_request(root.id, request.id)
            assert row["status"] == "resolved" and row["outcome"]["answers"] == {
                "q": {"text": "Continue"},
            }
            assert not decision.done()
            assert await store.list_inbox(root.id, root.id) == []
        human = HumanActivities(store, SimpleNamespace(), client)
        async with (
            agent_workers(client, store, unused_runtime, human=human),
            asyncio.timeout(30),
        ):
            assert (await decision).status == "resolved"
            assert (await handle(client, request).result()).outcome == row["outcome"]
            assert len(await store.list_requests(root.id)) == 1
            assert (await store.bootstrap_agent(root.id, root.id))["latest_seq"] == 1
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
        if decision is not None and not decision.done():
            decision.cancel()
            await asyncio.gather(decision, return_exceptions=True)
