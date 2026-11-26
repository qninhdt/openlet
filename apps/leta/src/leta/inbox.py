from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from openlet_sdk.config import JSON
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field
from temporalio.client import Client as TemporalClient

from .activity import ActivityEmitter
from .db import Pool

type InboxKind = Literal["channel", "agent", "hitl", "schedule", "notification"]


class InboxSender(BaseModel):
    type: Literal["user", "agent", "system"]
    id: str
    name: str = ""
    handle: str = ""


class InboxItem(BaseModel):
    agent_id: UUID
    idempotency_key: str = Field(min_length=1)
    kind: InboxKind
    channel: str | None = None
    reply_address: str | None = None
    sender: InboxSender
    content: str
    attachments: list[dict[str, JSON]] = Field(default_factory=list[dict[str, JSON]])
    metadata: dict[str, JSON] = Field(default_factory=dict[str, JSON])
    silent: bool = False


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    delivered: bool
    skipped: bool
    seq: int | None


class InboxGateway:
    """DB-first unified mailbox converging channels, subagents, HITL, and schedules."""

    def __init__(
        self,
        *,
        db: Pool,
        temporal: TemporalClient | None,
        orchestration_queue: str,
        runtime_queue: str = "openlet-leta-runtime",
        run_timeout_seconds: int = 7200,
        heartbeat_timeout_seconds: int = 15,
        activity: ActivityEmitter | None = None,
    ) -> None:
        self.db = db
        self.temporal = temporal
        self.orchestration_queue = orchestration_queue
        self.runtime_queue = runtime_queue
        self.run_timeout_seconds = run_timeout_seconds
        self.heartbeat_timeout_seconds = heartbeat_timeout_seconds
        self.activity = activity

    async def deliver(self, item: InboxItem) -> DeliveryResult:
        async with self.db.connection() as conn, conn.transaction():
            agent = await (
                await conn.execute(
                    """
                    SELECT a.id, a.leta_id, a.state, l.state AS leta_state
                    FROM agents a
                    JOIN letas l ON l.id = a.leta_id
                    WHERE a.id = %s
                    FOR UPDATE OF a
                    """,
                    (item.agent_id,),
                )
            ).fetchone()
            if (
                agent is None
                or agent["state"] != "active"
                or agent["leta_state"] != "active"
            ):
                return DeliveryResult(delivered=False, skipped=True, seq=None)

            existing = await (
                await conn.execute(
                    "SELECT seq FROM inbox_items WHERE agent_id = %s AND idempotency_key = %s",
                    (item.agent_id, item.idempotency_key),
                )
            ).fetchone()
            if existing is not None:
                seq = int(existing["seq"])
                created = False
            else:
                row = await (
                    await conn.execute(
                        "UPDATE agents SET inbox_seq = inbox_seq + 1 WHERE id = %s RETURNING inbox_seq",
                        (item.agent_id,),
                    )
                ).fetchone()
                assert row is not None
                seq = int(row["inbox_seq"])
                await conn.execute(
                    """
                    INSERT INTO inbox_items(
                        agent_id, seq, idempotency_key, kind, channel,
                        reply_address, sender, content, attachments, metadata, silent
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        item.agent_id,
                        seq,
                        item.idempotency_key,
                        item.kind,
                        item.channel,
                        item.reply_address,
                        Jsonb(item.sender.model_dump()),
                        item.content,
                        Jsonb(item.attachments),
                        Jsonb(item.metadata),
                        item.silent,
                    ),
                )
                created = True
            leta_id = UUID(str(agent["leta_id"]))

        if not item.silent and self.temporal is not None:
            from .orchestration.agent_workflow import AgentWorkflow, AgentWorkflowState

            await self.temporal.start_workflow(
                AgentWorkflow.run,
                AgentWorkflowState(
                    agent_id=item.agent_id,
                    leta_id=leta_id,
                    is_root=(item.agent_id == leta_id),
                    runtime_queue=self.runtime_queue,
                    run_timeout_seconds=self.run_timeout_seconds,
                    heartbeat_timeout_seconds=self.heartbeat_timeout_seconds,
                ),
                id=f"agent/{item.agent_id}",
                task_queue=self.orchestration_queue,
                start_signal="wake",
                start_signal_args=[seq],
            )

        if created and item.kind == "agent" and self.activity is not None:
            await self.activity.emit(
                leta_id=leta_id,
                agent_id=item.agent_id,
                event_type="activity.agent_message",
                data={
                    "inbox_seq": seq,
                    "from": item.sender.model_dump(),
                    "reply_address": item.reply_address,
                    "content": item.content,
                },
            )

        return DeliveryResult(delivered=True, skipped=False, seq=seq)
