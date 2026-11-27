"""Messaging, reaction, channel-listing, and outbound link-normalization tools."""

from __future__ import annotations

import contextlib
import xml.sax.saxutils as sax
from time import monotonic
from typing import TYPE_CHECKING, Literal

import grpc
import regex as re
from langchain_core.tools import ToolException
from langgraph.prebuilt import ToolRuntime  # noqa: TC002  # Evaluated at runtime by LangGraph ToolNode.get_type_hints.
from pydantic import Field

from leta.channels.base import (
    CallerContext,
    OutboundAttachment,
    OutboundMention,
    OutboundMessage,
)
from leta.inbox import InboxSender
from leta.runtime.state import AgentState, RuntimeContext  # noqa: TC001  # Evaluated at runtime by LangGraph ToolNode.get_type_hints.
from leta.runtime.tools.base import ToolArgs, ToolResult, idempotency_key, make_tool
from leta.runtime.tools.files import missing_path_recovery, normalize_workspace_path

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from openlet_sdk.config import JSON

    from leta.filesystem.workspace import Filesystem

_MD_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)")
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_CITATION_RE = re.compile(r"\[(\d+)\](?!\()")


def validate_citations(content: str, sources: list[str]) -> None:
    """Validate 1-based [n] citations when sources are provided; ignore code blocks & allow bare [1] when sources=[]."""
    if not sources:
        return
    stripped = _INLINE_CODE_RE.sub("", _FENCED_CODE_RE.sub("", content))
    cited = {int(m.group(1)) for m in _CITATION_RE.finditer(stripped)}
    max_idx = len(sources)
    out_of_range = [i for i in sorted(cited) if i < 1 or i > max_idx]
    if out_of_range:
        raise ValueError(
            f"Citation index {out_of_range} out of range for {max_idx} source(s)."
        )
    uncited = [i for i in range(1, max_idx + 1) if i not in cited]
    if uncited:
        raise ValueError(
            f"Source(s) {uncited} were provided in sources but not cited as [n] in content."
        )


async def normalize_outbound_links(
    content: str, fs: Filesystem
) -> tuple[str, list[OutboundMention]]:
    """Rewrite workspace Markdown links [label](/shared/...) to canonical [label](/letfs/<sid>/<nid>)."""
    mentions: list[OutboundMention] = []
    matches = list(_MD_LINK_RE.finditer(content))
    if not matches:
        return content, mentions

    replacements: list[tuple[int, int, str]] = []
    for m in matches:
        label, href = m.group(1), m.group(2)
        if href.startswith(("http://", "https://", "mailto:", "#")):
            continue
        if href.startswith("/letfs/"):
            parts = [p for p in href.removeprefix("/letfs/").split("/") if p]
            if len(parts) >= 2:
                mentions.append(
                    OutboundMention(
                        kind="file",
                        id=parts[1],
                        storage_id=parts[0],
                        node_id=parts[1],
                        label=label,
                    )
                )
            continue
        if href.startswith(("/", "~")):
            try:
                ref = await fs.resolve_ref(href)
            except OSError, ValueError, grpc.aio.AioRpcError:
                continue
            if ref.storage_id and ref.node_id:
                canonical = f"/letfs/{ref.storage_id}/{ref.node_id}"
                replacements.append((m.start(), m.end(), f"[{label}]({canonical})"))
                mentions.append(
                    OutboundMention(
                        kind=ref.kind,
                        id=ref.node_id,
                        storage_id=ref.storage_id,
                        node_id=ref.node_id,
                        label=label,
                    )
                )

    if not replacements:
        return content, mentions
    out_parts: list[str] = []
    last = 0
    for s, e, repl in replacements:
        out_parts.append(content[last:s])
        out_parts.append(repl)
        last = e
    out_parts.append(content[last:])
    return "".join(out_parts), mentions


