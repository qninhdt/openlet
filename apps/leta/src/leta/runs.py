from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from openlet_sdk.config import JSON, ReasoningEffort
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .activity import ActivityEmitter, ActivityType
from .db import Pool, hydrate


@dataclass(frozen=True, slots=True)
class RunOutcome:
    inbox_cursor: int
    latest_wake_seq: int


class AgentRuntimeRecord(BaseModel):
    id: UUID
    leta_id: UUID
    parent_agent_id: UUID | None = None
    depth: int = 0
    name: str
    title: str
    description: str = ""
    handle: str
    custom_instructions: str = ""
    model_id: str | None = None
    reasoning_effort: ReasoningEffort = None
    state: str = "active"
    workspace_id: UUID
    storage_id: UUID
    parent_handle: str | None = None

    @field_validator("description", "custom_instructions", mode="before")
    @classmethod
    def _none_to_empty(cls, v: object) -> object:
        return "" if v is None else v


class MessageEventData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = ""
    reasoning: str | None = None


class ToolCallEventData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "tool"
    args: dict[str, JSON] = Field(default_factory=dict[str, JSON])
    tool_call_id: str = ""


class ToolResultEventData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = "tool"
    status: str = "ok"
    preview: str = ""
    content: str = ""
    tool_call_id: str = ""


class AgentMessageSender(BaseModel):
    model_config = ConfigDict(extra="ignore")

    handle: str = ""
    name: str = ""


class AgentMessageEventData(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    sender: AgentMessageSender | None = Field(default=None, alias="from")
    content: str = ""


class InboxBatchItemSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    preview: str = ""


class InboxReceivedEventData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[InboxBatchItemSummary] = Field(
        default_factory=list[InboxBatchItemSummary]
    )


class RunFinishedEventData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = "done"
    error_code: str | None = None


class ActivityEventRecord(BaseModel):
    seq: int
    type: ActivityType
    data: dict[str, JSON] = Field(default_factory=dict[str, JSON])
    created_at: datetime


async def load_agent_runtime_record(db: Pool, agent_id: UUID) -> AgentRuntimeRecord:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                """
                SELECT a.id, a.leta_id, a.parent_agent_id, a.depth, a.name, a.title,
                       a.description, a.handle, a.custom_instructions, a.model_id,
                       a.reasoning_effort, a.state, l.workspace_id, l.storage_id,
                       p.handle AS parent_handle
                FROM agents a
                JOIN letas l ON l.id = a.leta_id
                LEFT JOIN agents p ON p.id = a.parent_agent_id
                WHERE a.id = %s
                """,
                (agent_id,),
            )
        ).fetchone()
    if row is None:
        raise LookupError(f"agent {agent_id} not found")
    return hydrate(row, AgentRuntimeRecord)


async def start_run(db: Pool, run_id: UUID, agent_id: UUID) -> int:
    """Upsert running run row and return the lowest pending/previewed inbox seq."""
    async with db.connection() as conn:
        trigger_row = await (
            await conn.execute(
                """
                SELECT COALESCE(MIN(seq), 0) AS trigger_seq
                FROM inbox_items
                WHERE agent_id = %s AND delivery_state IN ('pending', 'previewed')
                """,
                (agent_id,),
            )
        ).fetchone()
        trigger_seq = int(trigger_row["trigger_seq"]) if trigger_row else 0
        await conn.execute(
            """
            INSERT INTO runs(id, agent_id, status, heartbeat_at)
            VALUES (%s, %s, 'running', now())
            ON CONFLICT (id) DO UPDATE SET heartbeat_at = now()
            """,
            (run_id, agent_id),
        )
    return trigger_seq


async def touch_run_heartbeat(db: Pool, run_id: UUID) -> None:
    async with db.connection() as conn:
        await conn.execute(
            "UPDATE runs SET heartbeat_at = now() WHERE id = %s",
            (run_id,),
        )


async def record_run_usage(
    db: Pool,
    run_id: UUID,
    *,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
    cost_usd: float,
    llm_calls: int,
) -> None:
    async with db.connection() as conn:
        await conn.execute(
            """
            UPDATE runs
            SET input_tokens = input_tokens + %s,
                cached_input_tokens = cached_input_tokens + %s,
                output_tokens = output_tokens + %s,
                reasoning_tokens = reasoning_tokens + %s,
                cost_usd = cost_usd + %s,
                llm_calls = llm_calls + %s,
                heartbeat_at = now()
            WHERE id = %s
            """,
            (
                input_tokens,
                cached_input_tokens,
                output_tokens,
                reasoning_tokens,
                cost_usd,
                llm_calls,
                run_id,
            ),
        )


async def finish_run(
    db: Pool,
    activity: ActivityEmitter,
    *,
    run_id: UUID,
    agent_id: UUID,
    status: Literal["completed", "failed", "cancelled"],
    error_code: str | None,
) -> None:
    async with db.connection() as conn:
        row = await (
            await conn.execute(
                """
                UPDATE runs
                SET status = %s,
                    finished_at = coalesce(finished_at, now()),
                    error_code = coalesce(%s, error_code)
                WHERE id = %s AND status = 'running'
                RETURNING id, error_code, input_tokens, cached_input_tokens, output_tokens,
                          reasoning_tokens, cost_usd, llm_calls
                """,
                (status, error_code, run_id),
            )
        ).fetchone()
        agent = await (
            await conn.execute("SELECT leta_id FROM agents WHERE id = %s", (agent_id,))
        ).fetchone()
    if row is not None and agent is not None:
        await activity.emit(
            leta_id=UUID(str(agent["leta_id"])),
            agent_id=agent_id,
            run_id=run_id,
            event_type="run.finished",
            data={
                "status": status,
                "error_code": row["error_code"],
                "input_tokens": int(row["input_tokens"]),
                "cached_input_tokens": int(row["cached_input_tokens"]),
                "output_tokens": int(row["output_tokens"]),
                "reasoning_tokens": int(row["reasoning_tokens"]),
                "cost_usd": float(row["cost_usd"]),
                "llm_calls": int(row["llm_calls"]),
            },
        )


async def list_recent_activity(
    db: Pool, agent_id: UUID, limit: int
) -> list[ActivityEventRecord]:
    async with db.connection() as conn:
        rows = await (
            await conn.execute(
                """
                SELECT seq, type, data, created_at
                FROM activity_events
                WHERE agent_id = %s
                ORDER BY seq DESC
                LIMIT %s
                """,
                (agent_id, limit),
            )
        ).fetchall()
    return [hydrate(r, ActivityEventRecord) for r in rows]
