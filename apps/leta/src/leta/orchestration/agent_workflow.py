"""Durable Temporal workflow managing an agent's wake, pause, cancel, and turn loop."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, CancelledError


class AgentWorkflowState(BaseModel):
    """Serializable workflow state preserved across continue-as-new rotations."""

    agent_id: UUID
    leta_id: UUID
    is_root: bool
    processed_seq: int = 0
    known_seq: int = 0
    suppressed_through: int = 0
    paused: bool = False
    runtime_queue: str = "openlet-leta-runtime"
    run_timeout_seconds: int = 7200
    heartbeat_timeout_seconds: int = 15


class RunInput(BaseModel):
    """Input passed to the Layer 2 run_agent_turn activity."""

    agent_id: UUID
    run_id: UUID


class RunResult(BaseModel):
    """Result returned by run_agent_turn with updated inbox cursors."""

    inbox_cursor: int
    latest_wake_seq: int


class AgentStatus(BaseModel):
    """Query snapshot describing an agent workflow's current phase and cursors."""

    state: Literal["idle", "running", "paused", "stopping"]
    active_run_id: UUID | None
    processed_seq: int
    known_seq: int
    paused: bool


@workflow.defn(name="AgentWorkflow")
class AgentWorkflow:
    """Long-lived workflow serializing turn execution and signals for a single agent."""

    @workflow.init
    def __init__(self, state: AgentWorkflowState) -> None:
        self._state: AgentWorkflowState = state
        self._stopping: bool = False
        self._rotating: bool = False
        self._cancel_requested: bool = False
        self._active_run_id: UUID | None = None
        self._active_handle: workflow.ActivityHandle[RunResult] | None = None

    @workflow.signal
    def wake(self, seq: int) -> None:
        """Advance known_seq so the workflow schedules a turn if unpaused."""
        self._state.known_seq = max(self._state.known_seq, seq)

    @workflow.signal
    def cancel_run(self, run_id: UUID | None = None) -> None:
        """Cancel the active run (or specific run_id) and suppress pending wakes."""
        if run_id is not None and self._active_run_id != run_id:
            return
        self._state.suppressed_through = max(
            self._state.suppressed_through, self._state.known_seq
        )
        self._cancel_requested = True
        if self._active_handle is not None and not self._active_handle.done():
            self._active_handle.cancel()

    @workflow.signal
    def pause(
        self,
        cancel_active: bool = False,  # noqa: FBT001, FBT002  # Temporal @workflow.signal receives positional args
    ) -> None:
        """Pause new turn execution and optionally cancel the active run."""
        self._state.paused = True
        if cancel_active:
            self._cancel_requested = True
            if self._active_handle is not None and not self._active_handle.done():
                self._active_handle.cancel()

    @workflow.signal
    def resume(self) -> None:
        """Clear the paused flag so queued wakes can execute."""
        self._state.paused = False

    @workflow.signal
    def stop(self) -> None:
        """Signal the agent workflow to cancel any active run and shut down."""
        self._stopping = True
        if self._active_handle is not None and not self._active_handle.done():
            self._active_handle.cancel()

    @workflow.query
    def status(self) -> AgentStatus:
        """Return the current execution phase and sequence cursors."""
        st = self._state
        if self._stopping:
            phase: Literal["idle", "running", "paused", "stopping"] = "stopping"
        elif self._active_run_id is not None:
            phase = "running"
        elif st.paused:
            phase = "paused"
        else:
            phase = "idle"
        return AgentStatus(
            state=phase,
            active_run_id=self._active_run_id,
            processed_seq=st.processed_seq,
            known_seq=st.known_seq,
            paused=st.paused,
        )

    async def _collect_result(
        self, handle: workflow.ActivityHandle[RunResult]
    ) -> tuple[
        Literal["completed", "failed", "cancelled"], str | None, RunResult | None
    ]:
        try:
            res = await handle
        except CancelledError:
            return "cancelled", "cancelled", None
        except ActivityError as exc:
            if isinstance(exc.cause, CancelledError):
                return "cancelled", "cancelled", None
            return "failed", str(exc.cause or exc), None
        except asyncio.CancelledError:
            return "cancelled", "cancelled", None
        except Exception as exc:  # noqa: BLE001  # Workflow boundary records any unexpected activity failure
            return "failed", str(exc), None
        else:
            return "completed", None, res

    @workflow.run
    async def run(self, state: AgentWorkflowState) -> None:
        """Run the main agent wake/execute loop until stopped or rotated."""
        state = self._state
        while not self._stopping:
            await workflow.wait_condition(
                lambda: (
                    self._stopping
                    or self._rotating
                    or (
                        not state.paused
                        and state.known_seq
                        > max(state.processed_seq, state.suppressed_through)
                    )
                )
            )
            if self._stopping or self._rotating:
                break

            self._active_run_id = workflow.uuid4()
            self._cancel_requested = False
            self._active_handle = workflow.start_activity(
                "run_agent_turn",
                RunInput(agent_id=state.agent_id, run_id=self._active_run_id),
                task_queue=state.runtime_queue,
                start_to_close_timeout=timedelta(seconds=state.run_timeout_seconds),
                heartbeat_timeout=timedelta(seconds=state.heartbeat_timeout_seconds),
                cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=60),
                    maximum_attempts=8,
                    non_retryable_error_types=[
                        "ContextLimitError",
                        "AuthError",
                        "InvalidConfigError",
                    ],
                ),
                result_type=RunResult,
            )

            await workflow.wait_condition(
                lambda: (
                    (self._active_handle is not None and self._active_handle.done())
                    or self._stopping
                    or self._cancel_requested
                )
            )
            if (
                self._stopping or self._cancel_requested
            ) and not self._active_handle.done():
                self._active_handle.cancel()

            run_status, err_msg, res = await self._collect_result(self._active_handle)
            self._cancel_requested = False

            if run_status == "completed" and res is not None:
                state.processed_seq = max(state.processed_seq, res.inbox_cursor)
                state.known_seq = max(state.known_seq, res.latest_wake_seq)
            elif run_status == "failed":
                state.suppressed_through = max(
                    state.suppressed_through, state.known_seq
                )

            await workflow.execute_local_activity(
                "finish_run",
                args=[self._active_run_id, state.agent_id, run_status, err_msg],
                start_to_close_timeout=timedelta(seconds=15),
            )
            self._active_handle = None
            self._active_run_id = None

            if not state.is_root and run_status == "failed":
                await workflow.execute_activity(
                    "notify_parent_failure",
                    args=[state.agent_id, err_msg or "unknown error"],
                    start_to_close_timeout=timedelta(seconds=30),
                )

            if workflow.info().is_continue_as_new_suggested():
                self._rotating = True

        if self._stopping:
            await workflow.execute_activity(
                "stop_child_agents",
                state.agent_id,
                start_to_close_timeout=timedelta(minutes=2),
            )
            await workflow.wait_condition(workflow.all_handlers_finished)
            return

        if self._rotating:
            await workflow.wait_condition(workflow.all_handlers_finished)
            workflow.continue_as_new(state)
