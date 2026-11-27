from __future__ import annotations

from uuid import UUID, uuid5

from .base import (
    CallerContext,
    ChannelAdapter,
    ChannelError,
    ChannelMessage,
    ChannelSummary,
    OutboundMessage,
    OutboundReceipt,
)


def parse_address(to: str) -> tuple[str, str]:
    raw = to.strip()
    if ":" not in raw:
        raise ValueError(
            f"invalid destination {to!r}; expected '<scheme>:<target>' (e.g. 'chat:<conversation_id>' or 'agent:<handle>')"
        )
    scheme, target = raw.split(":", 1)
    scheme = scheme.strip().lower()
    target = target.strip()
    if not scheme or not target:
        raise ValueError(f"invalid destination {to!r}")
    return scheme, target


def outbound_idempotency_key(agent_id: UUID, tool_call_id: str) -> UUID:
    return uuid5(agent_id, tool_call_id)


class ChannelRouter:
    def __init__(self, adapters: list[ChannelAdapter]) -> None:
        self._adapters: dict[str, ChannelAdapter] = {a.scheme: a for a in adapters}

    async def resolve_destination(
        self, caller: CallerContext, to: str
    ) -> tuple[ChannelAdapter, str]:
        """Resolve prefixed or plain destinations (e.g. 'ethan', '<uuid>', 'chat:<id>', 'agent:<handle>')."""
        raw = to.strip()
        if not raw:
            raise ChannelError("Destination 'to' cannot be empty.")

        # 1. Explicit '<scheme>:<target>' (including convenience 'user:<handle|uuid>')
        if ":" in raw:
            scheme, target = raw.split(":", 1)
            scheme = scheme.strip().lower()
            target = target.strip()
            if scheme == "user" and target:
                scheme = "chat"
                target = f"user:{target}"
            if not caller.is_root and scheme != "agent":
                raise PermissionError(
                    "Subagents can only message peer agents via 'agent:<handle>' or a peer handle. "
                    "Report back to your parent agent instead."
                )
            adapter = self._adapters.get(scheme)
            if adapter is None:
                supported = ", ".join(sorted(self._adapters))
                raise ChannelError(
                    f"Unsupported channel scheme {scheme!r} (supported: {supported})."
                )
            if not target:
                raise ChannelError(f"Invalid destination {to!r}: missing target.")
            return adapter, target

        # 2. Unprefixed destination (bare UUID or plain handle, with optional stray '@')
        cleaned = raw.lstrip("@").strip()
        agent_adapter = self._adapters.get("agent")
        chat_adapter = self._adapters.get("chat")

        # Subagents only talk to agents in their own Leta tree.
        if not caller.is_root:
            if agent_adapter is None:
                raise ChannelError("Internal agent channel is unavailable.")
            return agent_adapter, cleaned

        # Bare UUID -> check own subagent tree first, otherwise treat as chat conversation UUID.
        try:
            UUID(cleaned)
            if agent_adapter is not None:
                found = await agent_adapter.resolve_uuid_target(caller, cleaned)
                if found is not None:
                    return agent_adapter, found
            if chat_adapter is not None:
                found = await chat_adapter.resolve_uuid_target(caller, cleaned)
                if found is not None:
                    return chat_adapter, found
        except ValueError:
            pass

        # Plain handle (e.g. 'ethan', 'nora', 'general', 'orion-analyst'):
        candidates: list[tuple[ChannelAdapter, str, str, str]] = []
        for adapter in (agent_adapter, chat_adapter):
            if adapter is None:
                continue
            for m in await adapter.resolve_plain_targets(caller, cleaned):
                candidates.append((adapter, m.target, m.address, m.label))

        if len(candidates) == 1:
            return candidates[0][0], candidates[0][1]

        if len(candidates) > 1:
            opts = ", ".join(f"'{addr}' ({lbl})" for _, _, addr, lbl in candidates)
            raise ChannelError(
                f"Destination {to!r} matches multiple targets. Specify one of: {opts}"
            )

        # Helpful miss message listing currently available targets.
        available = await self.list_channels(caller, limit=10)
        if available:
            hints = ", ".join(f"'{c.address}' ({c.title})" for c in available[:8])
            raise ChannelError(
                f"Destination {to!r} not found. Available channels/agents: {hints}. "
                "Call list_channels or list_members to find more."
            )
        raise ChannelError(
            f"Destination {to!r} not found. Call list_channels or list_members to see valid handles."
        )

    async def send(
        self,
        caller: CallerContext,
        to: str,
        msg: OutboundMessage,
        *,
        tool_call_id: str,
    ) -> OutboundReceipt:
        adapter, target = await self.resolve_destination(caller, to)
        key = outbound_idempotency_key(caller.agent_id, tool_call_id)
        return await adapter.send(caller, target, msg, key)

    async def react(
        self, caller: CallerContext, to: str, message_id: str, emoji: str
    ) -> None:
        if not caller.is_root:
            raise PermissionError("Only the Root Leta can react to external messages.")
        adapter, target = await self.resolve_destination(caller, to)
        await adapter.react(caller, target, message_id, emoji)

    async def read_history(
        self,
        caller: CallerContext,
        to: str,
        *,
        before_seq: int | None = None,
        limit: int = 20,
        query: str = "",
    ) -> list[ChannelMessage]:
        adapter, target = await self.resolve_destination(caller, to)
        return await adapter.read_history(
            caller, target, before_seq=before_seq, limit=limit, query=query
        )

    async def list_channels(
        self, caller: CallerContext, *, query: str = "", limit: int = 20
    ) -> list[ChannelSummary]:
        out: list[ChannelSummary] = []
        for scheme, adapter in self._adapters.items():
            if not caller.is_root and scheme != "agent":
                continue
            out.extend(await adapter.list_channels(caller, query=query, limit=limit))
        return out[:limit]

    async def set_typing(self, caller: CallerContext, to: str, active: bool) -> None:
        if not caller.is_root:
            return
        try:
            adapter, target = await self.resolve_destination(caller, to)
            await adapter.set_typing(caller, target, active)
        except Exception:
            return

    async def mark_read(self, caller: CallerContext, to: str, seq: int) -> None:
        if not caller.is_root or seq <= 0:
            return
        try:
            adapter, target = await self.resolve_destination(caller, to)
            await adapter.mark_read(caller, target, seq)
        except Exception:
            return
