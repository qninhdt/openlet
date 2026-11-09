import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ApplicationError, is_cancelled_exception

with workflow.unsafe.imports_passed_through():
    from leta.temporal.publication import publish
    from leta.temporal.types import (
        RUNTIME_QUEUE,
        AgentControl,
        AgentInput,
        AgentRef,
        AgentStart,
        AgentState,
        Bootstrap,
        InboxReceipt,
        RunControl,
        RunInput,
        RunResult,
    )


async def local(name, value, result_type):
    return await workflow.execute_local_activity(
        name,
        value,
        result_type=result_type,
        start_to_close_timeout=timedelta(seconds=5),
    )


@workflow.defn
class AgentWorkflow:
    @workflow.init
    def __init__(self, start: AgentStart):
        self.start = start
        self.state = AgentState(
            cursor=start.cursor,
            run_id=start.run_id,
            continuation=start.continuation,
            paused=start.paused,
        )
        self.receiving = asyncio.Lock()
        self.active = None
        self.control_seen = False
        self.stop_complete = False

    def ref(self):
        return AgentRef(leta_id=self.start.leta_id, agent_id=self.start.agent_id)

    def run_input(self):
        return RunInput(
            leta_id=self.start.leta_id,
            agent_id=self.start.agent_id,
            run_id=self.state.run_id,
        )

    def merge(self, **changes):
        self.state = self.state.model_copy(update=changes)

    def rotate(self):
        info = workflow.info()
        return (
            info.is_continue_as_new_suggested()
            or info.get_current_history_length() >= self.start.history_events
            or info.get_current_history_size() >= self.start.history_bytes
        )

    @workflow.query
    def status(self) -> AgentState:
        return self.state

    @workflow.update
    async def receive(self, value: AgentInput) -> InboxReceipt:
        async with self.receiving:
            receipt = await local("persist_inbox", value, InboxReceipt)
            await publish(self.start.leta_id, "message", receipt.message_id)
            self.merge(latest_seq=max(self.state.latest_seq, receipt.seq))
            return receipt

    @receive.validator
    def validate_receive(self, value: AgentInput):
        if (
            value.message.leta_id != self.start.leta_id
            or value.message.recipient_agent_id != self.start.agent_id
        ):
            raise ApplicationError(
                "input targets another agent", type="VALIDATION", non_retryable=True
            )

    @workflow.update
    async def control(self, value: AgentControl) -> AgentState:
        if value.action == "stop":
            self.merge(stopped=True)
            if self.active is not None:
                self.active.cancel()
            await workflow.wait_condition(lambda: self.stop_complete)
        elif value.action in {"pause", "resume"}:
            self.control_seen = True
            self.merge(paused=value.action == "pause")
        elif value.run_id == self.state.run_id and self.active is not None:
            await local(
                "save_run_control", RunControl(**self.run_input().model_dump()), str
            )
        return self.state

    @workflow.run
    async def run(self, start: AgentStart) -> None:
        boot = await local("bootstrap_agent", self.ref(), Bootstrap)
        if start.run_id and boot.run_id and start.run_id != boot.run_id:
            raise ApplicationError(
                "unfinished run changed", type="STATE_CONFLICT", non_retryable=True
            )
        self.merge(
            latest_seq=max(self.state.latest_seq, boot.latest_seq),
            cursor=max(self.state.cursor, boot.cursor),
            run_id=boot.run_id or start.run_id,
            continuation=bool(boot.run_id or start.continuation),
            paused=self.state.paused if self.control_seen else boot.paused,
            stopped=self.state.stopped or boot.stopped,
        )
        while not self.state.stopped:
            await workflow.wait_condition(
                lambda: (
                    self.state.stopped
                    or self.rotate()
                    or (
                        not self.state.paused
                        and (
                            self.state.continuation
                            or self.state.latest_seq > self.state.cursor
                        )
                    )
                )
            )
            if self.state.stopped:
                break
            if self.rotate():
                await workflow.wait_condition(
                    lambda: workflow.all_handlers_finished() or self.state.stopped
                )
                if self.state.stopped:
                    break
                workflow.continue_as_new(
                    AgentStart(
                        leta_id=self.start.leta_id,
                        agent_id=self.start.agent_id,
                        cursor=self.state.cursor,
                        run_id=self.state.run_id,
                        continuation=self.state.continuation,
                        paused=self.state.paused,
                        history_events=start.history_events,
                        history_bytes=start.history_bytes,
                    )
                )
            if self.state.run_id is None:
                self.merge(run_id=workflow.uuid4())
                # Reserve before dispatch: rotation can precede runtime pickup.
                await local("bootstrap_agent", self.run_input(), Bootstrap)
                if self.state.stopped:
                    break
            self.active = workflow.start_activity(
                "run_agent",
                self.run_input(),
                result_type=RunResult,
                task_queue=RUNTIME_QUEUE,
                start_to_close_timeout=timedelta(days=7),
                heartbeat_timeout=timedelta(seconds=10),
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
            )
            try:
                await workflow.wait_condition(
                    lambda: self.active.done() or self.state.stopped or self.rotate()
                )
                if self.state.stopped:
                    self.active.cancel()
                elif self.rotate() and not self.active.done():
                    await local(
                        "save_run_control",
                        RunControl(**self.run_input().model_dump()),
                        str,
                    )
                result = await self.active
                if result.cursor < self.state.cursor:
                    raise ApplicationError(
                        "run moved inbox cursor backward",
                        type="STATE_CONFLICT",
                        non_retryable=True,
                    )
                self.merge(
                    cursor=result.cursor,
                    latest_seq=max(self.state.latest_seq, result.cursor),
                    continuation=result.outcome != "completed",
                    run_id=None if result.outcome == "completed" else self.state.run_id,
                )
                if result.outcome == "paused":
                    self.control_seen = False
                    current = await local("bootstrap_agent", self.ref(), Bootstrap)
                    if not self.control_seen:
                        self.merge(paused=current.paused)
            except BaseException as error:
                if not (self.state.stopped and is_cancelled_exception(error)):
                    if not is_cancelled_exception(error):
                        await workflow.wait_condition(workflow.all_handlers_finished)
                    raise
            finally:
                self.active = None
        if self.state.run_id is not None:
            await local(
                "save_run_control",
                RunControl(**self.run_input().model_dump(), action="stop"),
                str,
            )
        self.stop_complete = True
        await workflow.wait_condition(workflow.all_handlers_finished)
