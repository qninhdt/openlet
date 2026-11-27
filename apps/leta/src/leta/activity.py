from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import httpx
from openlet_sdk.config import JSON
from psycopg.types.json import Jsonb

from .db import Pool

logger = logging.getLogger(__name__)

type StreamDeltaKind = Literal[
    "stream.thinking_delta", "stream.text_delta", "stream.tool_args_delta"
]

type ActivityType = Literal[
    "run.started",
    "run.finished",
    "activity.inbox_received",
    "activity.message",
    "activity.tool_call",
    "activity.tool_result",
    "activity.compacted",
    "activity.agent_message",
    "subagent.spawned",
    "subagent.stopped",
    "hitl.updated",
    "schedule.updated",
]


def activity_channel(leta_id: UUID | str) -> str:
    return f"leta:activity:{leta_id}"


def leta_user_channel(user_id: UUID | str) -> str:
    return f"leta:user#{user_id}"


class CentrifugoPublisher:
    def __init__(self, *, api_url: str, api_key: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._client = (
            httpx.AsyncClient(
                base_url=self._api_url,
                headers={"X-API-Key": api_key} if api_key else {},
                timeout=3.0,
                limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
            )
            if self._api_url
            else None
        )

    async def close(self) -> None:
        for task in list(self._bg_tasks):
            task.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
            self._bg_tasks.clear()
        if self._client is not None:
            await self._client.aclose()

    def broadcast_soon(
        self,
        channels: list[str],
        event_type: str,
        data: Mapping[str, JSON],
        *,
        skip_history: bool = False,
    ) -> None:
        if self._client is None or not channels:
            return
        if len(self._bg_tasks) >= 256:
            return
        task = asyncio.create_task(
            self.broadcast(channels, event_type, data, skip_history=skip_history)
        )
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def publish(
        self,
        channel: str,
        event_type: str,
        data: Mapping[str, JSON],
        *,
        skip_history: bool = False,
    ) -> None:
        await self.broadcast([channel], event_type, data, skip_history=skip_history)

    async def broadcast(
        self,
        channels: list[str],
        event_type: str,
        data: Mapping[str, JSON],
        *,
        skip_history: bool = False,
    ) -> None:
        if self._client is None or not channels:
            return
        try:
            resp = await self._client.post(
                "/broadcast",
                json={
                    "channels": list(dict.fromkeys(channels)),
                    "data": {"type": event_type, "data": data},
                    "skip_history": skip_history,
                },
            )
            if resp.status_code >= 300:
                logger.warning(
                    "centrifugo broadcast status %s: %s",
                    resp.status_code,
                    resp.text[:300],
                )
        except Exception:
            logger.warning("centrifugo broadcast failed", exc_info=True)


class ActivityEmitter:
    def __init__(self, db: Pool, centrifugo: CentrifugoPublisher) -> None:
        self.db = db
        self.centrifugo = centrifugo

    async def emit(
        self,
        *,
        leta_id: UUID,
        agent_id: UUID,
        event_type: ActivityType,
        data: Mapping[str, JSON],
        run_id: UUID | None = None,
        realtime_data: Mapping[str, JSON] | None = None,
        extra_channels: list[str] | None = None,
    ) -> int:
        async with self.db.connection() as conn, conn.transaction():
            row = await (
                await conn.execute(
                    "UPDATE agents SET activity_seq = activity_seq + 1 WHERE id = %s RETURNING activity_seq",
                    (agent_id,),
                )
            ).fetchone()
            if row is None:
                return 0
            seq = int(row["activity_seq"])
            await conn.execute(
                """
                INSERT INTO activity_events(agent_id, seq, run_id, type, data)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (agent_id, seq, run_id, event_type, Jsonb(data)),
            )

        payload: dict[str, JSON] = {
            "leta_id": str(leta_id),
            "agent_id": str(agent_id),
            "seq": seq,
            "run_id": str(run_id) if run_id is not None else None,
            "created_at": datetime.now(UTC).isoformat(),
            **(realtime_data if realtime_data is not None else data),
        }
        channels = [activity_channel(leta_id), *(extra_channels or [])]
        self.centrifugo.broadcast_soon(channels, event_type, payload)
        return seq

    async def publish_stream_delta(
        self,
        *,
        leta_id: UUID,
        agent_id: UUID,
        run_id: UUID,
        kind: StreamDeltaKind,
        delta: str,
        tool_call_id: str | None = None,
    ) -> None:
        if not delta:
            return
        payload: dict[str, JSON] = {
            "leta_id": str(leta_id),
            "agent_id": str(agent_id),
            "run_id": str(run_id),
            "delta": delta,
        }
        if tool_call_id is not None:
            payload["tool_call_id"] = tool_call_id
        self.centrifugo.broadcast_soon(
            [activity_channel(leta_id)], kind, payload, skip_history=True
        )


class StreamCoalescer:
    """Coalesces high-frequency LLM streaming token deltas every 50ms into Centrifugo publishes."""

    def __init__(
        self,
        emitter: ActivityEmitter,
        *,
        leta_id: UUID,
        agent_id: UUID,
        run_id: UUID,
        interval_seconds: float = 0.05,
    ) -> None:
        self._emitter = emitter
        self._leta_id = leta_id
        self._agent_id = agent_id
        self._run_id = run_id
        self._interval = interval_seconds
        self._buffers: dict[tuple[StreamDeltaKind, str | None], list[str]] = {}
        self._flush_task: asyncio.Task[None] | None = None

    def push(
        self,
        kind: StreamDeltaKind,
        delta: str,
        *,
        tool_call_id: str | None = None,
    ) -> None:
        if not delta:
            return
        key = (kind, tool_call_id)
        self._buffers.setdefault(key, []).append(delta)
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._delayed_flush())

    async def _delayed_flush(self) -> None:
        await asyncio.sleep(self._interval)
        await self.flush()

    async def flush(self) -> None:
        if not self._buffers:
            return
        pending = self._buffers
        self._buffers = {}
        for (kind, tool_call_id), chunks in pending.items():
            text = "".join(chunks)
            if not text:
                continue
            await self._emitter.publish_stream_delta(
                leta_id=self._leta_id,
                agent_id=self._agent_id,
                run_id=self._run_id,
                kind=kind,
                delta=text,
                tool_call_id=tool_call_id,
            )

    async def close(self) -> None:
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self.flush()
