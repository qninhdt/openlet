"""One finite coordinator per human request, independent of the agent loop."""

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from leta.human import RequestResolution
    from leta.temporal.agent import local
    from leta.temporal.human_types import (
        HumanRequestOutcome,
        HumanRequestRef,
        HumanRequestState,
        OpenHumanRequest,
        SettleHumanRequest,
    )
    from leta.temporal.publication import publish


@workflow.defn
class HumanRequestWorkflow:
    @workflow.init
    def __init__(self, start: HumanRequestRef):
        self.start = start
        self.changing = asyncio.Lock()
        self.state: HumanRequestState | None = None
        self.finished = False

    def validate_identity(self, value):
        if (
            value.leta_id != self.start.leta_id
            or value.request_id != self.start.request_id
        ):
            raise ApplicationError(
                "request targets another coordinator",
                type="VALIDATION",
                non_retryable=True,
            )

    @workflow.update
    async def open(self, value: OpenHumanRequest) -> HumanRequestState:
        async with self.changing:
            self.state = await local("open_hitl_request", value, HumanRequestState)
            saved = self.state
        await publish(self.start.leta_id, "human_request", self.start.request_id)
        return saved

    @open.validator
    def validate_open(self, value: OpenHumanRequest):
        self.validate_identity(value)

    @workflow.update
    async def resolve(self, value: RequestResolution) -> HumanRequestState:
        async with self.changing:
            self.state = await local("resolve_hitl_request", value, HumanRequestState)
            saved = self.state
        await publish(self.start.leta_id, "human_request", self.start.request_id)
        return saved

    @resolve.validator
    def validate_resolve(self, value: RequestResolution):
        self.validate_identity(value)

    @workflow.update
    async def settle(self, value: SettleHumanRequest) -> HumanRequestState:
        async with self.changing:
            self.state = await local(
                "open_hitl_request",
                OpenHumanRequest(**self.start.model_dump()),
                HumanRequestState,
            )
            if self.state.status == "pending":
                self.state = await local(
                    "resolve_hitl_request",
                    RequestResolution(
                        **self.start.model_dump(),
                        action="cancel",
                        requester_agent_id=value.leta_id,
                        reason=value.reason,
                    ),
                    HumanRequestState,
                )
        await publish(self.start.leta_id, "human_request", self.start.request_id)
        # The lock protects only the SQL transition, never grant or delivery.
        await workflow.wait_condition(lambda: self.finished)
        return self.state

    @settle.validator
    def validate_settle(self, value: SettleHumanRequest):
        self.validate_identity(value)

    @workflow.run
    async def run(self, start: HumanRequestRef) -> HumanRequestState:
        await workflow.wait_condition(lambda: self.state is not None)
        while self.state.status == "pending":
            try:
                timeout = (
                    max(self.state.expires_at - workflow.now(), timedelta())
                    if self.state.expires_at is not None
                    else None
                )
                await workflow.wait_condition(
                    lambda: self.state.status != "pending", timeout=timeout
                )
            except TimeoutError:
                async with self.changing:
                    self.state = await local(
                        "resolve_hitl_request",
                        RequestResolution(**start.model_dump(), action="expire"),
                        HumanRequestState,
                    )
                if self.state.status == "pending":
                    # SQL time decides expiry; tolerate a small server clock skew.
                    await workflow.sleep(timedelta(seconds=1))
                else:
                    await publish(start.leta_id, "human_request", start.request_id)
        if self.state.needs_grant:
            outcome = await workflow.execute_activity(
                "grant_requested_access",
                start,
                result_type=dict,
                start_to_close_timeout=timedelta(minutes=2),
            )
            async with self.changing:
                self.state = await local(
                    "save_hitl_outcome",
                    HumanRequestOutcome(**start.model_dump(), outcome=outcome),
                    HumanRequestState,
                )
            await publish(start.leta_id, "human_request", start.request_id)
        await workflow.execute_activity(
            "deliver_agent_input",
            self.state.delivery,
            result_type=str,
            start_to_close_timeout=timedelta(seconds=45),
        )
        self.finished = True
        await workflow.wait_condition(workflow.all_handlers_finished)
        return self.state
