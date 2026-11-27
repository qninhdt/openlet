"""LangGraph inbox-drain node and XML <inbox> message formatting."""

from __future__ import annotations

import contextlib
import xml.sax.saxutils as sax
from time import monotonic
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, ToolMessage

from leta.channels.base import CallerContext
from leta.runtime.formatting import (
    format_hitl_outcome,
    format_hitl_outcome_attr,
    format_hitl_response,
)

if TYPE_CHECKING:
    from datetime import datetime
    from typing import Literal

    from langgraph.runtime import Runtime
    from openlet_sdk.config import JSON

    from leta.inbox import InboxMetadata, InboxRecord, InboxSender
    from leta.runtime.state import AgentState, AgentStateUpdate, RuntimeContext


def _iso(val: datetime) -> str:
    return val.isoformat()


def _sender_label(sender: InboxSender) -> str:
    handle = sender.handle.lstrip("@").strip()
    name = sender.name.strip()
    if handle and name:
        return f"{name} ({handle})"
    if handle:
        return handle
    return name or f"{sender.type}:{sender.id}"


def _inbox_display_content(kind: str, content: str, meta: InboxMetadata) -> str:
    if content:
        return content
    if kind == "hitl":
        parts = [
            f"HITL request '{meta.title}' ({meta.request_id}) resolved with status: {meta.status}."
        ]
        resp_text = format_hitl_response(meta.payload, meta.response)
        if resp_text:
            parts.append(resp_text)
        outcome_text = format_hitl_outcome(meta.outcome)
        if outcome_text:
            parts.append(f"Outcome: {outcome_text}")
        return "\n".join(parts)
    if kind == "notification" and meta.event == "subagent_failed":
        return meta.error or "unknown error"
    return ""


def format_inbox_item_full(
    rec: InboxRecord,
    *,
    sender_override: InboxSender | None = None,
    chat_storage: str | None = None,
) -> str:
    """Format a single inbox record as full XML for the agent's <inbox> prompt."""
    seq = rec.seq
    kind = rec.kind
    channel = rec.channel or ""
    reply_to = rec.reply_address or ""
    sender = sender_override if sender_override is not None else rec.sender
    meta = rec.metadata
    content = rec.content
    created_at = _iso(rec.created_at)
    from_str = _sender_label(sender)

    if kind == "agent":
        return (
            f'  <agent-message seq="{seq}" from={sax.quoteattr(from_str)} '
            f"reply_address={sax.quoteattr(reply_to)} at={sax.quoteattr(created_at)}>\n"
            f"    {sax.escape(content)}\n"
            f"  </agent-message>"
        )

    if kind == "schedule":
        scheduled_for = meta.scheduled_for or created_at
        return (
            f'  <schedule seq="{seq}" id={sax.quoteattr(meta.schedule_id)} '
            f"title={sax.quoteattr(meta.title)} scheduled_for={sax.quoteattr(scheduled_for)} "
            f"delivered_at={sax.quoteattr(created_at)}>\n"
            f"    {sax.escape(content)}\n"
            f"  </schedule>"
        )

    if kind == "hitl":
        outcome = format_hitl_outcome_attr(meta.outcome)
        body = _inbox_display_content(kind, content, meta)
        return (
            f'  <hitl-result seq="{seq}" request_id={sax.quoteattr(meta.request_id)} '
            f"type={sax.quoteattr(meta.type)} status={sax.quoteattr(meta.status)} "
            f"outcome={sax.quoteattr(outcome)} from={sax.quoteattr(from_str)}>\n"
            f"    {sax.escape(body)}\n"
            f"  </hitl-result>"
        )

    if kind == "notification" and meta.event == "subagent_failed":
        sub_handle = meta.subagent_handle or sender.handle
        sub_name = meta.subagent_name or sender.name
        err_text = _inbox_display_content(kind, content, meta)
        return (
            f'  <subagent-failed seq="{seq}" handle={sax.quoteattr(sub_handle)} '
            f"name={sax.quoteattr(sub_name)} subagent_id={sax.quoteattr(meta.subagent_id)}>\n"
            f"    {sax.escape(err_text)}\n"
            f"  </subagent-failed>"
        )

    if kind == "reaction":
        return (
            f'  <reaction seq="{seq}" channel={sax.quoteattr(channel)} '
            f"from={sax.quoteattr(from_str)} target_message_id={sax.quoteattr(meta.target_message_id)} "
            f"emoji={sax.quoteattr(meta.emoji)} action={sax.quoteattr(meta.action)} />"
        )

    storage_attr = (
        f" chat_storage={sax.quoteattr(chat_storage)}" if chat_storage else ""
    )
    lines = [
        (
            f'  <message seq="{seq}" id={sax.quoteattr(meta.message_id)} channel={sax.quoteattr(channel)} '
            f"reply_address={sax.quoteattr(reply_to)}{storage_attr} from={sax.quoteattr(from_str)} "
            f"at={sax.quoteattr(created_at)}>"
        )
    ]
    if meta.reply_to_message_id:
        lines.append(f"    <reply-to id={sax.quoteattr(meta.reply_to_message_id)} />")
    lines.append(f"    <content>{sax.escape(content)}</content>")
    if rec.attachments:
        lines.append("    <attachments>")
        for att in rec.attachments:
            letfs_path = (
                f"/letfs/{att.storage_id}/{att.node_id}"
                if att.storage_id and att.node_id
                else ""
            )
            lines.append(
                f"      <attachment name={sax.quoteattr(att.name)} media_type={sax.quoteattr(att.media_type)} "
                f"path={sax.quoteattr(letfs_path)} />"
            )
        lines.append("    </attachments>")
    lines.append("  </message>")
    return "\n".join(lines)


