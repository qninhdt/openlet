from __future__ import annotations

import json
import logging
from typing import cast
from uuid import UUID, uuid4

import grpc
import grpc.aio
from google.protobuf.empty_pb2 import Empty
from openlet_api.leta.v1 import internal_pb2 as pb
from openlet_api.leta.v1 import internal_pb2_grpc as pb_grpc
from openlet_sdk.config import JSON
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from ..config import Services
from ..inbox import InboxItem, InboxKind, InboxSender
from ..orchestration.lifecycle_workflow import LetaLifecycleInput, LetaLifecycleWorkflow

logger = logging.getLogger(__name__)


class LetaInternalServicer(pb_grpc.LetaInternalServiceServicer):
    def __init__(self, services: Services) -> None:
        self.s = services

    async def DeliverInbox(
        self,
        request: pb.DeliverInboxRequest,
        context: grpc.aio.ServicerContext[pb.DeliverInboxRequest, Empty],
    ) -> Empty:
        try:
            agent_id = UUID(request.agent_id)
        except ValueError:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid agent_id")
            return Empty()

        attachments: list[dict[str, JSON]] = []
        if request.attachments_json:
            try:
                parsed = json.loads(request.attachments_json.decode("utf-8"))
                if isinstance(parsed, list):
                    attachments = cast(list[dict[str, JSON]], parsed)
            except Exception:
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT, "invalid attachments_json"
                )
                return Empty()

        metadata: dict[str, JSON] = {}
        if request.metadata_json:
            try:
                parsed_meta = json.loads(request.metadata_json.decode("utf-8"))
                if isinstance(parsed_meta, dict):
                    metadata = cast(dict[str, JSON], parsed_meta)
            except Exception:
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT, "invalid metadata_json"
                )
                return Empty()

        sender_type = request.sender.type if request.HasField("sender") else "system"
        if sender_type not in ("user", "agent", "system"):
            sender_type = "system"
        sender = InboxSender(
            type=sender_type,
            id=request.sender.id if request.HasField("sender") else "",
            name=request.sender.name if request.HasField("sender") else "",
            handle=request.sender.handle if request.HasField("sender") else "",
        )
        kind: InboxKind = (
            "notification" if request.kind == "notification" else "channel"
        )
        result = await self.s.inbox.deliver(
            InboxItem(
                agent_id=agent_id,
                idempotency_key=request.idempotency_key,
                kind=kind,
                channel=request.channel or "chat",
                reply_address=request.reply_address or None,
                sender=sender,
                content=request.content,
                attachments=attachments,
                metadata=metadata,
                silent=bool(request.silent),
            )
        )
        if result.skipped:
            await context.abort(grpc.StatusCode.NOT_FOUND, "agent not active")
            return Empty()
        return Empty()

    async def DeleteWorkspaceAgents(
        self,
        request: pb.DeleteWorkspaceAgentsRequest,
        context: grpc.aio.ServicerContext[pb.DeleteWorkspaceAgentsRequest, Empty],
    ) -> Empty:
        try:
            workspace_id = UUID(request.workspace_id)
        except ValueError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "invalid workspace_id"
            )
            return Empty()

        async with self.s.db.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT id FROM letas WHERE workspace_id = %s AND state <> 'archived'",
                    (workspace_id,),
                )
            ).fetchall()

        for row in rows:
            leta_id = UUID(str(row["id"]))
            await self.s.temporal.execute_workflow(
                LetaLifecycleWorkflow.run,
                LetaLifecycleInput(
                    action="delete", leta_id=leta_id, workspace_id=workspace_id
                ),
                id=f"leta-op/{leta_id}/delete/{uuid4()}",
                task_queue=self.s.queues.orchestration,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        return Empty()


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
