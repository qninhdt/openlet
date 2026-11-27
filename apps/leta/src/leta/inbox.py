from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from openlet_sdk.config import JSON
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field
from temporalio.client import Client as TemporalClient

from .activity import ActivityEmitter
from .db import Pool, hydrate
from .hitl.models import (
    ApprovalPayload,
    ApprovalResponse,
    AskPayload,
    AskResponse,
    HitlOutcome,
)

type InboxKind = Literal[
    "channel", "reaction", "agent", "hitl", "schedule", "notification"
]
type DeliveryState = Literal["pending", "previewed", "delivered"]


class InboxSender(BaseModel):
    type: Literal["user", "agent", "system"]
    id: str
    name: str = ""
    handle: str = ""


class InboxAttachment(BaseModel):
    storage_id: str = ""
    node_id: str = ""
    name: str = ""
    media_type: str = ""
    kind: str = "file"
    size_bytes: int = 0


class InboxMetadata(BaseModel):
    """Typed superset of inbox_items.metadata across channel/schedule/hitl/reaction/notification."""

    model_config = ConfigDict(extra="allow")

    # channel / chat
    message_id: str = ""
    reply_to_message_id: str | None = None
    seq: int | None = None
    # schedule
    schedule_id: str = ""
    title: str = ""
    scheduled_for: str | None = None
    # hitl
    request_id: str = ""
    type: str = ""
    status: str = ""
    payload: AskPayload | ApprovalPayload | dict[str, JSON] | None = None
    response: AskResponse | ApprovalResponse | dict[str, JSON] | str | None = None
    outcome: HitlOutcome | str | None = None
    # notification
    event: str = ""
    error: str = ""
    subagent_handle: str = ""
    subagent_name: str = ""
    subagent_id: str = ""
    # reaction
    target_message_id: str = ""
    emoji: str = ""
    action: str = "added"


class InboxRecord(BaseModel):
    seq: int
    kind: InboxKind
    channel: str | None = None
    reply_address: str | None = None
    sender: InboxSender
    content: str = ""
    attachments: list[InboxAttachment] = Field(default_factory=list[InboxAttachment])
    metadata: InboxMetadata = Field(default_factory=InboxMetadata)
    silent: bool = False
    delivery_state: DeliveryState = "pending"
    created_at: datetime


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

    async def fetch_pending(
        self, agent_id: UUID, *, include_previewed: bool
    ) -> list[InboxRecord]:
        async with self.db.connection() as conn:
            if include_previewed:
                rows = await (
                    await conn.execute(
                        """
                        SELECT seq, kind, channel, reply_address, sender, content,
                               attachments, metadata, silent, delivery_state, created_at
                        FROM inbox_items
                        WHERE agent_id = %s AND delivery_state IN ('pending', 'previewed')
                        ORDER BY seq ASC
                        """,
                        (agent_id,),
                    )
                ).fetchall()
            else:
                rows = await (
                    await conn.execute(
                        """
                        SELECT seq, kind, channel, reply_address, sender, content,
                               attachments, metadata, silent, delivery_state, created_at
                        FROM inbox_items
                        WHERE agent_id = %s AND delivery_state = 'pending'
                        ORDER BY seq ASC
                        """,
                        (agent_id,),
                    )
                ).fetchall()
        return [hydrate(r, InboxRecord) for r in rows]

    async def mark_delivery_states(
        self,
        agent_id: UUID,
        *,
        delivered_seqs: list[int],
        previewed_seqs: list[int],
    ) -> None:
        if not delivered_seqs and not previewed_seqs:
            return
        async with self.db.connection() as conn, conn.transaction():
            if delivered_seqs:
                await conn.execute(
                    """
                    UPDATE inbox_items
                    SET delivery_state = 'delivered'
                    WHERE agent_id = %s AND seq = ANY(%s)
                    """,
                    (agent_id, delivered_seqs),
                )
            if previewed_seqs:
                await conn.execute(
                    """
                    UPDATE inbox_items
                    SET delivery_state = 'previewed'
                    WHERE agent_id = %s AND seq = ANY(%s)
                    """,
                    (agent_id, previewed_seqs),
                )

    async def has_pending(self, agent_id: UUID) -> bool:
        async with self.db.connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT 1
                    FROM inbox_items
                    WHERE agent_id = %s AND delivery_state = 'pending'
                    LIMIT 1
                    """,
                    (agent_id,),
                )
            ).fetchone()
        return row is not None

    async def mark_channel_delivered(self, agent_id: UUID, reply_address: str) -> None:
        async with self.db.connection() as conn:
            await conn.execute(
                """
                UPDATE inbox_items
                SET delivery_state = 'delivered'
                WHERE agent_id = %s AND reply_address = %s AND delivery_state = 'previewed'
                """,
                (agent_id, reply_address),
            )

    async def compute_wake_cursors(
        self, agent_id: UUID, final_cursor: int
    ) -> tuple[int, int]:
        async with self.db.connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT
                        COALESCE(MAX(seq), 0) AS latest_wake_seq,
                        MIN(seq) FILTER (WHERE delivery_state IN ('pending', 'previewed')) AS min_undelivered
                    FROM inbox_items
                    WHERE agent_id = %s AND NOT silent
                    """,
                    (agent_id,),
                )
            ).fetchone()
        latest_wake_seq = int(row["latest_wake_seq"]) if row else 0
        min_undelivered = row["min_undelivered"] if row else None
        if min_undelivered is not None:
            reported_cursor = min(final_cursor, int(min_undelivered) - 1)
        else:
            reported_cursor = max(final_cursor, latest_wake_seq)
        return reported_cursor, latest_wake_seq