def format_inbox_notification_preview(
    rec: InboxRecord,
    *,
    preview_chars: int = 120,
    unread_in_channel: int = 1,
) -> str:
    """Format a mid-run cross-channel message as a compact <notification> preview."""
    channel = rec.channel or rec.kind
    reply_to = rec.reply_address or ""
    msg_id = rec.metadata.message_id or rec.metadata.schedule_id
    created_at = _iso(rec.created_at)
    from_str = _sender_label(rec.sender)
    raw = " ".join(rec.content.split())
    snippet = raw[:preview_chars] + ("..." if len(raw) > preview_chars else "")
    return (
        f'  <notification seq="{rec.seq}" id={sax.quoteattr(msg_id)} channel={sax.quoteattr(channel)} '
        f"from={sax.quoteattr(from_str)} to={sax.quoteattr(reply_to)} at={sax.quoteattr(created_at)} "
        f'unread_in_channel="{unread_in_channel}">'
        f"{sax.escape(snippet)} "
        f"(Call read_messages(to={reply_to!r}) if urgent, or ignore until after your current task.)"
        f"</notification>"
    )


def _prune_expired_channels(rt: RuntimeContext) -> None:
    ttl = float(rt.services.settings.messaging.active_channel_ttl_seconds)
    now = monotonic()
    expired = [addr for addr, ts in rt.active_channels.items() if now - ts > ttl]
    for addr in expired:
        rt.active_channels.pop(addr, None)


def _caller(rt: RuntimeContext) -> CallerContext:
    return CallerContext(
        workspace_id=rt.workspace_id,
        leta_id=rt.leta_id,
        agent_id=rt.agent_id,
        handle=rt.handle,
        name=rt.agent_name,
        is_root=rt.is_root,
    )


