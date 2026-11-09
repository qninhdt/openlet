from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid7

import pytest
from authzed.api.v1 import CheckBulkPermissionsResponse, CheckPermissionResponse
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from test_domain import root_input
from test_human_requests_integration import ask
from test_lifecycle_integration import RemoteServices, unused_runtime
from test_store_integration import active_box, active_root

from leta.api import create_app
from leta.domain import NewActivity, NewHumanRequest, NewMessage
from leta.http.common import Context, api
from leta.temporal.bridges import open_human_request
from leta.temporal.human_activities import HumanActivities
from leta.temporal.human_types import OpenHumanRequest
from leta.temporal.lifecycle_activities import LifecycleActivities
from leta.temporal.schedule_activities import ScheduleActivities
from leta.worker import agent_workers

pytestmark = pytest.mark.integration


class Authorization:
    """External authorization boundary; exercise the real Python check adapter."""

    member = True

    async def CheckPermission(self, request, **kwargs):
        assert request.consistency.fully_consistent
        return CheckPermissionResponse(permissionship=2 if self.member else 1)

    async def CheckBulkPermissions(self, request, **kwargs):
        assert request.consistency.fully_consistent and len(request.items) <= 100
        response = CheckBulkPermissionsResponse()
        for item in request.items:
            pair = response.pairs.add(request=item)
            pair.item.permissionship = 2 if self.member else 1
        return response


@pytest.fixture
async def http(store, settings, persistent_temporal):
    authz = Authorization()
    scopes = SimpleNamespace()
    app = create_app(settings)
    app.state.settings = settings

    def context(request: Request):
        return Context(
            request,
            store,
            scopes,
            persistent_temporal,
            authz,
            request.state.principal.actor,
            settings.models,
        )

    app.dependency_overrides[api] = context
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://leta"
    ) as client:
        yield SimpleNamespace(
            client=client,
            authz=authz,
            scopes=scopes,
            temporal=persistent_temporal,
            store=store,
        )


def headers(settings, user, key=None):
    return {
        "x-gateway-token": settings.gateway_token,
        "x-openlet-user-id": str(user),
        "x-clerk-sub": "fixture-human",
    } | ({"idempotency-key": str(key)} if key else {})


