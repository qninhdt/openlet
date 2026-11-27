from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal, override
from uuid import UUID

import grpc
import grpc.aio
from openlet_api.leta.v1 import internal_pb2 as pb
from openlet_api.leta.v1 import internal_pb2_grpc as pb_grpc
from openlet_sdk.config import JSON
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from ..config import Services
from ..db import json_value
from ..inbox import InboxItem, InboxSender
from ..orchestration.lifecycle_workflow import LetaLifecycleInput, LetaLifecycleWorkflow

logger = logging.getLogger(__name__)


def _parse_actor(actor: pb.ActorRef) -> InboxSender:
    actor_type: Literal["user", "agent", "system"] = (
        actor.type if actor.type in ("user", "agent", "system") else "system"
    )
    return InboxSender(
        type=actor_type,
        id=actor.id,
        name=actor.name,
        handle=actor.handle,
    )


class LetaInternalServicer(pb_grpc.LetaInternalServiceServicer):
    def __init__(self, services: Services) -> None:
        self.s = services

    @override
    async def DeliverInbox(
        self,
        request: pb.DeliverInboxRequest,
        context: grpc.aio.ServicerContext[
            pb.DeliverInboxRequest, pb.DeliverInboxResponse
        ],
    ) -> pb.DeliverInboxResponse:
        try:
            agent_id = UUID(request.agent_id)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid agent_id")
            return pb.DeliverInboxResponse()

        event_kind = request.WhichOneof("event")
        if event_kind == "chat_reaction":
            ev = request.chat_reaction
            item = InboxItem(
                agent_id=agent_id,
                idempotency_key=request.idempotency_key,
                kind="reaction",
                channel="chat",
                reply_address=f"chat:{ev.conversation_id}",
                sender=_parse_actor(ev.actor),
                content="",
                metadata={
                    "workspace_id": ev.workspace_id,
                    "conversation_id": ev.conversation_id,
                    "target_message_id": ev.message_id,
                    "emoji": ev.emoji,
                    "action": ev.action,
                },
                silent=True,
            )
        elif event_kind == "chat_message":
            ev = request.chat_message
            extra_meta: JSON = {}
            if ev.metadata_json:
                try:
                    extra_meta = json_value(
                        json.loads(ev.metadata_json.decode("utf-8"))
                    )
                except Exception:
                    await context.abort(
                        grpc.StatusCode.INVALID_ARGUMENT, "invalid metadata_json"
                    )
                    return pb.DeliverInboxResponse()
            attachments: list[dict[str, JSON]] = [
                {
                    "storage_id": att.storage_id,
                    "node_id": att.node_id,
                    "name": att.name,
                    "media_type": att.media_type,
                }
                for att in ev.attachments
            ]
            mentions: list[JSON] = [
                {
                    "kind": m.kind,
                    "id": m.id,
                    **({"storage_id": m.storage_id} if m.storage_id else {}),
                    **({"node_id": m.node_id} if m.node_id else {}),
                    "label": m.label,
                }
                for m in ev.mentions
            ]
            item = InboxItem(
                agent_id=agent_id,
                idempotency_key=request.idempotency_key,
                kind="channel",
                channel="chat",
                reply_address=f"chat:{ev.conversation_id}",
                sender=_parse_actor(ev.sender),
                content=ev.content,
                attachments=attachments,
                metadata={
                    "workspace_id": ev.workspace_id,
                    "conversation_id": ev.conversation_id,
                    "conversation_type": ev.conversation_type,
                    "title": ev.title,
                    "handle": ev.handle or None,
                    "message_id": ev.message_id,
                    "seq": ev.seq,
                    "reply_to_message_id": ev.reply_to_message_id or None,
                    "mentions": mentions,
                    "metadata": extra_meta,
                },
                silent=False,
            )
        else:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "missing event payload"
            )
            return pb.DeliverInboxResponse()

        result = await self.s.inbox.deliver(item)
        if result.skipped:
            await context.abort(grpc.StatusCode.NOT_FOUND, "agent not active")
            return pb.DeliverInboxResponse()
        return pb.DeliverInboxResponse(
            delivered=result.delivered,
            skipped=result.skipped,
            seq=result.seq or 0,
        )

    @override
    async def DeleteWorkspaceAgents(
        self,
        request: pb.DeleteWorkspaceAgentsRequest,
        context: grpc.aio.ServicerContext[
            pb.DeleteWorkspaceAgentsRequest, pb.DeleteWorkspaceAgentsResponse
        ],
    ) -> pb.DeleteWorkspaceAgentsResponse:
        try:
            workspace_id = UUID(request.workspace_id)
        except ValueError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "invalid workspace_id"
            )
            return pb.DeleteWorkspaceAgentsResponse()

        async with self.s.db.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT id FROM letas WHERE workspace_id = %s AND state <> 'archived'",
                    (workspace_id,),
                )
            ).fetchall()

        if rows:
            await asyncio.gather(
                *(
                    self.s.temporal.execute_workflow(
                        LetaLifecycleWorkflow.run,
                        LetaLifecycleInput(
                            action="delete",
                            leta_id=UUID(str(row["id"])),
                            workspace_id=workspace_id,
                        ),
                        id=f"leta-op/{row['id']}/delete",
                        task_queue=self.s.queues.orchestration,
                        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    )
                    for row in rows
                )
            )
        return pb.DeleteWorkspaceAgentsResponse()


async def start_internal_grpc(services: Services) -> grpc.aio.Server:
    server = grpc.aio.server()
    pb_grpc.add_LetaInternalServiceServicer_to_server(
        LetaInternalServicer(services), server
    )
    listen = services.settings.grpc_listen
    server.add_insecure_port(listen)
    await server.start()
    logger.info("leta internal gRPC listening on %s", listen)
    return server
