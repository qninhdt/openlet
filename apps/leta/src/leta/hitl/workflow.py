from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID

from openlet_sdk.config import JSON
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from .service import HitlDecisionInput, OpenHitlInput


@workflow.defn(name="HitlWorkflow")
class HitlWorkflow:
    @workflow.init
    def __init__(self, request: OpenHitlInput) -> None:
        self._decision: HitlDecisionInput | None = None
        self._request: OpenHitlInput = request
        self._resolved: dict[str, JSON] | None = None

    @workflow.update
    async def decide(self, decision: HitlDecisionInput) -> dict[str, JSON]:
        if self._decision is not None:
            raise ApplicationError("HITL request already resolved", non_retryable=True)
        if decision.actor_id != self._request.recipient_user_id:
            raise ApplicationError(
                "Only the designated recipient can decide this HITL request",
                non_retryable=True,
            )
        decision.resolved_at = workflow.now()
        try:
            result: dict[str, JSON] = await workflow.execute_activity(
                "resolve_hitl",
                decision,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception as exc:
            raise ApplicationError(str(exc), non_retryable=True) from exc
        self._decision = decision
        self._resolved = result
        return result

    @workflow.signal
    def cancel(self, actor_id: UUID) -> None:
        if self._decision is None:
            self._decision = HitlDecisionInput(
                request_id=self._request.id,
                actor_id=actor_id,
                status="cancelled",
                resolved_at=workflow.now(),
            )

    @workflow.run
    async def run(self, request: OpenHitlInput) -> dict[str, JSON]:
        request = self._request
        opened: dict[str, JSON] = await workflow.execute_activity(
            "open_hitl",
            request,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if opened.get("status") == "already_granted":
            return opened

        timeout: timedelta | None = None
        if request.expires_at is not None:
            delta = request.expires_at - workflow.now()
            timeout = delta if delta.total_seconds() > 0 else timedelta(seconds=0)

        try:
            await workflow.wait_condition(
                lambda: self._decision is not None, timeout=timeout
            )
        except asyncio.TimeoutError:
            self._decision = HitlDecisionInput(
                request_id=request.id,
                actor_id=request.recipient_user_id,
                status="expired",
                resolved_at=workflow.now(),
            )

        assert self._decision is not None
        if self._resolved is None:
            self._resolved = await workflow.execute_activity(
                "resolve_hitl",
                self._decision,
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )

        if request.type == "approval" and self._decision.status == "accepted":
            self._resolved = await workflow.execute_activity(
                "apply_hitl_effect",
                request.id,
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )

        await workflow.execute_activity(
            "deliver_hitl_result",
            request.id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )
        await workflow.wait_condition(workflow.all_handlers_finished)
        assert self._resolved is not None
        return self._resolved
