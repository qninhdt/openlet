from __future__ import annotations

from uuid import UUID

from ..db import Pool
from ..inbox import InboxGateway, InboxItem, InboxSender
from .base import (
    CallerContext,
    ChannelError,
    ChannelMessage,
    ChannelSummary,
    OutboundMessage,
    OutboundReceipt,
)


class InternalAgentAdapter:
    """Direct peer-to-peer IPC between Root Leta and subagents within the same leta_id."""

    scheme = "agent"

    def __init__(self, db: Pool, inbox: InboxGateway) -> None:
        self.db = db
        self.inbox = inbox

    async def _list_active_peers(
        self, caller: CallerContext
    ) -> list[dict[str, object]]:
        async with self.db.connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT id, handle, name, title, depth
                    FROM agents
                    WHERE leta_id = %s AND state = 'active' AND id <> %s
                    ORDER BY depth ASC, created_at ASC
                    """,
                    (caller.leta_id, caller.agent_id),
                )
            ).fetchall()
        return [dict(r) for r in rows]

    async def resolve_target(
        self, caller: CallerContext, target: str
    ) -> dict[str, object] | None:
        cleaned = target.strip().removeprefix("agent:").lstrip("@").strip()
        if not cleaned:
            return None
        uid: UUID | None = None
        try:
            uid = UUID(cleaned)
        except ValueError:
            uid = None
        low = cleaned.lower()
        async with self.db.connection() as conn:
            if uid is not None:
                row = await (
                    await conn.execute(
                        """
                        SELECT id, handle, name, title
                        FROM agents
                        WHERE leta_id = %s AND id = %s AND state = 'active'
                        LIMIT 1
                        """,
                        (caller.leta_id, uid),
                    )
                ).fetchone()
            else:
                row = await (
                    await conn.execute(
                        """
                        SELECT id, handle, name, title
                        FROM agents
                        WHERE leta_id = %s AND lower(handle) = %s AND state = 'active'
                        LIMIT 1
                        """,
                        (caller.leta_id, low),
                    )
                ).fetchone()
        return dict(row) if row is not None else None

    async def send(
        self,
        caller: CallerContext,
        target: str,
        msg: OutboundMessage,
        idempotency_key: UUID,
    ) -> OutboundReceipt:
        row = await self.resolve_target(caller, target)
        if row is None:
            peers = await self._list_active_peers(caller)
            if peers:
                opts = ", ".join(
                    f"agent:{p['handle']} ({p['name']})" for p in peers[:10]
                )
                raise ChannelError(
                    f"Active agent {target!r} not found in this Leta tree. Available agents: {opts}"
                )
            raise ChannelError(
                f"Active agent {target!r} not found in this Leta tree (no other active agents)."
            )
        target_id = UUID(str(row["id"]))
        handle = str(row["handle"])
        if target_id == caller.agent_id:
            raise ChannelError("Cannot send an internal message to yourself.")

        result = await self.inbox.deliver(
            InboxItem(
                agent_id=target_id,
                idempotency_key=f"agent:{idempotency_key}",
                kind="agent",
                channel="agent",
                reply_address=f"agent:{caller.handle}",
                sender=InboxSender(
                    type="agent",
                    id=str(caller.agent_id),
                    name=caller.name,
                    handle=caller.handle,
                ),
                content=msg.content,
                metadata={"from_handle": caller.handle},
            )
        )
        if not result.delivered:
            raise ChannelError(f"Agent {handle!r} is no longer active.")
        return OutboundReceipt(
            channel="agent",
            target=handle,
            message_id=str(idempotency_key),
            seq=result.seq,
            recipient={
                "kind": "agent",
                "id": str(target_id),
                "name": str(row["name"]),
            },
        )

    async def react(
        self, caller: CallerContext, target: str, message_id: str, emoji: str
    ) -> None:
        raise ChannelError("Reactions are not supported on internal agent channels.")

    async def read_history(
        self,
        caller: CallerContext,
        target: str,
        *,
        before_seq: int | None = None,
        limit: int = 20,
        query: str = "",
    ) -> list[ChannelMessage]:
        return []

    async def list_channels(
        self, caller: CallerContext, *, query: str = "", limit: int = 20
    ) -> list[ChannelSummary]:
        rows = await self._list_active_peers(caller)
        needle = query.strip().lstrip("@").lower()
        out: list[ChannelSummary] = []
        for r in rows:
            handle = str(r["handle"])
            name = str(r["name"])
            if needle and needle not in handle.lower() and needle not in name.lower():
                continue
            out.append(
                ChannelSummary(
                    address=f"agent:{handle}",
                    channel="agent",
                    kind="agent",
                    title=f"{name} ({r['title']})" if r["title"] else name,
                    handle=handle,
                )
            )
        return out[: max(1, min(limit, 50))]

    async def set_typing(
        self, caller: CallerContext, target: str, active: bool
    ) -> None:
        return

    async def mark_read(self, caller: CallerContext, target: str, seq: int) -> None:
        return None
