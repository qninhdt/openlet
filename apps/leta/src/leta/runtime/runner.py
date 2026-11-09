"""One Temporal Activity owns one synchronous-durability graph invocation."""

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid7

from langchain.agents import create_agent
from langchain_openrouter import ChatOpenRouter
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from openlet.errors import AppError
from openlet.temporal import application_error
from openrouter import OpenRouter
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from temporalio import activity

from leta.config import ModelSelection, Settings
from leta.domain import RunStatus
from leta.filesystem.workspace import WorkspaceFactory
from leta.runtime.events import ModelEvents
from leta.runtime.history import PublishAssistant, PublishContext
from leta.runtime.middleware import (
    CollectInbox,
    DynamicModel,
    OpenletBoundary,
    OpenletSummary,
    SavedToolResults,
)
from leta.runtime.state import LetaAgentState, RuntimeContext
from leta.runtime.tools import build_tools
from leta.store import Store, fault
from leta.streaming import Publisher
from leta.temporal.types import RunInput, RunResult

GRAPH_RECURSION_LIMIT = 10000


@asynccontextmanager
async def openrouter_models(settings: Settings):
    with OpenRouter(
        api_key=settings.provider_key,
        server_url=settings.provider_endpoint,
        timeout_ms=120000,
        retry_config=None,
    ) as client:

        def model(selection: ModelSelection):
            definition = next(
                m for m in settings.models.models if m.model_id == selection.model_id
            )
            return ChatOpenRouter(
                client=client,
                api_key=settings.provider_key,
                model=selection.model_id,
                reasoning={"effort": selection.reasoning_effort}
                if selection.reasoning_effort
                else None,
                max_completion_tokens=definition.max_output_tokens,
                streaming=True,
                max_retries=0,
            )

        async with client:
            yield model


def graph_input(snapshot, request: RunInput):
    """Select continuation before supplying any new graph input."""
    values = snapshot.values
    pending = bool(snapshot.next or snapshot.tasks or snapshot.interrupts)
    if not values:
        return {
            "business_run_id": str(request.run_id),
            "inbox_cursor": 0,
            "messages": [],
        }
    if values["business_run_id"] != str(request.run_id):
        if pending:
            raise fault(
                "STATE_CONFLICT", "checkpoint belongs to another unfinished run"
            )
        return {"business_run_id": str(request.run_id), "messages": []}
    if snapshot.interrupts:
        for item in snapshot.interrupts:
            value = item.value
            if (
                not isinstance(value, dict)
                or value.get("kind") != "openlet_control"
                or value.get("run_id") != str(request.run_id)
                or value.get("reason") not in {"paused", "yielded"}
            ):
                raise fault("STATE_CONFLICT", "unsupported checkpoint interrupt")
        return Command(resume={item.id: True for item in snapshot.interrupts})
    return None