class RootSendMessageArgs(ToolArgs):
    """Input schema for root Leta ``send_message``."""

    to: str = Field(
        min_length=1,
        description=(
            "'chat:<conv_id>', plain handle ('ethan', 'general', 'orion-analyst'), "
            "prefixed handle ('chat:user:...', 'agent:...'), or conversation UUID."
        ),
    )
    content: str = Field(min_length=1)
    attachments: list[str] = Field(
        default_factory=list[str],
        max_length=20,
        description="Workspace paths to attach (required for /home files; link /shared or current /chat/<handle> inline).",
    )
    sources: list[str] = Field(
        default_factory=list[str],
        max_length=64,
        description="Ordered paths/URLs cited 1-to-1 as [1], [2] in content.",
    )
    reply_to_message_id: str | None = Field(
        default=None,
        description="Message UUID to quote-reply to.",
    )
    end_turn: bool = Field(
        default=True,
        description="End turn immediately after delivery with no extra LLM step (set false if more work/messages remain).",
    )


class SubagentSendMessageArgs(ToolArgs):
    """Input schema for subagent ``send_message``."""

    to: str = Field(
        min_length=1,
        description="Parent or sibling handle ('agent:<handle>' or plain handle) or UUID.",
    )
    content: str = Field(min_length=1)
    end_turn: bool = Field(
        default=True,
        description="End turn immediately after delivery (set false if more work remains).",
    )


class ReactMessageArgs(ToolArgs):
    """Input schema for ``react_message``."""

    to: str = Field(min_length=1, description="Conversation address or handle.")
    message_id: str = Field(min_length=1)
    emoji: str = Field(min_length=1, max_length=64)
    end_turn: bool = Field(
        default=False,
        description="End turn immediately if no further action is needed.",
    )


class ReadMessagesArgs(ToolArgs):
    """Input schema for ``read_messages``."""

    to: str = Field(
        min_length=1, description="Conversation address ('chat:<conv_id>') or handle."
    )
    before: int | None = Field(
        default=None,
        gt=0,
        description="Pass next_before from a previous call to page backwards.",
    )
    limit: int = Field(default=20, ge=1, le=100)
    query: str = ""


class ListChannelsArgs(ToolArgs):
    """Input schema for ``list_channels``."""

    query: str = ""
    limit: int = Field(default=20, ge=1, le=100)


def _caller(rt: RuntimeContext) -> CallerContext:
    return CallerContext(
        workspace_id=rt.workspace_id,
        leta_id=rt.leta_id,
        agent_id=rt.agent_id,
        handle=rt.handle,
        name=rt.agent_name,
        is_root=rt.is_root,
    )


def _format_sender_label(rt: RuntimeContext, sender_type: str, sender_id: str) -> str:
    stype: Literal["user", "agent", "system"] = (
        sender_type if sender_type in ("user", "agent", "system") else "system"
    )
    enriched = rt.fs.enrich_sender(InboxSender(type=stype, id=sender_id))
    handle = enriched.handle.lstrip("@").strip()
    name = enriched.name.strip()
    if handle and name:
        return f"{name} ({handle})"
    if handle:
        return handle
    if name:
        return name
    return f"{sender_type}:{sender_id}"


async def _resolve_outbound_attachments(
    rt: RuntimeContext, raw_atts: list[str]
) -> list[OutboundAttachment]:
    attachments: list[OutboundAttachment] = []
    for att_path in raw_atts:
        abs_att = normalize_workspace_path(att_path)
        try:
            ref = await rt.fs.resolve_ref(abs_att)
        except FileNotFoundError:
            _, err_msg = await missing_path_recovery(rt, abs_att, allow_alternate=False)
            raise ToolException(f"Cannot attach missing file: {err_msg}") from None
        if not ref.storage_id or not ref.node_id:
            raise ToolException(f"Cannot attach unresolved path: {att_path}")
        attachments.append(
            OutboundAttachment(
                storage_id=ref.storage_id,
                node_id=ref.node_id,
                kind=ref.kind,
                name=ref.name,
                media_type=ref.media_type,
                size_bytes=ref.size_bytes,
            )
        )
    return attachments


async def _resolve_outbound_sources(
    rt: RuntimeContext, sources: list[str]
) -> list[JSON]:
    resolved_sources: list[JSON] = []
    for src in sources:
        if src.startswith(("http://", "https://")):
            resolved_sources.append({"kind": "web", "url": src})
            continue
        try:
            ref = await rt.fs.resolve_ref(normalize_workspace_path(src))
            resolved_sources.append(
                {
                    "kind": ref.kind,
                    "path": ref.path,
                    "storage_id": ref.storage_id,
                    "node_id": ref.node_id,
                }
            )
        except OSError, ValueError, grpc.aio.AioRpcError:
            resolved_sources.append({"kind": "path", "path": src})
    return resolved_sources


