from __future__ import annotations

import xml.sax.saxutils as sax
from collections.abc import Mapping
from datetime import datetime
from time import monotonic
from typing import Literal, cast

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.runtime import Runtime
from openlet_sdk.config import JSON

from ...channels.base import CallerContext
from ...hitl.service import format_hitl_outcome_attr
from ..state import AgentState, RuntimeContext


def _iso(val: object) -> str:
    if isinstance(val, datetime):
        return val.isoformat()
    return str(val or "")


def _sender_label(sender: Mapping[str, object]) -> str:
    handle = str(sender.get("handle") or "").lstrip("@").strip()
    name = str(sender.get("name") or "").strip()
    sid = str(sender.get("id") or "")
    stype = str(sender.get("type") or "")
    if handle and name:
        return f"{name} ({handle})"
    if handle:
        return handle
    return name or f"{stype}:{sid}"


def format_inbox_item_full(
    row: Mapping[str, object],
    *,
    sender_override: Mapping[str, object] | None = None,
    chat_storage: str | None = None,
) -> str:
    seq = int(cast(int, row["seq"]))
    kind = str(row["kind"])
    channel = str(row.get("channel") or "")
    reply_to = str(row.get("reply_address") or "")
    sender = (
        sender_override
        if sender_override is not None
        else cast(Mapping[str, object], row.get("sender") or {})
    )
    meta = cast(Mapping[str, object], row.get("metadata") or {})
    attachments = cast(list[Mapping[str, object]], row.get("attachments") or [])
    content = str(row.get("content") or "")
    created_at = _iso(row.get("created_at"))
    from_str = _sender_label(sender)

    if kind == "agent":
        return (
            f'  <agent-message seq="{seq}" from={sax.quoteattr(from_str)} '
            f"reply_address={sax.quoteattr(reply_to)} at={sax.quoteattr(created_at)}>\n"
            f"    {sax.escape(content)}\n"
            f"  </agent-message>"
        )

    if kind == "schedule":
        sched_id = str(meta.get("schedule_id") or "")
        title = str(meta.get("title") or "")
        scheduled_for = str(meta.get("scheduled_for") or created_at)
        return (
            f'  <schedule seq="{seq}" id={sax.quoteattr(sched_id)} '
            f"title={sax.quoteattr(title)} scheduled_for={sax.quoteattr(scheduled_for)} "
            f"delivered_at={sax.quoteattr(created_at)}>\n"
            f"    {sax.escape(content)}\n"
            f"  </schedule>"
        )

    if kind == "hitl":
        req_id = str(meta.get("request_id") or "")
        h_type = str(meta.get("type") or "")
        status = str(meta.get("status") or "")
        outcome = format_hitl_outcome_attr(meta.get("outcome"))
        return (
            f'  <hitl-result seq="{seq}" request_id={sax.quoteattr(req_id)} '
            f"type={sax.quoteattr(h_type)} status={sax.quoteattr(status)} "
            f"outcome={sax.quoteattr(outcome)} from={sax.quoteattr(from_str)}>\n"
            f"    {sax.escape(content)}\n"
            f"  </hitl-result>"
        )

    if meta.get("event") == "reaction":
        target_msg = str(meta.get("target_message_id") or "")
        emoji = str(meta.get("emoji") or content)
        return (
            f'  <reaction seq="{seq}" channel={sax.quoteattr(channel)} '
            f"from={sax.quoteattr(from_str)} target_message_id={sax.quoteattr(target_msg)} "
            f"emoji={sax.quoteattr(emoji)} />"
        )

    msg_id = str(meta.get("message_id") or "")
    storage_attr = (
        f" chat_storage={sax.quoteattr(chat_storage)}" if chat_storage else ""
    )
    lines = [
        f'  <message seq="{seq}" id={sax.quoteattr(msg_id)} channel={sax.quoteattr(channel)} '
        f"reply_address={sax.quoteattr(reply_to)}{storage_attr} from={sax.quoteattr(from_str)} "
        f"at={sax.quoteattr(created_at)}>"
    ]
    if meta.get("reply_to_message_id"):
        lines.append(
            f"    <reply-to id={sax.quoteattr(str(meta['reply_to_message_id']))} />"
        )
    lines.append(f"    <content>{sax.escape(content)}</content>")
    if attachments:
        lines.append("    <attachments>")
        for att in attachments:
            sid = str(att.get("storage_id") or "")
            nid = str(att.get("node_id") or "")
            name = str(att.get("name") or "")
            mtype = str(att.get("media_type") or "")
            letfs_path = f"/letfs/{sid}/{nid}" if sid and nid else ""
            lines.append(
                f"      <attachment name={sax.quoteattr(name)} media_type={sax.quoteattr(mtype)} "
                f"path={sax.quoteattr(letfs_path)} />"
            )
        lines.append("    </attachments>")
    lines.append("  </message>")
    return "\n".join(lines)