class AgentRunner:
    def __init__(
        self,
        store: Store,
        workspaces: WorkspaceFactory,
        database_url: str,
        model_provider,
        temporal,
        *,
        publisher: Publisher | None = None,
    ):
        self.store, self.workspaces = store, workspaces
        self.database_url, self.model_provider = database_url, model_provider
        self.temporal = temporal
        self.publisher = publisher

    @activity.defn(name="run_agent")
    async def run_agent(self, request: RunInput) -> RunResult:
        async def heartbeat():
            while True:
                activity.heartbeat(str(request.run_id))
                await asyncio.sleep(1)

        try:
            try:
                async with asyncio.TaskGroup() as group:
                    pulse = group.create_task(heartbeat())
                    try:
                        result = await self.execute(request)
                    finally:
                        pulse.cancel()
                return result
            except ExceptionGroup as error:
                if len(error.exceptions) == 1:
                    raise error.exceptions[0] from None
                raise
        except AppError as error:
            raise application_error(
                error, fallback="RUNTIME_FAILED", message="agent runtime failed"
            ) from error

    async def execute(self, request: RunInput) -> RunResult:
        async with await AsyncConnection.connect(
            self.database_url,
            autocommit=True,
            row_factory=dict_row,
            prepare_threshold=0,
            connect_timeout=5,
        ) as connection:
            while not (
                await (
                    await connection.execute(
                        "SELECT pg_try_advisory_lock(hashtextextended(%s,0)) "
                        "AS acquired",
                        (str(request.agent_id),),
                    )
                ).fetchone()
            )["acquired"]:
                await asyncio.sleep(0.1)
            run = await self.store.get_run(**request.model_dump())
            if run["status"] == RunStatus.COMPLETED:
                return RunResult.model_validate(run["result"])
            if run["status"] in {RunStatus.CANCELLED, RunStatus.FAILED}:
                raise fault(
                    "RUN_TERMINAL", "run already ended without a successful result"
                )
            publisher = (
                await self.publisher.agent(**request.model_dump())
                if self.publisher is not None
                else None
            )
            async with (
                self.workspaces.open(
                    request.leta_id, request.agent_id, str(uuid7())
                ) as workspace,
                self.model_provider() as model_factory,
            ):
                context = RuntimeContext(
                    request=request,
                    store=self.store,
                    scopes=self.workspaces.scopes,
                    workspace=workspace,
                    models=self.store.models,
                    model_factory=model_factory,
                    temporal=self.temporal,
                    root={},
                    agent={},
                    selection=self.store.models.default,
                    events=ModelEvents(publisher) if publisher is not None else None,
                )
                await context.refresh()
                context.tools = build_tools(context)
                graph = create_agent(
                    model_factory(context.selection),
                    tools=context.tools,
                    state_schema=LetaAgentState,
                    context_schema=RuntimeContext,
                    middleware=[
                        OpenletBoundary(),
                        OpenletSummary(),
                        CollectInbox(),
                        PublishContext(),
                        DynamicModel(),
                        PublishAssistant(),
                        SavedToolResults(),
                    ],
                    checkpointer=AsyncPostgresSaver(connection),
                )
                config = {
                    "configurable": {"thread_id": str(request.agent_id)},
                    "recursion_limit": GRAPH_RECURSION_LIMIT,
                    "callbacks": [context.events] if context.events is not None else [],
                }
                snapshot = await graph.aget_state(config)
                incoming = graph_input(snapshot, request)
                same_run = snapshot.values.get("business_run_id") == str(request.run_id)
                completed = same_run and not (
                    snapshot.next or snapshot.tasks or snapshot.interrupts
                )
                if snapshot.interrupts and context.root["paused"]:
                    return await self.finish(request, snapshot, "paused", publisher)
                if not completed:
                    if publisher is not None:
                        await publisher.emit(
                            {
                                "type": "CUSTOM" if same_run else "RUN_STARTED",
                                **(
                                    {
                                        "name": "run_status",
                                        "value": {"status": "running"},
                                    }
                                    if same_run
                                    else {
                                        "threadId": str(request.agent_id),
                                        "runId": str(request.run_id),
                                    }
                                ),
                            }
                        )
                    try:
                        await graph.ainvoke(
                            incoming, config, context=context, durability="sync"
                        )
                    except AppError as error:
                        if not error.retryable:
                            failed = await graph.aget_state(config)
                            await self.store.save_run(
                                **request.model_dump(),
                                status=RunStatus.FAILED,
                                inbox_cursor=failed.values.get(
                                    "inbox_cursor", run["inbox_cursor"]
                                ),
                                error={"reason": error.reason, "detail": str(error)},
                            )
                            if publisher is not None:
                                await publisher.emit(
                                    {
                                        "type": "RUN_ERROR",
                                        "message": "Agent run failed",
                                        "code": error.reason,
                                    }
                                )
                        raise
                    snapshot = await graph.aget_state(config)
                outcome = (
                    snapshot.interrupts[0].value["reason"]
                    if snapshot.interrupts
                    else "completed"
                )
                return await self.finish(request, snapshot, outcome, publisher)

    async def finish(self, request, snapshot, outcome, publisher=None):
        result = RunResult(
            cursor=snapshot.values.get("inbox_cursor", 0), outcome=outcome
        )
        checkpoint = snapshot.config.get("configurable", {})
        await self.store.save_run(
            **request.model_dump(),
            status=RunStatus.COMPLETED if outcome == "completed" else RunStatus.PAUSED,
            inbox_cursor=result.cursor,
            checkpoint_id=checkpoint.get("checkpoint_id"),
            checkpoint_ns=checkpoint.get("checkpoint_ns"),
            continuation={
                "interrupts": [
                    {"id": item.id, "value": item.value} for item in snapshot.interrupts
                ]
            }
            if snapshot.interrupts
            else None,
            result=result.model_dump() if outcome == "completed" else None,
        )
        if publisher is not None:
            await publisher.emit(
                {
                    "type": "CUSTOM",
                    "name": "run_status",
                    "value": {
                        "status": "completed" if outcome == "completed" else "paused",
                        "outcome": outcome,
                    },
                }
            )
            if outcome == "completed":
                await publisher.emit(
                    {
                        "type": "RUN_FINISHED",
                        "threadId": str(request.agent_id),
                        "runId": str(request.run_id),
                    }
                )
        return result
