"""Internal peer-to-peer agent messaging adapter backed by InboxGateway."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from leta.channels.base import (
    CallerContext,
    ChannelError,
    ChannelMessage,
    ChannelSummary,
    OutboundMessage,
    OutboundReceipt,
    OutboundRecipient,
    PlainTargetMatch,
)
from leta.inbox import InboxGateway, InboxItem, InboxMetadata, InboxSender

if TYPE_CHECKING:
    from leta.db import Pool


@dataclass(frozen=True, slots=True)
class _PeerAgent:
    id: UUID
    handle: str
    name: str
    title: str


class InternalAgentAdapter:
    """Direct peer-to-peer IPC between Root Leta and subagents within the same leta_id."""

    scheme = "agent"

    def __init__(self, db: Pool, inbox: InboxGateway) -> None:
        self.db = db
        self.inbox = inbox

    async def _list_active_peers(self, caller: CallerContext) -> list[_PeerAgent]:
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
        return [
            _PeerAgent(
                id=UUID(str(r["id"])),
                handle=str(r["handle"]),
                name=str(r["name"]),
                title=str(r["title"] or ""),
            )
            for r in rows
        ]

    async def resolve_target(
        self, caller: CallerContext, target: str
    ) -> _PeerAgent | None:
        """Resolve an active peer agent in the caller's Leta tree by UUID or handle."""
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
        if row is None:
            return None
        return _PeerAgent(
            id=UUID(str(row["id"])),
            handle=str(row["handle"]),
            name=str(row["name"]),
            title=str(row["title"] or ""),
        )

    async def resolve_uuid_target(
        self, caller: CallerContext, raw_id: str
    ) -> str | None:
        """Resolve a peer agent UUID to its handle if active in the caller's tree."""
        found = await self.resolve_target(caller, raw_id)
        return found.handle if found is not None else None

    async def resolve_plain_targets(
        self, caller: CallerContext, query: str
    ) -> list[PlainTargetMatch]:
        """Resolve an unprefixed handle query against active peer agents."""
        sub = await self.resolve_target(caller, query)
        if sub is None:
            return []
        return [
            PlainTargetMatch(
                target=sub.handle,
                address=f"agent:{sub.handle}",
                label=f"{sub.name} (subagent)",
            )
        ]

    async def send(
        self,
        caller: CallerContext,
        target: str,
        msg: OutboundMessage,
        idempotency_key: UUID,
    ) -> OutboundReceipt:
        """Deliver an internal message to a peer agent's inbox."""
        peer = await self.resolve_target(caller, target)
        if peer is None:
            peers = await self._list_active_peers(caller)
            if peers:
                opts = ", ".join(f"agent:{p.handle} ({p.name})" for p in peers[:10])
                raise ChannelError(
                    f"Active agent {target!r} not found in this Leta tree. Available agents: {opts}"
                )
            raise ChannelError(
                f"Active agent {target!r} not found in this Leta tree (no other active agents)."
            )
        if peer.id == caller.agent_id:
            raise ChannelError("Cannot send an internal message to yourself.")

        result = await self.inbox.deliver(
            InboxItem(
                agent_id=peer.id,
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
                metadata=InboxMetadata(from_handle=caller.handle),
            )
        )
        if not result.delivered:
            raise ChannelError(f"Agent {peer.handle!r} is no longer active.")
        return OutboundReceipt(
            channel="agent",
            target=peer.handle,
            message_id=str(idempotency_key),
            seq=result.seq,
            recipient=OutboundRecipient(
                kind="agent",
                id=str(peer.id),
                name=peer.name,
            ),
        )

    async def react(
        self, caller: CallerContext, target: str, message_id: str, emoji: str
    ) -> None:
        """Raise ChannelError since internal agent channels do not support reactions."""
        _ = (caller, target, message_id, emoji)
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
        """Return an empty list since internal agent IPC has no shared channel log."""
        _ = (caller, target, before_seq, limit, query)
        return []

    async def list_channels(
        self, caller: CallerContext, *, query: str = "", limit: int = 20
    ) -> list[ChannelSummary]:
        """List active peer agents reachable in the caller's Leta tree."""
        peers = await self._list_active_peers(caller)
        needle = query.strip().lstrip("@").lower()
        out: list[ChannelSummary] = []
        for p in peers:
            if (
                needle
                and needle not in p.handle.lower()
                and needle not in p.name.lower()
            ):
                continue
            out.append(
                ChannelSummary(
                    address=f"agent:{p.handle}",
                    channel="agent",
                    kind="agent",
                    title=f"{p.name} ({p.title})" if p.title else p.name,
                    handle=p.handle,
                )
            )
        return out[: max(1, min(limit, 50))]

    async def set_typing(
        self,
        caller: CallerContext,
        target: str,
        active: bool,  # noqa: FBT001  # Matches ChannelAdapter protocol for leta.runtime callers
    ) -> None:
        """No-op for internal agent IPC channels."""
        _ = (caller, target, active)

    async def mark_read(self, caller: CallerContext, target: str, seq: int) -> None:
        """No-op for internal agent IPC channels."""
        _ = (caller, target, seq)
