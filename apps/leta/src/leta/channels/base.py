from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from openlet_sdk.config import JSON


@dataclass(frozen=True, slots=True)
class OutboundAttachment:
    storage_id: str
    node_id: str
    kind: str = "file"
    name: str = ""
    media_type: str = ""
    size_bytes: int = 0


@dataclass(frozen=True, slots=True)
class OutboundMention:
    kind: str  # "user" | "agent" | "file" | "folder"
    id: str = ""
    storage_id: str | None = None
    node_id: str | None = None
    label: str = ""


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    content: str
    attachments: list[OutboundAttachment] = field(
        default_factory=list[OutboundAttachment]
    )
    mentions: list[OutboundMention] = field(default_factory=list[OutboundMention])
    reply_to_id: str | None = None
    metadata: dict[str, JSON] = field(default_factory=dict[str, JSON])


@dataclass(frozen=True, slots=True)
class OutboundReceipt:
    channel: str
    target: str
    message_id: str
    seq: int | None = None
    recipient: dict[str, JSON] | None = None


@dataclass(frozen=True, slots=True)
class ChannelMessage:
    id: str
    seq: int | None
    sender_type: str
    sender_id: str
    content: str
    created_at: str
    reply_to_id: str | None = None
    attachments: list[dict[str, JSON]] = field(default_factory=list[dict[str, JSON]])
    reactions: list[dict[str, JSON]] = field(default_factory=list[dict[str, JSON]])


@dataclass(frozen=True, slots=True)
class ChannelSummary:
    address: str
    channel: str
    kind: str
    title: str
    handle: str | None = None
    unread_count: int = 0
    last_message_snippet: str = ""
    members: list[dict[str, JSON]] = field(default_factory=list[dict[str, JSON]])


@dataclass(frozen=True, slots=True)
class CallerContext:
    workspace_id: UUID
    leta_id: UUID
    agent_id: UUID
    handle: str
    name: str
    is_root: bool


class ChannelAdapter(Protocol):
    scheme: str

    async def send(
        self,
        caller: CallerContext,
        target: str,
        msg: OutboundMessage,
        idempotency_key: UUID,
    ) -> OutboundReceipt: ...

    async def react(
        self, caller: CallerContext, target: str, message_id: str, emoji: str
    ) -> None: ...

    async def read_history(
        self,
        caller: CallerContext,
        target: str,
        *,
        before_seq: int | None = None,
        limit: int = 20,
        query: str = "",
    ) -> list[ChannelMessage]: ...

    async def list_channels(
        self, caller: CallerContext, *, query: str = "", limit: int = 20
    ) -> list[ChannelSummary]: ...

    async def set_typing(
        self, caller: CallerContext, target: str, active: bool
    ) -> None: ...

    async def mark_read(self, caller: CallerContext, target: str, seq: int) -> None: ...
