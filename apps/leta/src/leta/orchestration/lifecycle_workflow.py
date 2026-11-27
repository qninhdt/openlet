"""Temporal workflow orchestrating Leta instance provisioning and teardown."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Literal
from uuid import UUID

from openlet_sdk.config import ReasoningEffort
from pydantic import BaseModel, Field
from temporalio import workflow
from temporalio.common import RetryPolicy


class LetaCreateInput(BaseModel):
    """Input payload for provisioning a new Leta instance."""

    leta_id: UUID
    workspace_id: UUID
    owner_user_id: UUID
    storage_id: UUID
    root_node_id: UUID
    name: str
    title: str
    description: str = ""
    custom_instructions: str = ""
    model_id: str | None = None
    reasoning_effort: ReasoningEffort = None
    appearance: dict[str, str] = Field(default_factory=dict[str, str])


class LetaLifecycleInput(BaseModel):
    """Input payload dispatching Leta creation or deletion in LetaLifecycleWorkflow."""

    action: Literal["create", "delete"]
    leta_id: UUID
    workspace_id: UUID
    create: LetaCreateInput | None = None


@workflow.defn(name="LetaLifecycleWorkflow")
class LetaLifecycleWorkflow:
    """Durable workflow coordinating Leta DB, SpiceDB, LetFS, and Temporal lifecycle."""

    @workflow.run
    async def run(self, payload: LetaLifecycleInput) -> dict[str, str]:
        """Execute creation provisioning or archival cleanup for a Leta instance."""
        retry = RetryPolicy(
            initial_interval=timedelta(seconds=1),
            maximum_interval=timedelta(seconds=30),
            maximum_attempts=10,
        )
        if payload.action == "create":
            if payload.create is None:
                raise RuntimeError("create payload is required when action == 'create'")
            handle: str = await workflow.execute_local_activity(
                "prepare_leta_db",
                payload.create,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            await workflow.execute_activity(
                "provision_leta_resources",
                payload.create,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry,
            )
            return {
                "leta_id": str(payload.leta_id),
                "handle": handle,
                "state": "active",
            }

        await workflow.execute_local_activity(
            "mark_leta_deleting",
            payload.leta_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry,
        )
        await asyncio.gather(
            workflow.execute_activity(
                "cleanup_leta_schedules",
                payload.leta_id,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry,
            ),
            workflow.execute_activity(
                "cleanup_leta_hitl",
                payload.leta_id,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry,
            ),
            workflow.execute_activity(
                "cleanup_leta_agents",
                payload.leta_id,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=retry,
            ),
        )
        await workflow.execute_activity(
            "cleanup_leta_resources",
            args=[payload.workspace_id, payload.leta_id],
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry,
        )
        return {"leta_id": str(payload.leta_id), "state": "archived"}
