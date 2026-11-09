"""Human tools finish immediately; only the finite request Workflow waits."""

from typing import Literal
from uuid import UUID, uuid5

from openlet.errors import AppError
from pydantic import TypeAdapter

from leta.domain import HumanStatus, NewHumanRequest, TimeCursor, fault
from leta.human import AskForm, PersonalResource, Question, RequestResolution
from leta.runtime.state import RuntimeContext
from leta.temporal.bridges import open_human_request, resolve_human_request
from leta.temporal.human_activities import has_scope_access
from leta.temporal.human_types import OpenHumanRequest

JSON = TypeAdapter(dict)


def projection(row):
    result = {
        key: row[key]
        for key in (
            "id",
            "requester_agent_id",
            "kind",
            "title",
            "payload",
            "approver_user_id",
            "resource",
            "requested_role",
            "status",
            "expires_at",
            "decision",
            "outcome",
            "created_at",
            "resolved_at",
        )
    }
    # Retry metadata stays in storage; the public deadline is expires_at.
    result["payload"] = row["payload"].copy()
    result["payload"].pop("timeout_seconds", None)
    return JSON.dump_python(result, mode="json")


async def existing(context, request_id):
    try:
        row = await context.store.get_request(context.request.leta_id, request_id)
    except AppError as error:
        if error.kind != "missing":
            raise
        return None
    if row["requester_agent_id"] != context.request.agent_id:
        raise fault("FORBIDDEN", "request belongs to another agent", "forbidden")
    return row


async def open_request(context, request, timeout_seconds):
    state = await open_human_request(
        context.temporal,
        context.store,
        OpenHumanRequest(
            leta_id=request.leta_id,
            request_id=request.id,
            creation=request,
            timeout_seconds=timeout_seconds,
        ),
    )
    return {
        "request_id": str(state.request_id),
        "status": state.status,
        "expires_at": state.expires_at.isoformat() if state.expires_at else None,
        "outcome": state.outcome,
    }


async def ask_user(
    context: RuntimeContext,
    request_id: UUID,
    title: str,
    questions: list[Question],
    timeout_seconds: int | None = None,
):
    form = AskForm(questions=questions)
    request = NewHumanRequest(
        id=request_id,
        leta_id=context.request.leta_id,
        requester_agent_id=context.request.agent_id,
        kind="ask",
        title=title,
        payload=form.model_dump(mode="json"),
        approver_user_id=context.root["created_by_user_id"],
        outcome_message_id=uuid5(request_id, "outcome"),
    )
    return await open_request(context, request, timeout_seconds)


async def request_access(
    context: RuntimeContext,
    request_id: UUID,
    resource: PersonalResource,
    role: Literal["viewer", "editor"] = "viewer",
    reason: str = "",
    timeout_seconds: int | None = None,
):
    resource = PersonalResource.model_validate(resource)
    if role not in {"viewer", "editor"}:
        raise ValueError("access role must be viewer or editor")
    saved = await existing(context, request_id)
    if saved:
        # Retry the original canonical request even after access or membership changes.
        canonical = saved["resource"]
        if saved["kind"] != "approval" or canonical["user_id"] != str(resource.user_id):
            raise fault("STATE_CONFLICT", "request identity has different resource")
    else:
        resolved = await context.scopes.resolve_personal_scope(
            str(context.root["workspace_id"]),
            str(resource.user_id),
            actor=context.workspace.actor,
        )
        if await has_scope_access(
            context.scopes, context.root, resolved.scope_id, role
        ):
            return {
                "status": "already_granted",
                "scope_id": resolved.scope_id,
                "role": role,
                "mount_path": f"/users/{resource.user_id}",
            }
        canonical = {
            "type": "personal_scope",
            "user_id": str(resource.user_id),
            "scope_id": resolved.scope_id,
        }
    request = NewHumanRequest(
        id=request_id,
        leta_id=context.request.leta_id,
        requester_agent_id=context.request.agent_id,
        kind="approval",
        title="Access personal scope",
        payload={"reason": reason},
        approver_user_id=resource.user_id,
        outcome_message_id=uuid5(request_id, "outcome"),
        grantee_leta_id=context.request.leta_id,
        resource=canonical,
        requested_role=role,
    )
    return await open_request(context, request, timeout_seconds)


async def list_hitl(context, status=None, box=None, limit=20, cursor=None):
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    box_id, requester = None, context.request.agent_id
    if box is not None:
        if context.agent["kind"] != "leta":
            raise fault("FORBIDDEN", "Leti may list only its requests", "forbidden")
        selected = await context.store.resolve_box(context.request.leta_id, box)
        box_id, requester = selected["id"], None
    page = await context.store.list_requests(
        context.request.leta_id,
        requester_agent_id=requester,
        box_id=box_id,
        status=HumanStatus(status) if status is not None else None,
        after=TimeCursor.model_validate_json(cursor) if cursor else None,
        limit=limit + 1,
    )
    return {
        "items": [projection(row) for row in page[:limit]],
        "next_cursor": (
            TimeCursor(
                at=page[limit - 1]["created_at"], id=page[limit - 1]["id"]
            ).model_dump_json()
            if len(page) > limit
            else None
        ),
    }


async def get_hitl(context, request_id):
    row = await context.store.get_request(context.request.leta_id, UUID(request_id))
    if (
        context.agent["kind"] != "leta"
        and row["requester_agent_id"] != context.request.agent_id
    ):
        raise fault("FORBIDDEN", "Leti may inspect only its requests", "forbidden")
    return row


async def cancel_hitl(context, request_id, reason=""):
    row = await get_hitl(context, request_id)
    state = await resolve_human_request(
        context.temporal,
        context.store,
        RequestResolution(
            leta_id=context.request.leta_id,
            request_id=row["id"],
            action="cancel",
            requester_agent_id=context.request.agent_id,
            reason=reason,
        ),
    )
    return {"request_id": str(state.request_id), "status": state.status}