async def inbox_node(
    state: AgentState, runtime: Runtime[RuntimeContext]
) -> AgentStateUpdate:
    """Drain inbox_items with pending -> previewed -> delivered policy and XML <inbox> framing."""
    rt = runtime.context
    _prune_expired_channels(rt)
    is_turn_start = rt.step_count == 0
    rt.drained_this_step = False

    rows = await rt.services.inbox.fetch_pending(
        rt.agent_id, include_previewed=(rt.is_root and is_turn_start)
    )

    if not rows:
        return {}

    now = monotonic()
    preview_chars = rt.services.settings.messaging.notification_preview_chars
    delivered_seqs: list[int] = []
    previewed_seqs: list[int] = []
    xml_entries: list[str] = []
    activity_items: list[dict[str, JSON]] = []
    typing_targets: set[str] = set()
    read_seqs: dict[str, int] = {}

    # Count per-channel batch sizes for unread_in_channel hints on mid-run previews.
    channel_counts: dict[str, int] = {}
    for r in rows:
        addr = r.reply_address or ""
        if addr:
            channel_counts[addr] = channel_counts.get(addr, 0) + 1

    if any((r.reply_address or "").startswith("chat:") for r in rows):
        with contextlib.suppress(Exception):
            await rt.fs.discover()

    for r in rows:
        reply_addr = r.reply_address or ""
        is_external = bool(reply_addr) and not reply_addr.startswith("agent:")
        enriched_sender = rt.fs.enrich_sender(r.sender) if is_external else r.sender
        chat_storage = rt.fs.chat_mount_for(reply_addr) if is_external else None

        deliver_full = (
            not rt.is_root
            or is_turn_start
            or r.kind in ("agent", "hitl", "reaction")
            or (reply_addr in rt.active_channels)
            or (r.kind == "notification" and len(r.content) <= 300)
        )

        if deliver_full:
            delivered_seqs.append(r.seq)
            xml_entries.append(
                format_inbox_item_full(
                    r, sender_override=enriched_sender, chat_storage=chat_storage
                )
            )
            if is_external:
                rt.active_channels[reply_addr] = now
                if r.metadata.seq is not None and r.metadata.seq > 0:
                    prev = read_seqs.get(reply_addr, 0)
                    if r.metadata.seq > prev:
                        read_seqs[reply_addr] = r.metadata.seq
                if not r.silent:
                    typing_targets.add(reply_addr)
        else:
            previewed_seqs.append(r.seq)
            xml_entries.append(
                format_inbox_notification_preview(
                    r,
                    preview_chars=preview_chars,
                    unread_in_channel=channel_counts.get(reply_addr, 1),
                )
            )

        att_dicts = [a.model_dump() for a in r.attachments]
        sender_dict: dict[str, JSON] = enriched_sender.model_dump()
        display_content = _inbox_display_content(r.kind, r.content, r.metadata)
        activity_items.append(
            {
                "seq": r.seq,
                "kind": r.kind,
                "channel": r.channel,
                "sender": sender_dict,
                "reply_address": reply_addr or None,
                "content": display_content[:4000],
                "preview": display_content[:200],
                "attachments": att_dicts,
                "attachments_count": len(att_dicts),
                "metadata": r.metadata.model_dump(mode="json", exclude_unset=True),
                "delivery_state": "delivered" if deliver_full else "previewed",
            }
        )

    await rt.services.inbox.mark_delivery_states(
        rt.agent_id,
        delivered_seqs=delivered_seqs,
        previewed_seqs=previewed_seqs,
    )

    caller = _caller(rt)
    for addr, msg_seq in read_seqs.items():
        await rt.router.mark_read(caller, addr, msg_seq)
    for addr in typing_targets:
        rt.active_typing.add(addr)
        await rt.router.set_typing(caller, addr, active=True)

    await rt.emitter.emit(
        leta_id=rt.leta_id,
        agent_id=rt.agent_id,
        run_id=rt.run_id,
        event_type="activity.inbox_received",
        data={"items": activity_items},
    )

    xml_payload = "<inbox>\n" + "\n".join(xml_entries) + "\n</inbox>"
    new_cursor = state.get("inbox_cursor", 0)
    if delivered_seqs:
        new_cursor = max(new_cursor, *delivered_seqs)

    rt.drained_this_step = True
    return {
        "messages": [HumanMessage(content=xml_payload)],
        "inbox_cursor": new_cursor,
    }


def after_inbox_router(
    state: AgentState, runtime: Runtime[RuntimeContext]
) -> Literal["compact", "__end__"]:
    """Route to compaction if inbox items or pending tool results exist; otherwise end."""
    rt = runtime.context
    if rt.drained_this_step:
        return "compact"
    msgs = state["messages"]
    if msgs and isinstance(msgs[-1], ToolMessage):
        return "compact"
    return "__end__"
