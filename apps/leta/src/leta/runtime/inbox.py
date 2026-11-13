from __future__ import annotations

import json
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
from ..messages import inbox_count, input_batch, pending

if TYPE_CHECKING:
    from .tools import Context


class State(AgentState[JSON]):
    inbox_cursor: NotRequired[int]


meter = metrics.get_meter("openlet.leta")
inbox_age = meter.create_histogram("openlet.leta.inbox.age", unit="s")


class Inbox(AgentMiddleware[State, "Context"]):
    state_schema = State

    def __init__(self, db: Pool, agent: UUID, root: bool) -> None:
        self.db, self.agent, self.root = db, agent, root

    async def abefore_model(
        self, state: State, runtime: Runtime[Context]
    ) -> dict[str, object] | None:
        rows = await pending(self.db, self.agent, state.get("inbox_cursor", 0))
        if not rows:
            return None
        last = cast(int, rows[-1]["seq"])
        labels = {"agent_role": "root" if self.root else "leti"}
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
                    content=json.dumps(
                        input_batch(rows, root=self.root), ensure_ascii=False
                    ),
                )
            ],
            "inbox_cursor": last,
        }