async def _send_message_impl(
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
    to: str,
    content: str,
    raw_atts: list[str],
    sources: list[str],
    reply_to: str | None,
    end_turn: bool,
) -> ToolResult:
    rt = runtime.context
    caller = _caller(rt)
    msg_cfg = rt.services.settings.messaging
    if len(raw_atts) > msg_cfg.max_attachments:
        raise ToolException(f"Maximum {msg_cfg.max_attachments} attachments allowed.")
    if len(sources) > msg_cfg.max_sources:
        raise ToolException(f"Maximum {msg_cfg.max_sources} sources allowed.")
    try:
        validate_citations(content, sources)
    except ValueError as exc:
        raise ToolException(str(exc)) from None

    adapter, target = await rt.router.resolve_destination(caller, to)
    is_external = adapter.scheme != "agent"
    mentions: list[OutboundMention] = []
    attachments: list[OutboundAttachment] = []
    metadata: dict[str, JSON] = {}

    if is_external:
        content, mentions = await normalize_outbound_links(content, rt.fs)
        attachments = await _resolve_outbound_attachments(rt, raw_atts)
        if sources:
            metadata["sources"] = await _resolve_outbound_sources(rt, sources)

    receipt = await adapter.send(
        caller,
        target,
        OutboundMessage(
            content=content,
            attachments=attachments,
            mentions=mentions,
            reply_to_id=reply_to,
            metadata=metadata,
        ),
        idempotency_key=idempotency_key(runtime),
    )

    canonical_addr = f"{receipt.channel}:{receipt.target}"
    if is_external:
        rt.active_channels[canonical_addr] = monotonic()
        rt.active_channels[to] = monotonic()
        for addr in (canonical_addr, to):
            if addr in rt.active_typing:
                rt.active_typing.discard(addr)
                await rt.router.set_typing(caller, addr, active=False)

    artifact: dict[str, JSON] = {
        "to": canonical_addr,
        "message_id": receipt.message_id,
        "seq": receipt.seq,
        "end_turn": end_turn,
        "attachments": [
            {"storage_id": a.storage_id, "node_id": a.node_id, "name": a.name}
            for a in attachments
        ],
    }
    if receipt.recipient is not None:
        artifact["recipient"] = receipt.recipient.to_json()

    return (
        f"Delivered to {canonical_addr} (message_id={receipt.message_id})",
        artifact,
    )


