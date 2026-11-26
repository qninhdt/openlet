from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import grpc
from google.protobuf.struct_pb2 import Struct
from langchain_core.tools import ToolException
from openlet_api.chat.v1 import chat_pb2 as chat_pb
from openlet_api.platform.v1 import internal_pb2 as plat_int_pb
from openlet_sdk.config import JSON

from ..auth import Actor
from ..db import Pool
from .base import (
    CallerContext,
    ChannelMessage,
    ChannelSummary,
    OutboundMessage,
    OutboundReceipt,
)

if TYPE_CHECKING:
    from openlet_api.chat.v1.chat_pb2_grpc import ChatServiceAsyncStub
    from openlet_api.platform.v1.internal_pb2_grpc import (
        PlatformInternalServiceAsyncStub,
    )


class OpenletChatAdapter:
    scheme = "chat"

    def __init__(
        self,
        chat: ChatServiceAsyncStub,
        platform_internal: PlatformInternalServiceAsyncStub,
        db: Pool,
    ) -> None:
        self.chat = chat
        self.platform_internal = platform_internal
        self.db = db

    async def _list_workspace_conversations(
        self, caller: CallerContext, *, limit: int = 100
    ) -> list[chat_pb.Conversation]:
        resp = await self.chat.ListConversations(
            chat_pb.ListConversationsRequest(
                workspace_id=str(caller.workspace_id),
                page_size=max(1, min(limit, 100)),
            ),
            metadata=Actor("agent", caller.leta_id).metadata,
            timeout=15,
        )
        return list(resp.conversations)

    async def _dm_with_user(self, caller: CallerContext, user_ref: str) -> str:
        cleaned = user_ref.strip().lstrip("@").strip()
        if not cleaned:
            raise ToolException("User target cannot be empty.")
        user_id: str | None = None
        try:
            user_id = str(UUID(cleaned))
        except ValueError:
            try:
                user = await self.platform_internal.GetUserByHandle(
                    plat_int_pb.UserHandleRequest(handle=cleaned.lower()), timeout=15
                )
                user_id = str(user.id)
            except grpc.aio.AioRpcError as exc:
                if exc.code() == grpc.StatusCode.NOT_FOUND:
                    raise ToolException(
                        f"User {cleaned!r} not found. Call list_members to see workspace handles."
                    ) from None
                raise
        conv = await self.chat.CreateOrGetDM(
            chat_pb.CreateOrGetDMRequest(
                workspace_id=str(caller.workspace_id),
                target=chat_pb.ChatActor(type="user", id=user_id),
            ),
            metadata=Actor("agent", caller.leta_id).metadata,
            timeout=15,
        )
        return str(conv.id)

    async def _dm_with_peer_agent(self, caller: CallerContext, agent_ref: str) -> str:
        cleaned = agent_ref.strip().lstrip("@").strip()
        if not cleaned:
            raise ToolException("Agent target cannot be empty.")
        uid: UUID | None = None
        try:
            uid = UUID(cleaned)
        except ValueError:
            uid = None
        async with self.db.connection() as conn:
            if uid is not None:
                row = await (
                    await conn.execute(
                        """
                        SELECT a.id, a.leta_id
                        FROM agents a
                        JOIN letas l ON l.id = a.leta_id
                        WHERE l.workspace_id = %s
                          AND l.state = 'active'
                          AND a.parent_agent_id IS NULL
                          AND (a.id = %s OR a.leta_id = %s)
                        LIMIT 1
                        """,
                        (caller.workspace_id, uid, uid),
                    )
                ).fetchone()
            else:
                row = await (
                    await conn.execute(
                        """
                        SELECT a.id, a.leta_id
                        FROM agents a
                        JOIN letas l ON l.id = a.leta_id
                        WHERE l.workspace_id = %s
                          AND l.state = 'active'
                          AND a.parent_agent_id IS NULL
                          AND lower(a.handle) = %s
                        LIMIT 1
                        """,
                        (caller.workspace_id, cleaned.lower()),
                    )
                ).fetchone()
        if row is None:
            raise ToolException(
                f"Peer agent {cleaned!r} not found in this workspace. Call list_members(kind='agent') to see peer agents."
            )
        conv = await self.chat.CreateOrGetDM(
            chat_pb.CreateOrGetDMRequest(
                workspace_id=str(caller.workspace_id),
                target=chat_pb.ChatActor(type="agent", id=str(row["leta_id"])),
            ),
            metadata=Actor("agent", caller.leta_id).metadata,
            timeout=15,
        )
        return str(conv.id)

    async def find_plain_matches(
        self, caller: CallerContext, raw_ref: str
    ) -> list[tuple[str, str]]:
        """Find candidate ('chat:<target>', label) matches for an unprefixed handle/name."""
        cleaned = raw_ref.strip().lstrip("@").strip()
        if not cleaned:
            return []
        low = cleaned.lower()
        matches: list[tuple[str, str]] = []

        # 1. Exact workspace user handle
        try:
            user = await self.platform_internal.GetUserByHandle(
                plat_int_pb.UserHandleRequest(handle=low), timeout=10
            )
            matches.append(
                (
                    f"chat:user:{user.handle}",
                    f"{user.display_name} (user: {user.handle})",
                )
            )
        except grpc.aio.AioRpcError:
            pass

        # 2. Exact peer Root Leta handle
        async with self.db.connection() as conn:
            row = await (
                await conn.execute(
                    """
                    SELECT a.name, a.handle
                    FROM agents a
                    JOIN letas l ON l.id = a.leta_id
                    WHERE l.workspace_id = %s
                      AND l.state = 'active'
                      AND a.parent_agent_id IS NULL
                      AND a.leta_id <> %s
                      AND lower(a.handle) = %s
                    LIMIT 1
                    """,
                    (caller.workspace_id, caller.leta_id, low),
                )
            ).fetchone()
        if row is not None:
            matches.append(
                (
                    f"chat:agent:{row['handle']}",
                    f"{row['name']} (peer agent: {row['handle']})",
                )
            )

        # 3. Exact group conversation handle
        try:
            convs = await self._list_workspace_conversations(caller)
            for c in convs:
                if (
                    c.type == "group"
                    and c.HasField("handle")
                    and c.handle.strip().lower() == low
                ):
                    matches.append((f"chat:{c.id}", f"{c.title or c.handle} (group)"))
        except Exception:
            pass

        return matches

    async def _resolve_conversation_id(self, caller: CallerContext, target: str) -> str:
        """Accept conv UUID, 'user:<handle|uuid>', 'agent:<handle|uuid>', or a group/user/peer handle."""
        cleaned = target.strip()
        try:
            return str(UUID(cleaned))
        except ValueError:
            pass

        if cleaned.lower().startswith("user:"):
            return await self._dm_with_user(caller, cleaned[5:])

        if cleaned.lower().startswith("agent:"):
            return await self._dm_with_peer_agent(caller, cleaned[6:])

        # Support chat:<group_handle> or chat:<@handle> (auto-resolve group/user/peer).
        matches = await self.find_plain_matches(caller, cleaned)
        if len(matches) == 1:
            addr = matches[0][0].removeprefix("chat:")
            return await self._resolve_conversation_id(caller, addr)
        if len(matches) > 1:
            opts = ", ".join(f"{a} [{lbl}]" for a, lbl in matches)
            raise ToolException(
                f"Chat target {target!r} matches multiple destinations. Specify one of: {opts}"
            )

        raise ToolException(
            f"Chat destination {target!r} not found. Use a conversation ID ('chat:<conv_id>'), "
            "a handle ('ethan', 'chat:user:ethan', 'chat:agent:nora'), or call list_channels / list_members."
        )

    async def send(
        self,
        caller: CallerContext,
        target: str,
        msg: OutboundMessage,
        idempotency_key: UUID,
    ) -> OutboundReceipt:
        conv_id = await self._resolve_conversation_id(caller, target)
        meta_struct: Struct | None = None
        if msg.metadata:
            meta_struct = Struct()
            meta_struct.update(msg.metadata)

        reply_to_id: str | None = None
        if msg.reply_to_id:
            candidate = msg.reply_to_id.strip()
            if candidate and not candidate.startswith("chat:") and candidate != conv_id:
                try:
                    reply_to_id = str(UUID(candidate))
                except ValueError:
                    reply_to_id = None

        req = chat_pb.SendMessageRequest(
            workspace_id=str(caller.workspace_id),
            conversation_id=conv_id,
            idempotency_key=str(idempotency_key),
            content=msg.content,
            reply_to_id=reply_to_id,
            attachments=[
                chat_pb.MessageAttachment(
                    storage_id=a.storage_id,
                    node_id=a.node_id,
                    kind=a.kind,
                    name=a.name,
                    media_type=a.media_type,
                    size_bytes=a.size_bytes,
                )
                for a in msg.attachments
            ],
            mentions=[
                chat_pb.MessageMention(
                    kind=m.kind,
                    id=m.id,
                    storage_id=m.storage_id or None,
                    node_id=m.node_id or None,
                    label=m.label,
                )
                for m in msg.mentions
            ],
            metadata=meta_struct,
        )
        meta = Actor("agent", caller.leta_id).metadata
        sent = await self.chat.SendMessage(req, metadata=meta, timeout=30)
        recipient: dict[str, JSON] | None = None
        try:
            conv = await self.chat.GetConversation(
                chat_pb.ConversationRequest(
                    workspace_id=str(caller.workspace_id),
                    conversation_id=conv_id,
                ),
                metadata=meta,
                timeout=10,
            )
            if conv.type == "group":
                recipient = {
                    "kind": "box",
                    "id": str(conv.id),
                    "name": conv.title or conv.handle or "Group",
                }
            else:
                for member in conv.members:
                    if str(member.actor_id) != str(caller.leta_id):
                        recipient = {
                            "kind": "agent" if member.actor_type == "agent" else "user",
                            "id": str(member.actor_id),
                        }
                        break
        except Exception:
            recipient = None
        return OutboundReceipt(
            channel="chat",
            target=conv_id,
            message_id=str(sent.id),
            seq=int(sent.seq),
            recipient=recipient,
        )

    async def react(
        self, caller: CallerContext, target: str, message_id: str, emoji: str
    ) -> None:
        conv_id = await self._resolve_conversation_id(caller, target)
        await self.chat.AddReaction(
            chat_pb.ReactionRequest(
                workspace_id=str(caller.workspace_id),
                conversation_id=conv_id,
                message_id=message_id,
                emoji=emoji,
            ),
            metadata=Actor("agent", caller.leta_id).metadata,
            timeout=15,
        )

    async def read_history(
        self,
        caller: CallerContext,
        target: str,
        *,
        before_seq: int | None = None,
        limit: int = 20,
        query: str = "",
    ) -> list[ChannelMessage]:
        conv_id = await self._resolve_conversation_id(caller, target)
        req = chat_pb.ListMessagesRequest(
            workspace_id=str(caller.workspace_id),
            conversation_id=conv_id,
            before_seq=before_seq,
            limit=max(1, min(limit, 100)),
            query=query,
        )
        resp = await self.chat.ListMessages(
            req, metadata=Actor("agent", caller.leta_id).metadata, timeout=15
        )
        out: list[ChannelMessage] = []
        for m in resp.messages:
            atts: list[dict[str, JSON]] = [
                {
                    "storage_id": a.storage_id,
                    "node_id": a.node_id,
                    "kind": a.kind,
                    "name": a.name,
                    "media_type": a.media_type,
                    "size_bytes": int(a.size_bytes),
                }
                for a in m.attachments
            ]
            rx: list[dict[str, JSON]] = [
                {
                    "actor_type": r.actor_type,
                    "actor_id": r.actor_id,
                    "emoji": r.emoji,
                }
                for r in m.reactions
            ]
            out.append(
                ChannelMessage(
                    id=m.id,
                    seq=int(m.seq),
                    sender_type=m.sender_type,
                    sender_id=m.sender_id,
                    content=m.content,
                    created_at=m.created_at.ToDatetime().isoformat(),
                    reply_to_id=m.reply_to_id if m.HasField("reply_to_id") else None,
                    attachments=atts,
                    reactions=rx,
                )
            )
        return out

    async def list_channels(
        self, caller: CallerContext, *, query: str = "", limit: int = 20
    ) -> list[ChannelSummary]:
        convs = await self._list_workspace_conversations(caller, limit=limit)
        needle = query.strip().lstrip("@#").lower()
        out: list[ChannelSummary] = []
        for c in convs:
            handle = c.handle if c.HasField("handle") else None
            title = c.title or handle or c.id
            if (
                needle
                and needle not in title.lower()
                and (not handle or needle not in handle.lower())
            ):
                continue
            members: list[dict[str, JSON]] = [
                {
                    "actor_type": m.actor_type,
                    "actor_id": m.actor_id,
                    "role": m.role,
                }
                for m in c.members
            ]
            snippet = (
                c.last_message_preview.snippet
                if c.HasField("last_message_preview")
                else ""
            )
            out.append(
                ChannelSummary(
                    address=f"chat:{c.id}",
                    channel="chat",
                    kind=c.type,
                    title=title,
                    handle=handle,
                    unread_count=int(c.unread_count),
                    last_message_snippet=snippet,
                    members=members,
                )
            )
        return out[:limit]

    async def set_typing(
        self, caller: CallerContext, target: str, active: bool
    ) -> None:
        conv_id = await self._resolve_conversation_id(caller, target)
        await self.chat.SetTyping(
            chat_pb.SetTypingRequest(
                workspace_id=str(caller.workspace_id),
                conversation_id=conv_id,
                active=active,
            ),
            metadata=Actor("agent", caller.leta_id).metadata,
            timeout=5,
        )

    async def mark_read(self, caller: CallerContext, target: str, seq: int) -> None:
        if seq <= 0:
            return
        conv_id = await self._resolve_conversation_id(caller, target)
        await self.chat.MarkRead(
            chat_pb.MarkReadRequest(
                workspace_id=str(caller.workspace_id),
                conversation_id=conv_id,
                seq=seq,
            ),
            metadata=Actor("agent", caller.leta_id).metadata,
            timeout=10,
        )
