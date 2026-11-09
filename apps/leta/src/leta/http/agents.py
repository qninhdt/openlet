from uuid import UUID, uuid7

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from openlet.authz import Resource, bulk_check, check
from openlet.errors import AppError

from leta.config import ModelCatalog, ModelSelection
from leta.domain import AgentConfiguration, Lifecycle, NewLeta
from leta.http.common import API, Limit, cursor_scope, page, read_cursor
from leta.http.models import AgentView, ChildConfiguration, CreateLeta, Page, agent_view
from leta.store import fault
from leta.temporal.bridges import change_leta
from leta.temporal.lifecycle_types import LetaChange

router = APIRouter()


@router.get("/v1/leta-models", response_model=ModelCatalog)
async def models(context: API):
    return context.models.model_dump(mode="json")


@router.post("/v1/letas", status_code=201, response_model=AgentView)
async def create(body: CreateLeta, context: API):
    try:
        selection = context.models.resolve(
            ModelSelection(
                model_id=body.model_id, reasoning_effort=body.reasoning_effort
            )
        )
    except ValueError as error:
        raise fault("VALIDATION", "unsupported model selection", "invalid") from error
    await context.scopes.get_workspace(str(body.workspace_id), actor=context.actor)
    if not await check(
        context.authz,
        context.actor,
        "create_leta",
        Resource("workspace", str(body.workspace_id)),
    ):
        raise fault("FORBIDDEN", "cannot create Leta in this workspace", "forbidden")
    key, saved = await context.command(body)
    root_id = saved["resource_id"]
    home_scope_id = uuid7()
    try:
        existing = await context.store.get_agent(root_id, root_id)
    except AppError as error:
        if error.kind != "missing":
            raise
    else:
        home_scope_id = existing["home_scope_id"]
        if existing["status"] != "initializing":
            await context.store.complete_api_request(context.actor.id, key)
            return agent_view(existing)
    creation = NewLeta(
        id=root_id,
        workspace_id=body.workspace_id,
        created_by_user_id=context.actor.id,
        home_scope_id=home_scope_id,
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        model=selection,
    )
    result = await context.execute(
        change_leta(
            context.temporal,
            LetaChange(leta_id=root_id, action="create", creation=creation),
            command_id=str(key),
        ),
        resource_id=root_id,
        key=key,
    )
    if isinstance(result, JSONResponse):
        return result
    return agent_view(await context.store.get_agent(root_id, root_id))


@router.get("/v1/letas", response_model=Page[AgentView])
async def list_letas(
    context: API,
    workspace_id: UUID | None = None,
    status: Lifecycle | None = None,
    limit: Limit = 20,
    cursor: str | None = None,
):
    scope = cursor_scope("letas", context.actor.id, workspace_id, status)
    after = read_cursor(cursor, scope)
    found = await context.store.api_roots(
        context.actor.id,
        workspace_id=workspace_id,
        status=status,
        after=after,
        limit=limit + 1,
    )
    allowed = (
        await bulk_check(
            context.authz,
            context.actor,
            "read",
            [Resource("leta", str(row["id"])) for row in found[:limit]],
        )
        if found
        else []
    )
    # The cursor advances over the SQL page even when membership filters every row.
    output = page(found, limit, scope, lambda row: str(row["id"]))
    output["items"] = [
        agent_view(row) for row, can_read in zip(found[:limit], allowed) if can_read
    ]
    return output


@router.get("/v1/letas/{leta_id}", response_model=AgentView)
async def get(leta_id: UUID, context: API):
    return agent_view(await context.root(leta_id))


@router.patch("/v1/letas/{leta_id}", response_model=AgentView)
async def update(leta_id: UUID, body: AgentConfiguration, context: API):
    await context.root(leta_id, manage=True)
    if not body.model_fields_set:
        raise fault("VALIDATION", "agent patch is empty", "invalid")
    key, saved = await context.command(body, resource_id=leta_id)
    if saved["expires_at"] is not None:
        return agent_view(await context.store.get_agent(leta_id, leta_id))
    await context.store.validate_configuration(leta_id, leta_id, body)
    result = await context.execute(
        change_leta(
            context.temporal,
            LetaChange(leta_id=leta_id, action="configure", configuration=body),
            command_id=str(key),
        ),
        resource_id=leta_id,
        key=key,
    )
    return (
        result
        if isinstance(result, JSONResponse)
        else agent_view(await context.store.get_agent(leta_id, leta_id))
    )


@router.post("/v1/letas/{leta_id}/pause", response_model=AgentView)
async def pause(leta_id: UUID, context: API):
    return await control(leta_id, context, "pause")


@router.post("/v1/letas/{leta_id}/resume", response_model=AgentView)
async def resume(leta_id: UUID, context: API):
    return await control(leta_id, context, "resume")


@router.delete("/v1/letas/{leta_id}", response_model=AgentView)
async def delete(leta_id: UUID, context: API):
    return await control(leta_id, context, "deleting")


async def control(leta_id, context, action):
    root = await context.root(leta_id, manage=True)
    key, saved = await context.command(resource_id=leta_id)
    if saved["expires_at"] is not None or (
        action == "deleting" and root["status"] == "archived"
    ):
        await context.store.complete_api_request(context.actor.id, key)
        return agent_view(root)
    result = await context.execute(
        change_leta(
            context.temporal,
            LetaChange(leta_id=leta_id, action=action),
            command_id=str(key),
        ),
        resource_id=leta_id,
        key=key,
    )
    return (
        result
        if isinstance(result, JSONResponse)
        else agent_view(await context.store.get_agent(leta_id, leta_id))
    )


@router.get("/v1/letas/{leta_id}/agents", response_model=Page[AgentView])
async def agents(
    leta_id: UUID, context: API, limit: Limit = 20, cursor: str | None = None
):
    root = await context.root(leta_id)
    scope = cursor_scope("agents", leta_id)
    after = read_cursor(cursor, scope)
    found = await context.store.api_agents(leta_id, after=after, limit=limit + 1)
    output = page(found, limit, scope, lambda row: str(row["id"]))
    output["items"] = [
        agent_view(row) | {"paused": root["paused"]} for row in found[:limit]
    ]
    return output


@router.patch("/v1/letas/{leta_id}/agents/{agent_id}", response_model=AgentView)
async def update_child(
    leta_id: UUID, agent_id: UUID, body: ChildConfiguration, context: API
):
    root = await context.root(leta_id, manage=True)
    child = await context.store.get_agent(leta_id, agent_id)
    if child["kind"] != "leti":
        raise fault("VALIDATION", "this route configures a Leti", "invalid")
    if not body.model_fields_set:
        raise fault("VALIDATION", "agent patch is empty", "invalid")
    patch = AgentConfiguration.model_validate(body.model_dump(exclude_unset=True))
    key, saved = await context.command(patch, resource_id=agent_id)
    if saved["expires_at"] is not None:
        return agent_view(child, paused=root["paused"])
    await context.store.validate_configuration(leta_id, agent_id, patch)
    result = await context.execute(
        change_leta(
            context.temporal,
            LetaChange(
                leta_id=leta_id,
                agent_id=agent_id,
                action="configure",
                configuration=patch,
            ),
            command_id=str(key),
        ),
        resource_id=agent_id,
        key=key,
    )
    return (
        result
        if isinstance(result, JSONResponse)
        else agent_view(
            await context.store.get_agent(leta_id, agent_id), paused=root["paused"]
        )
    )
