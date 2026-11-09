from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from openlet.authz import Resource, check

from leta.domain import HumanStatus, TimeCursor
from leta.http.common import API, Limit, cursor_scope, page, read_cursor, time_position
from leta.http.models import (
    CancelRequest,
    HumanResponse,
    Page,
    RequestCard,
    RequestView,
)
from leta.human import RequestResolution
from leta.runtime.human import projection
from leta.store import fault
from leta.temporal.bridges import resolve_human_request

router = APIRouter()


def card(row):
    return (
        projection(row)
        | {
            key: row[key]
            for key in (
                "leta_id",
                "workspace_id",
                "created_by_user_id",
                "leta_name",
                "requester_name",
                "box_id",
                "box_name",
            )
        }
        | {
            "visibility_notice": (
                "Access is granted to Leta and inherited by its Leti. The Leta "
                "owner can view resulting agent activity."
                if row["kind"] == "approval"
                else (
                    "Answers return to the requesting agent "
                    "and are visible to the Leta owner."
                )
            )
        }
    )


async def addressed(context, request_id):
    row = await context.store.addressed_request(context.actor.id, request_id)
    if not await check(
        context.authz,
        context.actor,
        "read",
        Resource("workspace", str(row["workspace_id"])),
    ):
        raise fault("FORBIDDEN", "workspace access denied", "forbidden")
    return row


@router.get("/v1/letas/{leta_id}/human-requests", response_model=Page[RequestView])
async def managed(
    leta_id: UUID,
    context: API,
    agent_id: UUID | None = None,
    box_id: UUID | None = None,
    status: HumanStatus | None = None,
    limit: Limit = 20,
    cursor: str | None = None,
):
    await context.root(leta_id)
    if agent_id:
        await context.store.get_agent(leta_id, agent_id)
    if box_id:
        await context.store.get_box(leta_id, box_id)
    scope = cursor_scope("managed_requests", leta_id, agent_id, box_id, status)
    found = await context.store.list_requests(
        leta_id,
        requester_agent_id=agent_id,
        box_id=box_id,
        status=status,
        after=read_cursor(cursor, scope, TimeCursor),
        limit=limit + 1,
    )
    output = page(found, limit, scope, time_position)
    output["items"] = [projection(row) for row in found[:limit]]
    return output


@router.get("/v1/human-requests", response_model=Page[RequestCard])
async def received(
    context: API,
    status: HumanStatus | None = None,
    limit: Limit = 20,
    cursor: str | None = None,
):
    from openlet.authz import bulk_check

    scope = cursor_scope("addressed_requests", context.actor.id, status)
    found = await context.store.addressed_requests(
        context.actor.id,
        status=status,
        after=read_cursor(cursor, scope, TimeCursor),
        limit=limit + 1,
    )
    resources = list(
        dict.fromkeys(
            Resource("workspace", str(row["workspace_id"])) for row in found[:limit]
        )
    )
    allowed = (
        dict(
            zip(
                resources,
                await bulk_check(context.authz, context.actor, "read", resources),
            )
        )
        if resources
        else {}
    )
    output = page(found, limit, scope, time_position)
    output["items"] = [
        card(row)
        for row in found[:limit]
        if allowed[Resource("workspace", str(row["workspace_id"]))]
    ]
    return output


@router.get("/v1/human-requests/{request_id}", response_model=RequestCard)
async def get(request_id: UUID, context: API):
    return card(await addressed(context, request_id))


@router.post("/v1/human-requests/{request_id}/response", response_model=RequestCard)
async def respond(request_id: UUID, body: HumanResponse, context: API):
    row = await addressed(context, request_id)
    resolution = RequestResolution(
        leta_id=row["leta_id"],
        request_id=request_id,
        actor_user_id=context.actor.id,
        **body.model_dump(mode="json"),
    )
    result = await context.execute(
        resolve_human_request(context.temporal, context.store, resolution),
        resource_id=request_id,
    )
    if isinstance(result, JSONResponse):
        return result
    return card(await addressed(context, request_id))


@router.post(
    "/v1/letas/{leta_id}/human-requests/{request_id}/cancel", response_model=RequestView
)
async def cancel(leta_id: UUID, request_id: UUID, body: CancelRequest, context: API):
    await context.root(leta_id, manage=True)
    await context.store.get_request(leta_id, request_id)
    result = await context.execute(
        resolve_human_request(
            context.temporal,
            context.store,
            RequestResolution(
                leta_id=leta_id,
                request_id=request_id,
                action="cancel",
                actor_user_id=context.actor.id,
                reason=body.reason,
            ),
        ),
        resource_id=request_id,
    )
    if isinstance(result, JSONResponse):
        return result
    return projection(await context.store.get_request(leta_id, request_id))