async def test_owner_read_models_scoping_cursors_and_public_history(http, settings):
    store, client = http.store, http.client
    root, other = await active_root(store), await active_root(store)
    box, foreign_box = await active_box(store, root), await active_box(store, other)
    h = headers(settings, root.created_by_user_id)
    base = f"/v1/letas/{root.id}"
    owner_input = NewMessage(
        id=uuid7(),
        leta_id=root.id,
        recipient_agent_id=root.id,
        source={"type": "owner", "id": str(root.created_by_user_id), "label": "owner"},
        reply_to={"type": "user", "id": root.created_by_user_id},
        conversation_key=f"user:{root.created_by_user_id}",
        content="Original owner text",
    )
    await store.receive(owner_input)
    outgoing = NewMessage(
        id=uuid7(),
        leta_id=root.id,
        sender_agent_id=root.id,
        recipient_user_id=root.created_by_user_id,
        source={"type": "agent", "id": str(root.id), "label": "Leta"},
        content="Actual reply",
    )
    await store.receive(outgoing)
    internal = NewMessage(
        id=uuid7(),
        leta_id=root.id,
        sender_agent_id=root.id,
        recipient_agent_id=box.letis[0].id,
        source={"type": "agent", "id": str(root.id), "label": "Leta"},
        reply_to={"type": "box", "id": box.id},
        content="Internal work",
    )
    await store.receive(internal)
    run_id = uuid7()
    await store.start_run(root.id, root.id, run_id)
    data = [
        (
            "inbox_input",
            {
                "mode": "digest",
                "runtime_message_id": "input",
                "cursor_from": 0,
                "cursor_to": 1,
                "groups": [
                    {
                        "source": owner_input.source.model_dump(mode="json"),
                        "conversation_id": owner_input.conversation_key,
                        "reply_to": owner_input.reply_to.model_dump(mode="json"),
                        "new_count": 1,
                        "message_ids": [str(owner_input.id)],
                        "preview": "Original owner text",
                    }
                ],
            },
        ),
        (
            "tool_call",
            {
                "name": "send_message",
                "args": {"to": "owner", "content": "Actual reply"},
            },
        ),
        (
            "tool_result",
            {
                "tool_call_id": "tool-1",
                "name": "send_message",
                "result": [{"type": "text", "text": "sent"}],
                "outcome": "success",
                "message": {"replay_only": "hidden"},
            },
        ),
        (
            "final_note",
            {
                "llm_message_id": "note",
                "content": [{"type": "text", "text": "Waiting"}],
            },
        ),
        (
            "compaction",
            {
                "summary_message_id": "summary",
                "summary": "Exact persisted summary",
                "replaces_through_message_id": "note",
                "retained_message_ids": [],
            },
        ),
    ]
    entries = []
    for kind, payload in data:
        entries.append(
            await store.append_activity(
                NewActivity(
                    id=uuid7(),
                    agent_id=root.id,
                    run_id=run_id,
                    kind=kind,
                    llm_message_id="call" if kind == "tool_call" else None,
                    tool_call_id="tool-1"
                    if kind in {"tool_call", "tool_result"}
                    else None,
                    dedup_key=kind,
                    data=payload,
                )
            )
        )
    response = await client.get(base + "/history", headers=h)
    assert response.status_code == 200, response.text
    transcript = response.json()["items"]
    assert [entry["kind"] for entry in transcript] == [item[0] for item in data]
    assert transcript[-1]["data"]["summary"] == "Exact persisted summary"
    assert "replay_only" not in response.text
    assert response.headers["cache-control"] == "no-store"
    chat = (await client.get(base + "/messages", headers=h)).json()["items"]
    assert [entry["content"] for entry in chat] == [
        "Original owner text",
        "Actual reply",
    ]
    assert (
        await client.get(base + f"/messages/{internal.id}", headers=h)
    ).status_code == 404
    inbox = await client.get(base + "/inbox", headers=h)
    assert len(inbox.json()["items"]) == 1
    assert (await store.get_message(root.id, owner_input.id))["read_at"] is None
    first = (await client.get(base + "/history?limit=2", headers=h)).json()
    second = await client.get(
        base + "/history",
        params={"cursor": first["next_cursor"], "limit": 2},
        headers=h,
    )
    assert second.json()["items"][0]["id"] == str(entries[2]["id"])
    mismatch = await client.get(
        base + "/history",
        params={"agent_id": str(box.letis[0].id), "cursor": first["next_cursor"]},
        headers=h,
    )
    assert mismatch.status_code == 400
    malformed = await client.get(base + "/history?cursor=!", headers=h)
    assert malformed.status_code == 400
    for path in [
        f"/v1/letas/{other.id}",
        base + f"/boxes/{foreign_box.id}",
        base + f"/inbox?agent_id={foreign_box.letis[0].id}",
        base + f"/history?agent_id={foreign_box.letis[0].id}",
        f"/v1/letas/{other.id}/history/{entries[0]['id']}",
        f"/v1/letas/{other.id}/runs/{run_id}",
    ]:
        assert (await client.get(path, headers=h)).status_code == 404, path
    run = (await client.get(base + f"/runs/{run_id}", headers=h)).json()
    assert run["events_url"] == base + "/events" and "continuation" not in run
    roster = await client.get(base + "/agents?limit=100", headers=h)
    assert roster.status_code == 200
    assert len(roster.json()["items"]) == 3
    http.authz.member = False
    assert (await client.get(base, headers=h)).status_code == 403
    assert (await client.get("/v1/letas", headers=h)).json()["items"] == []
    assert (await client.get("/v1/leta-models")).status_code == 401


async def test_message_pending_then_retry_is_one_admitted_input(http, settings):
    root = await active_root(http.store)
    await http.store.set_paused(root.id, True)
    base = f"/v1/letas/{root.id}/messages"
    h = headers(settings, root.created_by_user_id)
    body = {"id": str(uuid7()), "content": "Deliver after the worker returns"}
    pending = await http.client.post(base, json=body, headers=h)
    assert pending.status_code == 202, pending.text
    assert pending.json()["resource_id"] == body["id"]
    assert (
        await http.client.get(base + "/" + body["id"], headers=h)
    ).status_code == 404
    async with agent_workers(http.temporal, http.store, unused_runtime):
        response = await http.client.post(base, json=body, headers=h)
        assert response.status_code == 201, response.text
        assert response.json()["seq"] == 1
        retry = await http.client.post(base, json=body, headers=h)
        assert retry.json()["id"] == body["id"] and retry.json()["seq"] == 1
        conflict = await http.client.post(
            base, json=body | {"content": "Changed"}, headers=h
        )
        assert conflict.status_code == 409
        assert len((await http.client.get(base, headers=h)).json()["items"]) == 1
    invalid = await http.client.post(
        base, json=body | {"sender_agent_id": str(root.id)}, headers=h
    )
    assert invalid.status_code == 400 and body["content"] not in invalid.text


