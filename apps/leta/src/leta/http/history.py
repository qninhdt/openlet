from uuid import UUID

from fastapi import APIRouter

from leta.domain import fault
from leta.history import ActivityEntry, activity_entry
from leta.http.common import API, Limit, cursor_scope, page, read_cursor
from leta.http.models import Page, RunView

router = APIRouter()


@router.get("/v1/letas/{leta_id}/history", response_model=Page[ActivityEntry])
async def history(
    leta_id: UUID,
    context: API,
    agent_id: UUID | None = None,
    run_id: UUID | None = None,
    limit: Limit = 20,
    cursor: str | None = None,
):
    await context.root(leta_id)
    agent_id = agent_id or leta_id
    await context.store.get_agent(leta_id, agent_id)
    if run_id is not None:
        await context.store.get_run(leta_id, agent_id, run_id)
    scope = cursor_scope("history", leta_id, agent_id, run_id)
    after = read_cursor(cursor, scope, int)
    if after is not None and after < 0:
        raise fault("VALIDATION", "invalid history cursor", "invalid")
    found = await context.store.list_activity(
        leta_id, agent_id, after=after or 0, run_id=run_id, limit=limit + 1
    )
    output = page(found, limit, scope, lambda row: row["seq"])
    output["items"] = [activity_entry(row) for row in found[:limit]]
    return output


@router.get("/v1/letas/{leta_id}/history/{entry_id}", response_model=ActivityEntry)
async def entry(
    leta_id: UUID, entry_id: UUID, context: API, agent_id: UUID | None = None
):
    await context.root(leta_id)
    return activity_entry(
        await context.store.get_activity(leta_id, agent_id or leta_id, entry_id)
    )


@router.get("/v1/letas/{leta_id}/runs/{run_id}", response_model=RunView)
async def run(leta_id: UUID, run_id: UUID, context: API):
    await context.root(leta_id)
    row = await context.store.api_run(leta_id, run_id)
    return {key: row[key] for key in RunView.model_fields if key in row} | {
        "events_url": f"/v1/letas/{leta_id}/events"
    }
