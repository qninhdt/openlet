from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, NotRequired, cast
from uuid import UUID

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime
from openlet_sdk.config import JSON
from opentelemetry import metrics

from ..agents import stable
from ..db import Pool
from ..messages import inbox_count, input_batch, input_data, name_users, pending

if TYPE_CHECKING:
    from .tools import Context


class State(AgentState[JSON]):
    inbox_cursor: NotRequired[int]
    silent_cursor: NotRequired[int]


meter = metrics.get_meter("openlet.leta")
inbox_age = meter.create_histogram("openlet.leta.inbox.age", unit="s")


class Inbox(AgentMiddleware[State, "Context"]):
    state_schema = State

    def __init__(self, db: Pool, agent: UUID, root: bool) -> None:
        self.db, self.agent, self.root = db, agent, root

    async def abefore_model(
        self, state: State, runtime: Runtime[Context]
    ) -> dict[str, object] | None:
        rows = await pending(
            self.db,
            self.agent,
            state.get("inbox_cursor", 0),
            root=self.root,
            silent_after=state.get("silent_cursor", 0),
        )
        if not rows:
            return None
        ctx = runtime.context
        await name_users(ctx.services.internal, rows)
        async with self.db.connection() as conn:
            await conn.execute(
                "UPDATE agent_messages SET processing_run_id=%s WHERE recipient_agent_id=%s AND id=ANY(%s)",
                (ctx.run_id, self.agent, [row["id"] for row in rows]),
            )
        from .. import events

        for user in {
            cast(UUID, row["source_id"]) for row in rows if row["source_kind"] == "user"
        }:
            await events.changed(
                ctx.services.redis, ctx.leta_id, "messages", ctx.id, user
            )
        if any(row["source_kind"] in ("user", "hitl") for row in rows):
            runtime.context.filesystem.discovered = 0
        last = cast(int, rows[-1]["seq"])
        labels = {"agent_role": "leta" if self.root else "leti"}
        inbox_count.add(len(rows), {**labels, "direction": "consumed"})
        now = datetime.now(timezone.utc)
        for row in rows:
            inbox_age.record(
                (now - cast(datetime, row["created_at"])).total_seconds(), labels
            )
        return {
            "messages": [
                HumanMessage(
                    id=str(stable(self.agent, f"inbox/{last}")),
                    content=input_batch(rows, root=self.root),
                    additional_kwargs={"openlet": input_data(rows, root=self.root)},
                )
            ],
            "inbox_cursor": max(
                (cast(int, r["seq"]) for r in rows if not r.get("silent")),
                default=state.get("inbox_cursor", 0),
            ),
            "silent_cursor": max(
                (cast(int, r["seq"]) for r in rows if r.get("silent")),
                default=state.get("silent_cursor", 0),
            ),
        }