async def test_lifecycle_box_and_calendar_commands_use_stable_keys(http, settings):
    root = root_input()
    services = RemoteServices(root)

    async def ensure(workspace_id, leta_id, scope_id, key, **kwargs):
        services.root = SimpleNamespace(
            **await http.store.get_agent(UUID(leta_id), UUID(leta_id))
        )
        assert scope_id == key
        assert UUID(scope_id).version == 7

    services.scopes.ensure_leta_home_access.side_effect = ensure
    lifecycle = LifecycleActivities(
        http.store, services.scopes, services.native, services.graph, http.temporal
    )
    schedules = ScheduleActivities(http.store, http.temporal)

    async def get_workspace(*args, **kwargs):
        return SimpleNamespace(id=str(root.workspace_id))

    http.scopes.get_workspace = get_workspace
    key = uuid7()
    h = headers(settings, root.created_by_user_id, key)
    body = {
        "workspace_id": str(root.workspace_id),
        "name": "Leta",
        "description": "",
        "system_prompt": "Assist owner",
        "model_id": "provider/model",
        "reasoning_effort": None,
    }
    async with agent_workers(
        http.temporal, http.store, unused_runtime, lifecycle, schedules=schedules
    ):
        response = await http.client.post("/v1/letas", json=body, headers=h)
        assert response.status_code == 201, response.text
        leta_id = response.json()["id"]
        base = f"/v1/letas/{leta_id}"
        retry = await http.client.post("/v1/letas", json=body, headers=h)
        assert retry.json()["id"] == leta_id
        assert (
            await http.client.post(
                "/v1/letas", json=body | {"name": "Changed"}, headers=h
            )
        ).status_code == 409
        patchh = headers(settings, root.created_by_user_id, uuid7())
        assert (await http.client.post(base + "/pause", headers=patchh)).json()[
            "paused"
        ]
        assert (
            await http.client.post(
                base + "/resume",
                headers=headers(settings, root.created_by_user_id, uuid7()),
            )
        ).json()["paused"] is False
        # A completed HTTP key must not depend on a Temporal run's Update registry.
        from unittest.mock import patch

        with patch(
            "leta.http.agents.change_leta",
            side_effect=AssertionError("replayed completed key"),
        ):
            assert (await http.client.post(base + "/pause", headers=patchh)).json()[
                "paused"
            ] is False
        assert (
            await http.client.post(
                base + "/pause",
                headers=headers(settings, root.created_by_user_id, uuid7()),
            )
        ).json()["paused"] is True
        boxbody = {
            "name": "Team",
            "description": "",
            "letis": [
                {"name": "Researcher", "description": "", "system_prompt": "Research"},
                {"name": "Writer", "description": "", "system_prompt": "Write"},
            ],
            "representative": "Researcher",
            "edges": [["Researcher", "Writer"]],
        }
        bh = headers(settings, root.created_by_user_id, uuid7())
        box = await http.client.post(base + "/boxes", json=boxbody, headers=bh)
        assert box.status_code == 201, box.text
        assert len(box.json()["letis"]) == 2 and len(box.json()["edges"]) == 1
        assert all(child["paused"] for child in box.json()["letis"])
        child_id = box.json()["letis"][0]["id"]
        edit = await http.client.patch(
            base + f"/agents/{child_id}",
            json={"model_id": None, "reasoning_effort": None},
            headers=headers(settings, root.created_by_user_id, uuid7()),
        )
        assert edit.status_code == 200 and edit.json()["model_id"] is None
        assert edit.json()["paused"]
        assert (
            await http.client.patch(
                base,
                json={"model_id": None},
                headers=headers(settings, root.created_by_user_id, uuid7()),
            )
        ).status_code == 400
        assert (
            await http.client.patch(base, json={}, headers=patchh)
        ).status_code == 400
        sh = headers(settings, root.created_by_user_id, uuid7())
        schedule = await http.client.post(
            base + "/schedules",
            json={
                "title": "Reminder",
                "content": "Remind owner",
                "spec": {"type": "at", "after_seconds": 3600},
            },
            headers=sh,
        )
        assert schedule.status_code == 201, schedule.text
        schedule_id = schedule.json()["id"]
        assert schedule.json()["spec"]["at"]
        again = await http.client.post(
            base + "/schedules",
            json={
                "title": "Reminder",
                "content": "Remind owner",
                "spec": {"type": "at", "after_seconds": 3600},
            },
            headers=sh,
        )
        assert again.json()["spec"] == schedule.json()["spec"]
        now = datetime.now(UTC)
        calendar = await http.client.get(
            base + "/schedule-occurrences",
            params={
                "start": now.isoformat(),
                "end": (now + timedelta(hours=2)).isoformat(),
            },
            headers=h,
        )
        assert calendar.status_code == 200, calendar.text
        assert (
            len(calendar.json()) == 1
            and calendar.json()[0]["schedule_id"] == schedule_id
        )
        deleted = await http.client.delete(
            base + f"/schedules/{schedule_id}",
            headers=headers(settings, root.created_by_user_id, uuid7()),
        )
        assert deleted.status_code == 200 and deleted.json()["deleted_at"]
        box_id = box.json()["id"]
        deleted = await http.client.delete(
            base + f"/boxes/{box_id}",
            headers=headers(settings, root.created_by_user_id, uuid7()),
        )
        assert deleted.status_code == 200 and deleted.json()["status"] == "archived"
        # The old create key returns the archive; it never recreates agents/home.
        old = await http.client.post(base + "/boxes", json=boxbody, headers=bh)
        assert old.json()["id"] == box_id and old.json()["status"] == "archived"
        removed = await http.client.delete(
            base, headers=headers(settings, root.created_by_user_id, uuid7())
        )
        assert removed.status_code == 200 and removed.json()["status"] == "archived"
        assert (await http.client.get(base, headers=h)).status_code == 200
        old = await http.client.post("/v1/letas", json=body, headers=h)
        assert old.json()["id"] == leta_id and old.json()["status"] == "archived"


