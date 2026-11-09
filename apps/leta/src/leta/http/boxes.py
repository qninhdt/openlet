from uuid import UUID, uuid5, uuid7

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from openlet.errors import AppError
from pydantic import ValidationError

from leta.domain import LetiSpec, NewBox, fault
from leta.http.common import API, JSON, Limit, cursor_scope, page, read_cursor
from leta.http.models import BoxView, CreateBox, Page, agent_view
from leta.temporal.bridges import change_box
from leta.temporal.lifecycle_types import BoxChange

router = APIRouter()


def box_view(row, *, paused=False):
    result = {
        key: value
        for key, value in row.items()
        if key not in {"letis", "edges", "home_node_id"}
    }
    if "letis" in row:
        result["letis"] = [agent_view(agent, paused=paused) for agent in row["letis"]]
        result["edges"] = [
            [edge["agent_low_id"], edge["agent_high_id"]] for edge in row["edges"]
        ]
    return BoxView.model_validate(JSON.dump_python(result, mode="json"))


@router.get("/v1/letas/{leta_id}/boxes", response_model=Page[BoxView])
async def boxes(
    leta_id: UUID, context: API, limit: Limit = 20, cursor: str | None = None
):
    root = await context.root(leta_id)
    scope = cursor_scope("boxes", leta_id)
    after = read_cursor(cursor, scope)
    found = await context.store.list_boxes(leta_id, after=after, limit=limit + 1)
    output = page(found, limit, scope, lambda row: str(row["id"]))
    output["items"] = [box_view(row, paused=root["paused"]) for row in found[:limit]]
    return output


@router.post("/v1/letas/{leta_id}/boxes", status_code=201, response_model=BoxView)
async def create(leta_id: UUID, body: CreateBox, context: API):
    root = await context.root(leta_id, manage=True)
    key, saved = await context.command(body)
    box_id = saved["resource_id"]
    home_node_id = uuid7()
    try:
        existing = await context.store.get_box_graph(leta_id, box_id, details=True)
    except AppError as error:
        if error.kind != "missing":
            raise
    else:
        home_node_id = existing["home_node_id"]
        if existing["status"] != "initializing":
            await context.store.complete_api_request(context.actor.id, key)
            return box_view(existing, paused=root["paused"])
    try:
        creation = NewBox(
            id=box_id,
            leta_id=leta_id,
            home_node_id=home_node_id,
            name=body.name,
            description=body.description,
            letis=[
                LetiSpec(id=uuid5(box_id, f"leti:{spec.name}"), **spec.model_dump())
                for spec in body.letis
            ],
            edges=body.edges,
            representative=body.representative,
        )
    except ValidationError as error:
        raise fault("VALIDATION", "invalid box graph", "invalid") from error
    result = await context.execute(
        change_box(
            context.temporal,
            BoxChange(
                leta_id=leta_id, box_id=box_id, action="create", creation=creation
            ),
            command_id=str(key),
        ),
        resource_id=box_id,
        key=key,
    )
    return (
        result
        if isinstance(result, JSONResponse)
        else box_view(
            await context.store.get_box_graph(leta_id, box_id, details=True),
            paused=root["paused"],
        )
    )


@router.get("/v1/letas/{leta_id}/boxes/{box_id}", response_model=BoxView)
async def get(leta_id: UUID, box_id: UUID, context: API):
    root = await context.root(leta_id)
    return box_view(
        await context.store.get_box_graph(leta_id, box_id, details=True),
        paused=root["paused"],
    )


@router.delete("/v1/letas/{leta_id}/boxes/{box_id}", response_model=BoxView)
async def delete(leta_id: UUID, box_id: UUID, context: API):
    root = await context.root(leta_id, manage=True)
    box = await context.store.get_box(leta_id, box_id)
    key, _ = await context.command(resource_id=box_id)
    if box["status"] == "archived":
        await context.store.complete_api_request(context.actor.id, key)
        return box_view(box, paused=root["paused"])
    result = await context.execute(
        change_box(
            context.temporal,
            BoxChange(leta_id=leta_id, box_id=box_id, action="deleting"),
            command_id=str(key),
        ),
        resource_id=box_id,
        key=key,
    )
    return (
        result
        if isinstance(result, JSONResponse)
        else box_view(
            await context.store.get_box_graph(leta_id, box_id, details=True),
            paused=root["paused"],
        )
    )
