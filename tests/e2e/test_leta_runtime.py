"""Native Leta runtime, boxes, SSE streams, HITL, operator privacy, and schedules."""

from __future__ import annotations

import datetime as dt
import json
import time

import httpx
from openlet_env import Environment
from openlet_sdk.types import is_object_list, is_str_mapping

from .conftest import AccountFactory, AccountFixture, new_uuid, poll


def _read_first_sse_chunk(url: str, token: str) -> str:
    with httpx.Client(timeout=30.0) as client:
        with client.stream(
            "GET", url, headers={"Authorization": f"Bearer {token}"}
        ) as stream:
            assert stream.status_code == 200
            for chunk in stream.iter_text():
                if chunk.strip():
                    return chunk
    raise AssertionError(f"SSE stream at {url} produced no data")


def test_leta_runtime_boxes_hitl_and_owner_independent_schedules(
    openlet_env: Environment,
    account: AccountFixture,
    accounts: AccountFactory,
) -> None:
    api = account.api
    workspace = f"/v1/workspaces/{account.workspace_id}"

    models = api.get(f"{workspace}/letas/models")
    assert models.is_success, models.text
    assert models.json()["models"] == [
        {"model_id": "openai/gpt-4.1-mini", "reasoning_efforts": [None, "low"]}
    ]

    creation = api.post(
        f"{workspace}/letas",
        json={
            "request_id": new_uuid(),
            "name": "Vega",
            "title": "Workspace Coordinator",
            "system_prompt": "Perform workspace tasks and report the outcome.",
        },
    )
    assert creation.is_success, creation.text
    root_id: str = creation.json()["id"]
    path = f"{workspace}/letas/{root_id}"

    poll(
        lambda: api.get(path).json().get("state") == "active",
        timeout=30.0,
        desc="leta active",
    )

    selection = f"{path}/agents/{root_id}"
    selected = api.patch(
        selection, json={"model_id": "openai/gpt-4.1-mini", "reasoning_effort": "low"}
    )
    assert selected.is_success, selected.text
    assert selected.json()["reasoning_effort"] == "low"

    changed = api.patch(selection, json={"model_id": "openai/gpt-4.1-mini"})
    assert changed.is_success, changed.text
    assert changed.json()["reasoning_effort"] is None

    reset = api.patch(selection, json={"model_id": None})
    assert reset.is_success, reset.text
    assert reset.json()["model_id"] is None
    assert api.patch(selection, json={"reasoning_effort": "low"}).status_code == 422

    msg = {
        "message_id": new_uuid(),
        "content": "Write a workspace report and run a shell calculation.",
    }
    assert api.post(f"{path}/messages", json=msg).is_success
    assert api.post(f"{path}/messages", json=msg).is_success

    def has_final_note() -> bool:
        resp = api.get(f"{path}/agents/{root_id}/history")
        assert resp.is_success, resp.text
        return any(e.get("kind") == "final_note" for e in resp.json()["entries"])

    poll(has_final_note, timeout=45.0, interval=0.5, desc="leta final_note")

    root_view = api.get(f"{selection}/settings").json()
    storage = f"{workspace}/storages/{root_view['storage_id']}"
    storage_view = api.get(storage).json()
    children = api.get(f"{storage}/nodes/{storage_view['rootNodeId']}/children")
    assert children.is_success, children.text
    report_node = next(
        (n for n in children.json()["nodes"] if n["name"] == "report.txt"), None
    )
    assert report_node is not None
    report = api.get(f"{storage}/nodes/{report_node['id']}/text")
    assert report.is_success, report.text
    assert report.json()["content"] == "Native Leta runtime wrote this file."

    first_sse = _read_first_sse_chunk(
        f"{openlet_env.endpoints.api_url}{path}/events",
        accounts.sign("stream-test", account.id),
    )
    assert "openlet.snapshot" in first_sse
    assert "next_cursor" in first_sse

    team = api.post(
        f"{path}/boxes",
        json={
            "request_id": new_uuid(),
            "name": "Report Review Team",
            "letis": [
                {
                    "name": "Rigel",
                    "title": "Reviewer",
                    "system_prompt": "Review documents.",
                }
            ],
            "additional_links": [],
            "leader": "Rigel",
        },
    )
    assert team.is_success, team.text
    box = team.json()
    graph = api.get(f"{path}/boxes/{box['id']}").json()
    leti_id: str = graph["leader_agent_id"]

    question_id = new_uuid()
    asked = api.post(
        f"{path}/hitl-requests",
        json={
            "type": "ask",
            "request_id": question_id,
            "requester_agent_id": root_id,
            "recipient_user_id": account.id,
            "title": "Review the report?",
            "questions": [{"text": "Which region?", "options": ["North", "South"]}],
        },
    )
    assert asked.is_success, asked.text
    answered = api.post(
        f"/v1/hitl-requests/{question_id}/answer",
        json={
            "status": "answered",
            "response": {"answers": {"q1": {"option_id": "o1"}}},
        },
    )
    assert answered.is_success, answered.text

    guest = accounts.create()
    invite = api.post(
        f"{workspace}/invitations",
        json={"email": guest.email, "requestId": new_uuid()},
    )
    accepted = guest.api.post(
        "/v1/invitations:accept", json={"token": invite.json()["token"]}
    )
    assert accepted.is_success, accepted.text
    assert api.put(f"{path}/operators/{guest.id}").is_success

    private_text = f"Private note {new_uuid()}"
    assert guest.api.post(
        f"{path}/messages",
        json={"message_id": new_uuid(), "content": private_text},
    ).is_success
    assert private_text in guest.api.get(f"{path}/messages").text
    assert private_text not in api.get(f"{path}/messages").text
    assert guest.api.get(f"{path}/events").status_code == 403

    private_sse = _read_first_sse_chunk(
        f"{openlet_env.endpoints.api_url}{path}/messages/events",
        accounts.sign("private-stream", guest.id),
    )
    assert private_text in private_sse
    assert "system_prompt" not in private_sse
    assert '"history"' not in private_sse

    now = dt.datetime.now(dt.UTC)
    starts_at = (now + dt.timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    ends_at = (now + dt.timedelta(days=1)).isoformat().replace("+00:00", "Z")
    recurring = api.post(
        f"{path}/schedules",
        json={
            "request_id": new_uuid(),
            "content": "Review remaining work.",
            "every_seconds": 600,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "timezone": "Asia/Ho_Chi_Minh",
        },
    )
    assert recurring.is_success, recurring.text
    original = recurring.json()
    changed_sched = api.patch(
        f"{path}/schedules/{original['id']}",
        json={"request_id": new_uuid(), "every_seconds": 900, "paused": True},
    )
    assert changed_sched.is_success, changed_sched.text
    assert changed_sched.json()["spec"] == {**original["spec"], "every_seconds": 900}

    cleared = api.patch(
        f"{path}/schedules/{original['id']}",
        json={"request_id": new_uuid(), "ends_at": None},
    )
    assert cleared.is_success, cleared.text
    assert cleared.json()["spec"]["ends_at"] is None
    assert api.request(
        "DELETE",
        f"{path}/schedules/{original['id']}",
        json={"request_id": new_uuid()},
    ).is_success

    transfer = api.post(
        f"{workspace}:transferOwnership", json={"newOwnerUserId": guest.id}
    )
    assert transfer.is_success, transfer.text

    def guest_is_owner() -> bool:
        resp = guest.api.get("/v1/workspaces")
        assert resp.is_success, resp.text
        match = next(
            (w for w in resp.json()["workspaces"] if w["id"] == account.workspace_id),
            None,
        )
        return match is not None and match.get("role") == "WORKSPACE_ROLE_OWNER"

    poll(guest_is_owner, timeout=30.0, desc="ownership transferred to guest")

    scheduled_instruction = (
        f"Read the workspace report and run a shell calculation. Audit {root_id}"
    )
    scheduled = api.post(
        f"{path}/schedules",
        json={
            "request_id": new_uuid(),
            "target_box_id": box["id"],
            "after_seconds": 3,
            "content": scheduled_instruction,
        },
    )
    assert scheduled.is_success, scheduled.text

    left_at_ms = int(time.time() * 1000)
    assert api.delete(f"{workspace}/members/{account.id}").is_success

    assert guest.api.get(f"{path}/agents/{leti_id}/history").status_code == 403
    assert guest.api.get(f"{path}/inbox").status_code == 403
    assert (
        guest.api.post(
            f"{path}/schedules",
            json={
                "request_id": new_uuid(),
                "content": "Unauthorized",
                "after_seconds": 0,
            },
        ).status_code
        == 403
    )

    def schedule_executed() -> bool:
        requests = openlet_env.wiremock.find_requests(
            {
                "method": "POST",
                "urlPath": "/v1/chat/completions",
                "bodyPatterns": [{"contains": scheduled_instruction}],
            }
        )
        for entry in requests:
            if entry.loggedDate < left_at_ms:
                continue
            body: object = json.loads(entry.body)
            if not is_str_mapping(body):
                continue
            msgs = body.get("messages", [])
            if not is_object_list(msgs):
                continue
            for m in msgs:
                if (
                    is_str_mapping(m)
                    and m.get("role") == "tool"
                    and m.get("tool_call_id") == "reuse-session"
                    and m.get("content") == "Native Leta runtime wrote this file."
                ):
                    return True
        return False

    poll(
        schedule_executed, timeout=60.0, interval=0.5, desc="owner-independent schedule"
    )

    assert guest.api.delete(workspace).is_success
    poll(
        lambda: guest.api.get(workspace).status_code == 403,
        timeout=30.0,
        desc="workspace deleted by new owner",
    )