async def test_human_cards_only_resource_owner_responds_and_ask_resumes_child(
    http, settings
):
    from unittest.mock import AsyncMock

    from openlet.rpc import Actor
    from openlet_api.workspace.v1 import workspace_pb2 as pb

    root = await active_root(http.store)
    box = await active_box(http.store, root)
    await http.store.set_paused(root.id, True)
    resource_owner, scope_id = uuid7(), uuid7()
    approval = NewHumanRequest(
        id=uuid7(),
        leta_id=root.id,
        requester_agent_id=box.letis[0].id,
        kind="approval",
        title="Read personal sources",
        payload={"reason": "Research"},
        approver_user_id=resource_owner,
        outcome_message_id=uuid7(),
        grantee_leta_id=root.id,
        resource={
            "type": "personal_scope",
            "user_id": str(resource_owner),
            "scope_id": str(scope_id),
        },
        requested_role="viewer",
    )

    async def grant(command, *, actor):
        assert actor == Actor("user", resource_owner)
        assert command.grantee_kind == "leta" and command.grantee_id == str(root.id)
        return pb.ChangeScopeAccessResponse(rights=pb.ScopeRights(read_content=True))

    scopes = SimpleNamespace(
        resolve_personal_scope=AsyncMock(
            return_value=pb.ResolvePersonalScopeResponse(scope_id=str(scope_id))
        ),
        list_accessible_scopes=AsyncMock(
            return_value=pb.ListAccessibleScopesResponse()
        ),
        change_scope_access=AsyncMock(side_effect=grant),
    )
    human = HumanActivities(http.store, scopes, http.temporal)
    ownerh = headers(settings, root.created_by_user_id)
    resourceh = headers(settings, resource_owner)
    base = f"/v1/human-requests/{approval.id}"
    async with agent_workers(http.temporal, http.store, unused_runtime, human=human):
        await open_human_request(
            http.temporal,
            http.store,
            OpenHumanRequest(
                leta_id=root.id,
                request_id=approval.id,
                creation=approval,
                timeout_seconds=60,
            ),
        )
        assert (await http.client.get(base, headers=ownerh)).status_code == 404
        assert (
            await http.client.post(
                base + "/response", json={"action": "accept"}, headers=ownerh
            )
        ).status_code == 404
        card = await http.client.get(base, headers=resourceh)
        assert card.status_code == 200, card.text
        assert card.json()["requester_name"] == box.letis[0].name
        assert card.json()["expires_at"] is not None
        assert card.json()["payload"] == approval.payload
        assert "grant_key" not in card.text and "system_prompt" not in card.text
        assert (
            await http.client.get(f"/v1/letas/{root.id}/history", headers=resourceh)
        ).status_code == 404
        accepted = await http.client.post(
            base + "/response", json={"action": "accept"}, headers=resourceh
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "resolved"
        await http.temporal.get_workflow_handle(f"human-request/{approval.id}").result()
        retry = await http.client.post(
            base + "/response", json={"action": "accept"}, headers=resourceh
        )
        assert retry.json()["outcome"]["granted"]
        assert scopes.change_scope_access.await_count == 1
        assert (
            await http.client.post(
                base + "/response", json={"action": "deny"}, headers=resourceh
            )
        ).status_code == 409
        assert (
            len(
                (await http.client.get("/v1/human-requests", headers=resourceh)).json()[
                    "items"
                ]
            )
            == 1
        )
        ask_request = ask(root).model_copy(
            update={
                "requester_agent_id": box.letis[1].id,
                "payload": {
                    "questions": [
                        {
                            "id": "one",
                            "type": "single_choice",
                            "text": "Pick one",
                            "options": [{"id": "a", "label": "A"}],
                        },
                        {
                            "id": "many",
                            "type": "multiple_choice",
                            "text": "Pick several",
                            "options": [{"id": "b", "label": "B"}],
                        },
                        {"id": "text", "type": "text", "text": "Explain"},
                    ]
                },
            }
        )
        await open_human_request(
            http.temporal,
            http.store,
            OpenHumanRequest(
                leta_id=root.id,
                request_id=ask_request.id,
                creation=ask_request,
                timeout_seconds=60,
            ),
        )
        askbase = f"/v1/human-requests/{ask_request.id}"
        cards = await http.client.get("/v1/human-requests", headers=ownerh)
        assert cards.status_code == 200, cards.text
        assert cards.json()["items"][0]["payload"] == ask_request.payload
        assert cards.json()["items"][0]["expires_at"] is not None
        managed = await http.client.get(
            f"/v1/letas/{root.id}/human-requests", headers=ownerh
        )
        assert managed.status_code == 200, managed.text
        assert all(
            "timeout_seconds" not in item["payload"] for item in managed.json()["items"]
        )
        invalid = await http.client.post(
            askbase + "/response",
            headers=ownerh,
            json={"action": "answer", "answers": {"one": {"option_id": "wrong"}}},
        )
        assert invalid.status_code == 400
        answer = {
            "action": "answer",
            "answers": {
                "one": {"option_id": None, "note": "No choice"},
                "many": {"option_ids": [], "note": "None"},
                "text": {"text": "Proceed"},
            },
        }
        answered = await http.client.post(
            askbase + "/response", headers=ownerh, json=answer
        )
        assert answered.status_code == 200, answered.text
        await http.temporal.get_workflow_handle(
            f"human-request/{ask_request.id}"
        ).result()
        outcome = await http.store.get_message(root.id, ask_request.outcome_message_id)
        assert outcome["recipient_agent_id"] == box.letis[1].id
        assert outcome["data"]["outcome"]["answers"] == answer["answers"]
        pending = ask(root)
        await open_human_request(
            http.temporal,
            http.store,
            OpenHumanRequest(leta_id=root.id, request_id=pending.id, creation=pending),
        )
        cancelled = await http.client.post(
            f"/v1/letas/{root.id}/human-requests/{pending.id}/cancel",
            headers=ownerh,
            json={"reason": "Changed plan"},
        )
        assert (
            cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
        )
        assert (
            await http.client.get(f"/v1/letas/{root.id}/human-requests", headers=ownerh)
        ).status_code == 200


async def test_configuration_reports_incompatible_inheriting_children(http, settings):
    from leta.config import ModelCatalog
    from leta.domain import AgentConfiguration

    root = await active_root(http.store)
    box = await active_box(http.store, root)
    http.store.models = ModelCatalog.model_validate(
        {
            "models": [model.model_dump() for model in settings.models.models]
            + [
                {
                    "model_id": "provider/limited",
                    "reasoning_efforts": [None],
                    "context_window_tokens": 16384,
                    "max_output_tokens": 1000,
                }
            ],
            "default": settings.models.default.model_dump(),
        }
    )
    await http.store.configure_agent(
        root.id, box.letis[0].id, AgentConfiguration(reasoning_effort="high")
    )
    response = await http.client.patch(
        f"/v1/letas/{root.id}",
        json={"model_id": "provider/limited"},
        headers=headers(settings, root.created_by_user_id, uuid7()),
    )
    assert response.status_code == 400
    assert box.letis[0].name in response.json()["detail"]
    assert str(box.letis[0].id) in response.json()["detail"]
    assert (await http.store.get_agent(root.id, root.id))[
        "model_id"
    ] == "provider/model"