async def handle_root_send_message(
    to: str,
    content: str,
    *,
    attachments: list[str] | None = None,
    sources: list[str] | None = None,
    reply_to_message_id: str | None = None,
    end_turn: bool = True,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Deliver a message from the root Leta to an external channel or internal agent."""
    return await _send_message_impl(
        runtime=runtime,
        to=to,
        content=content,
        raw_atts=attachments or [],
        sources=sources or [],
        reply_to=reply_to_message_id,
        end_turn=end_turn,
    )


async def handle_subagent_send_message(
    to: str,
    content: str,
    *,
    end_turn: bool = True,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Deliver a message from a subagent to its parent or sibling subagent."""
    return await _send_message_impl(
        runtime=runtime,
        to=to,
        content=content,
        raw_atts=[],
        sources=[],
        reply_to=None,
        end_turn=end_turn,
    )


async def handle_react_message(
    to: str,
    message_id: str,
    emoji: str,
    *,
    end_turn: bool = False,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Add an emoji reaction to a message in an external chat channel."""
    rt = runtime.context
    caller = _caller(rt)
    await rt.router.react(caller, to, message_id, emoji)
    if to in rt.active_typing:
        rt.active_typing.discard(to)
        await rt.router.set_typing(caller, to, active=False)
    return (
        f"Reacted {emoji} on {message_id} in {to}",
        {
            "to": to,
            "message_id": message_id,
            "emoji": emoji,
            "end_turn": end_turn,
        },
    )


async def handle_read_messages(
    to: str,
    before: int | None = None,
    limit: int = 20,
    query: str = "",
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Read paginated message history from a chat or agent channel."""
    rt = runtime.context
    caller = _caller(rt)
    msgs = await rt.router.read_history(
        caller, to, before_seq=before, limit=limit, query=query
    )
    rt.active_channels[to] = monotonic()
    with contextlib.suppress(Exception):
        await rt.fs.discover()

    # Mark any previewed inbox rows for this channel as delivered.
    await rt.services.inbox.mark_channel_delivered(rt.agent_id, to)
    max_seq = max((m.seq for m in msgs if m.seq and m.seq > 0), default=0)
    if max_seq > 0:
        await rt.router.mark_read(caller, to, max_seq)

    next_before = msgs[0].seq if msgs and msgs[0].seq and msgs[0].seq > 1 else None
    lines = [
        f'<messages channel={sax.quoteattr(to)} count="{len(msgs)}" next_before="{next_before or ""}">'
    ]
    for m in msgs:
        from_label = _format_sender_label(rt, m.sender_type, m.sender_id)
        lines.append(
            f'  <message id={sax.quoteattr(m.id)} seq="{m.seq or ""}" '
            f"from={sax.quoteattr(from_label)} "
            f"at={sax.quoteattr(m.created_at)}>"
        )
        lines.append(f"    {sax.escape(m.content)}")
        if m.attachments:
            lines.append("    <attachments>")
            for att in m.attachments:
                sid = att.storage_id
                nid = att.node_id
                name = att.name
                mtype = att.media_type
                letfs_path = f"/letfs/{sid}/{nid}" if sid and nid else ""
                lines.append(
                    f"      <attachment name={sax.quoteattr(name)} media_type={sax.quoteattr(mtype)} "
                    f"path={sax.quoteattr(letfs_path)} />"
                )
            lines.append("    </attachments>")
        lines.append("  </message>")
    lines.append("</messages>")
    return (
        "\n".join(lines),
        {"to": to, "count": len(msgs), "next_before": next_before},
    )


async def handle_list_channels(
    query: str = "",
    limit: int = 20,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """List active DMs, group chats, and subagent channels visible to the caller."""
    rt = runtime.context
    caller = _caller(rt)
    channels = await rt.router.list_channels(caller, query=query, limit=limit)
    if not channels:
        return "No active channels found.", {"channels": []}
    with contextlib.suppress(Exception):
        await rt.fs.discover()
    lines: list[str] = []
    out_items: list[JSON] = []
    for c in channels:
        mount = rt.fs.chat_mount_for(c.address)
        mount_part = f" | storage: {mount}" if mount else ""
        lines.append(
            f'- {c.address} | {c.title} ({c.kind}){mount_part} | unread: {c.unread_count} | "{c.last_message_snippet}"'
        )
        out_items.append(
            {
                "address": c.address,
                "kind": c.kind,
                "title": c.title,
                "handle": c.handle,
                "storage": mount,
                "unread_count": c.unread_count,
            }
        )
    return "\n".join(lines), {"channels": out_items}


def build_messaging_tools(
    *, is_root: bool, enable_react: bool = True
) -> list[BaseTool]:
    """Build messaging, channel-reading, and optional reaction tools for the agent."""
    if not is_root:
        return [
            make_tool(
                name="send_message",
                description="Send an update or final report to your parent or a sibling subagent (cannot message external users).",
                args_schema=SubagentSendMessageArgs,
                coroutine=handle_subagent_send_message,
            )
        ]
    tools: list[BaseTool] = [
        make_tool(
            name="send_message",
            description=(
                "Send a message to a user, peer agent, group chat, or subagent. "
                "Required for all external communication (plain assistant text is internal work log only)."
            ),
            args_schema=RootSendMessageArgs,
            coroutine=handle_root_send_message,
        ),
        make_tool(
            name="read_messages",
            description="Read conversation history or open a mid-run <notification> preview from another channel.",
            args_schema=ReadMessagesArgs,
            coroutine=handle_read_messages,
        ),
        make_tool(
            name="list_channels",
            description="List active DMs, group chats, and subagent channels with their /chat/<handle> mounts and unread counts.",
            args_schema=ListChannelsArgs,
            coroutine=handle_list_channels,
        ),
    ]
    if enable_react:
        tools.append(
            make_tool(
                name="react_message",
                description="React with an emoji to an external chat message when a written reply is unnecessary.",
                args_schema=ReactMessageArgs,
                coroutine=handle_react_message,
            )
        )
    return tools
