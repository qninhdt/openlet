"""Root-only immutable canvas tools, using the concrete box coordinator."""

from uuid import UUID, uuid5, uuid7

from openlet.errors import AppError
from pydantic import Field, TypeAdapter

from leta.domain import LetiSpec, Named, NewBox, box_slug, fault
from leta.runtime.state import RuntimeContext
from leta.temporal.bridges import change_box
from leta.temporal.lifecycle_types import BoxChange

JSON = TypeAdapter(dict)


class LetiDefinition(Named):
    system_prompt: str = Field(max_length=100_000)


def require_root(context: RuntimeContext):
    if context.agent["kind"] != "leta":
        raise fault("FORBIDDEN", "only Leta manages boxes", "forbidden")


async def create_box(context, box_id, name, description, letis, edges, representative):
    require_root(context)
    try:
        saved = await context.store.get_box(context.request.leta_id, box_id)
    except AppError as error:
        if error.kind != "missing":
            raise
        home_node_id = uuid7()
    else:
        home_node_id = saved["home_node_id"]
    value = NewBox(
        id=box_id,
        leta_id=context.request.leta_id,
        home_node_id=home_node_id,
        name=name,
        description=description,
        letis=[
            LetiSpec(id=uuid5(box_id, f"leti:{spec.name}"), **spec.model_dump())
            for spec in letis
        ],
        edges=edges,
        representative=representative,
    )
    result = await change_box(
        context.temporal,
        BoxChange(
            leta_id=value.leta_id, box_id=box_id, action="create", creation=value
        ),
        command_id=str(box_id),
    )
    return {"box_id": str(box_id), "name": name, "status": result.status}


async def list_boxes(context, limit=20, cursor=None):
    require_root(context)
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    page = await context.store.list_boxes(
        context.request.leta_id, after=UUID(cursor) if cursor else None, limit=limit + 1
    )
    items = [
        {
            key: row[key]
            for key in (
                "id",
                "name",
                "description",
                "status",
                "agent_count",
                "pending_request_count",
                "schedule_count",
            )
        }
        for row in page[:limit]
    ]
    return JSON.dump_python(
        {
            "items": items,
            "next_cursor": str(page[limit - 1]["id"]) if len(page) > limit else None,
        },
        mode="json",
    )


async def get_box(context, reference):
    require_root(context)
    root_id = context.request.leta_id
    selected = await context.store.resolve_box(root_id, reference)
    box = await context.store.get_box_graph(root_id, selected["id"], details=True)
    return JSON.dump_python(
        {
            **{
                key: box[key]
                for key in (
                    "id",
                    "name",
                    "description",
                    "status",
                    "representative_agent_id",
                )
            },
            "home": f"~/.leti/{box_slug(box['name'])}",
            "letis": [
                {
                    key: agent[key]
                    for key in (
                        "id",
                        "name",
                        "description",
                        "system_prompt",
                        "status",
                        "model_id",
                        "reasoning_effort",
                    )
                }
                for agent in box["letis"]
            ],
            "edges": [
                [edge["agent_low_id"], edge["agent_high_id"]] for edge in box["edges"]
            ],
            "runs": box["runs"],
            "requests": box["requests"],
            "schedules": box["schedules"],
        },
        mode="json",
    )


async def delete_box(context, reference):
    require_root(context)
    box = await context.store.resolve_box(context.request.leta_id, reference)
    if box["status"] == "archived":
        return {"box_id": str(box["id"]), "status": "archived"}
    result = await change_box(
        context.temporal,
        BoxChange(leta_id=context.request.leta_id, box_id=box["id"], action="deleting"),
    )
    return {"box_id": str(box["id"]), "status": result.status}
