"""Channel adapter protocol, domain errors, and outbound/inbound message value objects."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from openlet_sdk.types import JSON

_EMPTY_JSON_MAP: Mapping[str, JSON] = MappingProxyType({})


class ChannelError(ValueError):
    """Domain error raised by channel adapters and router for invalid targets or operations."""


@dataclass(frozen=True, slots=True)
class OutboundAttachment:
    """File or media attachment included in an outbound or historical message."""

    storage_id: str
    node_id: str
    kind: str = "file"
    name: str = ""
    media_type: str = ""
    size_bytes: int = 0


@dataclass(frozen=True, slots=True)
class OutboundMention:
    """User, agent, file, or folder mention attached to an outbound message."""

    kind: str  # "user" | "agent" | "file" | "folder"
    id: str = ""
    storage_id: str | None = None
    node_id: str | None = None
    label: str = ""


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """Normalized outbound message payload passed to a ChannelAdapter."""

    content: str
    attachments: Sequence[OutboundAttachment] = ()
    mentions: Sequence[OutboundMention] = ()
    reply_to_id: str | None = None
    metadata: Mapping[str, JSON] = _EMPTY_JSON_MAP


@dataclass(frozen=True, slots=True)
class OutboundRecipient:
    """Resolved recipient identity returned in an OutboundReceipt."""

    kind: Literal["agent", "user", "box"]
    id: str
    name: str | None = None

    def to_json(self) -> dict[str, JSON]:
        """Serialize the recipient into a JSON-compatible dictionary."""
        out: dict[str, JSON] = {"kind": self.kind, "id": self.id}
        if self.name is not None:
            out["name"] = self.name
        return out


@dataclass(frozen=True, slots=True)
class OutboundReceipt:
    """Delivery receipt returned after sending a message via a ChannelAdapter."""

    channel: str
    target: str
    message_id: str
    seq: int | None = None
    recipient: OutboundRecipient | None = None


@dataclass(frozen=True, slots=True)
class ChannelReaction:
    """Reaction recorded on a channel message."""

    actor_type: str
    actor_id: str
    emoji: str


@dataclass(frozen=True, slots=True)
class ChannelMember:
    """Participant entry in a channel summary."""

    actor_type: str
    actor_id: str
    role: str


@dataclass(frozen=True, slots=True)
class ChannelMessage:
    """Normalized message record returned from channel history queries."""

    id: str
    seq: int | None
    sender_type: str
    sender_id: str
    content: str
    created_at: str
    reply_to_id: str | None = None
    attachments: Sequence[OutboundAttachment] = ()
    reactions: Sequence[ChannelReaction] = ()


@dataclass(frozen=True, slots=True)
class ChannelSummary:
    """Discovery summary describing a reachable conversation or peer agent."""

    address: str
    channel: str
    kind: str
    title: str
    handle: str | None = None
    unread_count: int = 0
    last_message_snippet: str = ""
    members: Sequence[ChannelMember] = ()


@dataclass(frozen=True, slots=True)
class PlainTargetMatch:
    """Candidate target resolved from an unprefixed handle or display query."""

    target: str
    address: str
    label: str


@dataclass(frozen=True, slots=True)
class CallerContext:
    """Identity and permissions of the agent invoking a channel operation."""

    workspace_id: UUID
    leta_id: UUID
    agent_id: UUID
    handle: str
    name: str
    is_root: bool


class ChannelAdapter(Protocol):
    """Protocol implemented by transport adapters (chat, internal agent IPC)."""

    scheme: str

    async def resolve_uuid_target(
        self, caller: CallerContext, raw_id: str
    ) -> str | None:
        """Resolve a bare UUID string to a target identifier if owned by this adapter."""
        ...

    async def resolve_plain_targets(
        self, caller: CallerContext, query: str
    ) -> list[PlainTargetMatch]:
        """Return matching targets for an unprefixed handle or name query."""
        ...

    async def send(
        self,
        caller: CallerContext,
        target: str,
        msg: OutboundMessage,
        idempotency_key: UUID,
    ) -> OutboundReceipt:
        """Send an outbound message idempotently to target."""
        ...

    async def react(
        self, caller: CallerContext, target: str, message_id: str, emoji: str
    ) -> None:
        """Attach an emoji reaction to message_id in target."""
        ...

    async def read_history(
        self,
        caller: CallerContext,
        target: str,
        *,
        before_seq: int | None = None,
        limit: int = 20,
        query: str = "",
    ) -> list[ChannelMessage]:
        """Fetch recent messages from target."""
        ...

    async def list_channels(
        self, caller: CallerContext, *, query: str = "", limit: int = 20
    ) -> list[ChannelSummary]:
        """List reachable destinations under this adapter."""
        ...

    async def set_typing(
        self,
        caller: CallerContext,
        target: str,
        active: bool,  # noqa: FBT001  # Positional arg kept for leta.runtime callers
    ) -> None:
        """Broadcast a typing indicator state for target."""
        ...

    async def mark_read(self, caller: CallerContext, target: str, seq: int) -> None:
        """Advance the read cursor for target up to seq."""
        ...