def format_inbox_notification_preview(
    row: Mapping[str, object], *, preview_chars: int = 120, unread_in_channel: int = 1
) -> str:
    seq = int(cast(int, row["seq"]))
    channel = str(row.get("channel") or row.get("kind") or "")
    reply_to = str(row.get("reply_address") or "")
    sender = cast(Mapping[str, object], row.get("sender") or {})
    meta = cast(Mapping[str, object], row.get("metadata") or {})
    msg_id = str(meta.get("message_id") or meta.get("schedule_id") or "")
    created_at = _iso(row.get("created_at"))
    from_str = _sender_label(sender)
    raw = " ".join(str(row.get("content") or "").split())
    snippet = raw[:preview_chars] + ("..." if len(raw) > preview_chars else "")
    return (
        f'  <notification seq="{seq}" id={sax.quoteattr(msg_id)} channel={sax.quoteattr(channel)} '
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
) -> dict[str, object]:
    """Drain inbox_items with pending -> previewed -> delivered policy and XML <inbox> framing."""
    rt = runtime.context
    _prune_expired_channels(rt)
    is_turn_start = rt.step_count == 0
    rt.drained_this_step = False

    async with rt.services.db.connection() as conn:
        if not rt.is_root:
            rows = await (
                await conn.execute(
                    """
                    SELECT seq, kind, channel, reply_address, sender, content,
                           attachments, metadata, silent, delivery_state, created_at
                    FROM inbox_items
                    WHERE agent_id = %s AND delivery_state = 'pending'
                    ORDER BY seq ASC
                    """,
                    (rt.agent_id,),
                )
            ).fetchall()
        elif is_turn_start:
            rows = await (
                await conn.execute(
                    """
                    SELECT seq, kind, channel, reply_address, sender, content,
                           attachments, metadata, silent, delivery_state, created_at
                    FROM inbox_items
                    WHERE agent_id = %s AND delivery_state IN ('pending', 'previewed')
                    ORDER BY seq ASC
                    """,
                    (rt.agent_id,),
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
                    (rt.agent_id,),
                )
            ).fetchall()

    if not rows:
        return {}

    now = monotonic()
    preview_chars = rt.services.settings.messaging.notification_preview_chars
    delivered_seqs: list[int] = []
    previewed_seqs: list[int] = []
    xml_entries: list[str] = []
    activity_items: list[JSON] = []
    typing_targets: set[str] = set()
    read_seqs: dict[str, int] = {}

    # Count per-channel batch sizes for unread_in_channel hints on mid-run previews.
    channel_counts: dict[str, int] = {}
    for r in rows:
        addr = str(r.get("reply_address") or "")
        if addr:
            channel_counts[addr] = channel_counts.get(addr, 0) + 1

    if any(str(r.get("reply_address") or "").startswith("chat:") for r in rows):
        try:
            await rt.fs.discover()
        except Exception:
            pass

    for r in rows:
        seq = int(r["seq"])
        kind = str(r["kind"])
        reply_addr = str(r.get("reply_address") or "")
        content = str(r.get("content") or "")
        is_external = bool(reply_addr) and not reply_addr.startswith("agent:")
        raw_sender = cast(Mapping[str, object], r.get("sender") or {})
        enriched_sender = rt.fs.enrich_sender(raw_sender) if is_external else raw_sender
        chat_storage = rt.fs.chat_mount_for(reply_addr) if is_external else None

        deliver_full = (
            not rt.is_root
            or is_turn_start
            or kind in ("agent", "hitl")
            or (reply_addr in rt.active_channels)
            or (kind == "notification" and len(content) <= 300)
        )

        if deliver_full:
            delivered_seqs.append(seq)
            xml_entries.append(
                format_inbox_item_full(
                    r, sender_override=enriched_sender, chat_storage=chat_storage
                )
            )
            if is_external:
                rt.active_channels[reply_addr] = now
                meta = cast(Mapping[str, object], r.get("metadata") or {})
                raw_msg_seq = meta.get("seq")
                if isinstance(raw_msg_seq, int) and raw_msg_seq > 0:
                    prev = read_seqs.get(reply_addr, 0)
                    if raw_msg_seq > prev:
                        read_seqs[reply_addr] = raw_msg_seq
                if not bool(r.get("silent")):
                    typing_targets.add(reply_addr)
        else:
            previewed_seqs.append(seq)
            xml_entries.append(
                format_inbox_notification_preview(
                    r,
                    preview_chars=preview_chars,
                    unread_in_channel=channel_counts.get(reply_addr, 1),
                )
            )

        meta_dict = cast(
            dict[str, JSON], dict(cast(Mapping[str, object], r.get("metadata") or {}))
        )
        raw_atts = cast(
            list[JSON], list(cast(list[object], r.get("attachments") or []))
        )
        sender_dict = cast(dict[str, JSON], dict(enriched_sender))
        activity_items.append(
            {
                "seq": seq,
                "kind": kind,
                "channel": r.get("channel"),
                "sender": sender_dict,
                "reply_address": reply_addr or None,
                "content": content[:4000],
                "preview": content[:200],
                "attachments": raw_atts,
                "attachments_count": len(raw_atts),
                "metadata": meta_dict,
                "delivery_state": "delivered" if deliver_full else "previewed",
            }
        )

    async with rt.services.db.connection() as conn, conn.transaction():
        if delivered_seqs:
            await conn.execute(
                """
                UPDATE inbox_items
                SET delivery_state = 'delivered'
                WHERE agent_id = %s AND seq = ANY(%s)
                """,
                (rt.agent_id, delivered_seqs),
            )
        if previewed_seqs:
            await conn.execute(
                """
                UPDATE inbox_items
                SET delivery_state = 'previewed'
                WHERE agent_id = %s AND seq = ANY(%s)
                """,
                (rt.agent_id, previewed_seqs),
            )

    caller = _caller(rt)
    for addr, msg_seq in read_seqs.items():
        await rt.router.mark_read(caller, addr, msg_seq)
    for addr in typing_targets:
        rt.active_typing.add(addr)
        await rt.router.set_typing(caller, addr, True)

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
        new_cursor = max(new_cursor, max(delivered_seqs))

    rt.drained_this_step = True
    return {
        "messages": [HumanMessage(content=xml_payload)],
        "inbox_cursor": new_cursor,
    }


def after_inbox_router(
    state: AgentState, runtime: Runtime[RuntimeContext]
) -> Literal["compact", "__end__"]:
    rt = runtime.context
    if rt.drained_this_step:
        return "compact"
    msgs = state["messages"]
    if msgs and isinstance(msgs[-1], ToolMessage):
        return "compact"
    return "__end__"
