import asyncio
from datetime import timedelta
from typing import cast
from uuid import UUID

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError

from .retry import RETRY

with workflow.unsafe.imports_passed_through():
    from openlet_sdk.config import JSON
    from pydantic import BaseModel

    from ..messages import Message


class AgentInput(BaseModel):
    agent_id: UUID
    runtime_queue: str
    inbox_cursor: int = 0
    admitted_seq: int = 0
    suppressed_through: int = 0


class RunInput(BaseModel):
    agent_id: UUID
    run_id: UUID


class RunResult(BaseModel):
    status: str
    inbox_cursor: int


@workflow.defn
class Agent:
    @workflow.init
    def __init__(self, input: AgentInput) -> None:
        self.input = input
        self.wake = True
        self.inbox_cursor = input.inbox_cursor
        self.admitted_seq = input.admitted_seq
        self.suppressed_through = input.suppressed_through
        self.paused = False
        self.stopping = False
        self.stopped = False
        self.rotating = False
        self.active: workflow.ActivityHandle[RunResult] | None = None
        self.run_id: UUID | None = None
        self.control = asyncio.Lock()

    def rotate(self) -> None:
        self.rotating |= workflow.info().is_continue_as_new_suggested()

    @workflow.update
    async def receive(self, message: Message) -> dict[str, JSON]:
        result = await workflow.execute_local_activity(
            "admit_input",
            message,
            retry_policy=RETRY,
            start_to_close_timeout=timedelta(seconds=15),
            result_type=dict[str, JSON],
        )
        seq = result.get("seq")
        if isinstance(seq, int) and not message.silent:
            self.admitted_seq = max(self.admitted_seq, seq)
        self.rotate()
        return result

    @receive.validator
    def validate_receive(self, message: Message) -> None:
        if message.recipient_agent_id != self.input.agent_id:
            raise ValueError("recipient does not match workflow")
        if self.stopped or self.stopping or self.rotating:
            raise ApplicationError(
                "agent execution is rotating or stopping", type="admission_closed"
            )

    @workflow.update
    async def refresh_control(self) -> None:
        async with self.control:
            state = await self.load()
            self.paused = bool(state["paused"])
            self.stopping |= not bool(state["active"])
            if not self.paused:
                self.wake = True
        self.rotate()

    @workflow.update
    async def cancel_current(self, run_id: UUID) -> None:
        if self.run_id == run_id and self.active is not None:
            self.wake = False
            self.suppressed_through = max(self.suppressed_through, self.admitted_seq)
            handle = self.active
            handle.cancel()
            await workflow.wait_condition(lambda: self.active is not handle)
        else:
            await workflow.execute_local_activity(
                "finish_run",
                args=[run_id, "cancelled", None],
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(seconds=15),
            )
        self.rotate()

    @workflow.update
    async def stop(self) -> None:
        self.stopping = True
        await workflow.wait_condition(lambda: self.stopped)

    async def load(self) -> dict[str, JSON]:
        return await workflow.execute_local_activity(
            "load_agent_control",
            self.input.agent_id,
            retry_policy=RETRY,
            start_to_close_timeout=timedelta(seconds=15),
            result_type=dict[str, JSON],
        )

    @workflow.run
    async def run(self, input: AgentInput) -> None:
        while not self.stopping:
            await workflow.wait_condition(
                lambda: (
                    self.stopping
                    or self.rotating
                    or (
                        (
                            self.wake
                            or self.admitted_seq
                            > max(self.inbox_cursor, self.suppressed_through)
                        )
                        and not self.paused
                    )
                )
            )
            if self.stopping or self.rotating:
                break
            self.wake = False
            async with self.control:
                state = await self.load()
                self.paused = bool(state["paused"])
                if not state["active"]:
                    self.stopping = True
                    break
                if self.paused:
                    continue
                self.run_id = (
                    UUID(str(state["run_id"]))
                    if state.get("run_id")
                    else workflow.uuid4()
                )
            self.active = workflow.start_activity(
                "run_agent",
                RunInput(agent_id=input.agent_id, run_id=self.run_id),
                task_queue=input.runtime_queue,
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(days=365),
                heartbeat_timeout=timedelta(seconds=10),
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                result_type=RunResult,
            )
            await workflow.wait_condition(
                lambda: (
                    cast(workflow.ActivityHandle[RunResult], self.active).done()
                    or self.stopping
                    or self.rotating
                )
            )
            if self.stopping or self.rotating:
                self.active.cancel()
            status = "completed"
            error: str | None = None
            try:
                result = await self.active
                self.inbox_cursor = max(self.inbox_cursor, result.inbox_cursor)
                if result.status == "paused":
                    self.paused = True
                    status = "paused"
            except CancelledError, asyncio.CancelledError:
                status = "cancelled"
            except ActivityError as failure:
                if isinstance(failure.cause, CancelledError):
                    status = "cancelled"
                else:
                    status, error = "failed", "runtime_error"
            if status == "failed":
                # A permanent failure must not repeatedly restart the same backlog.
                self.suppressed_through = max(
                    self.suppressed_through, self.admitted_seq
                )
            if not self.rotating:
                await workflow.execute_local_activity(
                    "finish_run",
                    args=[self.run_id, status, error],
                    retry_policy=RETRY,
                    start_to_close_timeout=timedelta(seconds=15),
                )
            self.active = None
            self.rotate()
        if self.rotating and not self.stopping:
            await workflow.wait_condition(workflow.all_handlers_finished)
            workflow.continue_as_new(
                input.model_copy(
                    update={
                        "inbox_cursor": self.inbox_cursor,
                        "admitted_seq": self.admitted_seq,
                        "suppressed_through": self.suppressed_through,
                    }
                )
            )
        self.stopped = True
        await workflow.wait_condition(workflow.all_handlers_finished)
