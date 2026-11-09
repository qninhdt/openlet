import asyncio
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid7

import pytest
from temporalio import activity, workflow
from temporalio.client import (
    WorkflowFailureError,
    WorkflowUpdateFailedError,
    WorkflowUpdateStage,
)
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

from leta.domain import NewMessage, Source
from leta.temporal.agent import AgentWorkflow
from leta.temporal.bridges import control_agent, deliver_agent_input, start_agent
from leta.temporal.publication import PublicationActivities
from leta.temporal.types import (
    ORCHESTRATION_QUEUE,
    RUNTIME_QUEUE,
    AgentControl,
    AgentInput,
    AgentRef,
    AgentStart,
    Bootstrap,
    InboxReceipt,
    RunControl,
    RunInput,
    RunResult,
)


def incoming(ref, **changes):
    return AgentInput(
        message=NewMessage(
            id=uuid7(),
            leta_id=ref.leta_id,
            recipient_agent_id=ref.agent_id,
            source=Source(type="fixture", id="source", label="Source"),
            content="work",
            **changes,
        )
    )


class ControlledAgent:
    def __init__(self):
        self.seq = 0
        self.calls = []
        self.messages = {}
        self.entered, self.release, self.cleaned = (asyncio.Event() for _ in range(3))
        self.boot_started, self.boot_release = asyncio.Event(), asyncio.Event()
        self.boot_release.set()
        self.paused = False
        self.yielded = asyncio.Event()
        self.persisted = asyncio.Event()

    @activity.defn
    async def bootstrap_agent(self, value: AgentRef) -> Bootstrap:
        snapshot = self.seq
        self.boot_started.set()
        await self.boot_release.wait()
        return Bootstrap(
            latest_seq=snapshot, cursor=0, paused=self.paused, stopped=False
        )

    @activity.defn
    async def persist_inbox(self, value: AgentInput) -> InboxReceipt:
        message = value.message
        if message.id not in self.messages:
            self.seq += 1
            self.messages[message.id] = self.seq
        self.persisted.set()
        return InboxReceipt(
            message_id=message.id,
            agent_id=message.recipient_agent_id,
            seq=self.messages[message.id],
        )

    @activity.defn
    async def save_run_control(self, value: RunControl) -> str:
        if value.action == "stop":
            return "cancelled"
        self.yielded.set()
        self.release.set()
        return "running"

    @activity.defn
    async def run_agent(self, value: RunInput) -> RunResult:
        self.calls.append(value.run_id)
        self.entered.set()
        try:
            while not self.release.is_set():
                activity.heartbeat()
                try:
                    await asyncio.wait_for(self.release.wait(), 0.1)
                except TimeoutError:
                    pass
            outcome = "yielded" if self.yielded.is_set() else "completed"
            if outcome == "yielded":
                self.yielded.clear()
                self.release.clear()
            return RunResult(cursor=self.seq, outcome=outcome)
        finally:
            self.cleaned.set()

    def sql(self):
        return [
            self.bootstrap_agent,
            self.persist_inbox,
            self.save_run_control,
            PublicationActivities(None).publish_resource_event,
        ]


async def wait_for_state(handle, predicate):
    async with asyncio.timeout(15):
        while True:
            state = await handle.query(AgentWorkflow.status)
            if predicate(state):
                return state
            await asyncio.sleep(0.01)


async def retain_history(handle, name):
    directory = os.getenv("OPENLET_TEST_TEMPORAL_HISTORY_DIR")
    if directory:
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{name}.json").write_text((await handle.fetch_history()).to_json())


async def test_busy_receive_commit_ack_and_stop_cleanup(temporal_environment):
    client, fake = temporal_environment.client, ControlledAgent()
    ref = AgentStart(leta_id=uuid7(), agent_id=uuid7())
    async with (
        Worker(
            client,
            task_queue=ORCHESTRATION_QUEUE,
            workflows=[AgentWorkflow],
            activities=fake.sql(),
        ),
        Worker(
            client,
            task_queue=RUNTIME_QUEUE,
            activities=[fake.run_agent],
            max_heartbeat_throttle_interval=timedelta(seconds=1),
        ),
        asyncio.timeout(20),
    ):
        first = incoming(ref)
        assert (await deliver_agent_input(client, first)).seq == 1
        await fake.entered.wait()
        assert (await deliver_agent_input(client, incoming(ref))).seq == 2
        assert (await deliver_agent_input(client, first)).seq == 1
        assert len(fake.calls) == 1 and not fake.cleaned.is_set()
        state = await control_agent(client, ref.agent_id, AgentControl(action="stop"))
        assert state.stopped and fake.cleaned.is_set()
        await client.get_workflow_handle_for(
            AgentWorkflow.run, f"agent/{ref.agent_id}"
        ).result()
        await retain_history(
            client.get_workflow_handle(f"agent/{ref.agent_id}"), "busy-receive"
        )


async def test_receive_during_bootstrap_does_not_lose_wakeup(temporal_environment):
    client, fake = temporal_environment.client, ControlledAgent()
    fake.boot_release.clear()
    ref = AgentStart(leta_id=uuid7(), agent_id=uuid7())
    async with (
        Worker(
            client,
            task_queue=ORCHESTRATION_QUEUE,
            workflows=[AgentWorkflow],
            activities=fake.sql(),
        ),
        Worker(
            client,
            task_queue=RUNTIME_QUEUE,
            activities=[fake.run_agent],
            max_heartbeat_throttle_interval=timedelta(seconds=1),
        ),
        asyncio.timeout(20),
    ):
        handle = await start_agent(client, ref)
        await fake.boot_started.wait()
        async with asyncio.TaskGroup() as tasks:
            delivery = tasks.create_task(deliver_agent_input(client, incoming(ref)))
            await fake.persisted.wait()
            fake.boot_release.set()
        assert delivery.result().seq == 1
        await fake.entered.wait()
        state = await handle.query(AgentWorkflow.status)
        assert state.latest_seq == 1 and state.run_id is not None
        await control_agent(client, ref.agent_id, AgentControl(action="stop"))
        await handle.result()


async def test_paused_receive_resume_and_invalid_target(temporal_environment):
    client, fake = temporal_environment.client, ControlledAgent()
    fake.paused = True
    ref = AgentStart(leta_id=uuid7(), agent_id=uuid7())
    async with (
        Worker(
            client,
            task_queue=ORCHESTRATION_QUEUE,
            workflows=[AgentWorkflow],
            activities=fake.sql(),
        ),
        Worker(
            client,
            task_queue=RUNTIME_QUEUE,
            activities=[fake.run_agent],
            max_heartbeat_throttle_interval=timedelta(seconds=1),
        ),
        asyncio.timeout(20),
    ):
        await deliver_agent_input(client, incoming(ref))
        handle = client.get_workflow_handle_for(
            AgentWorkflow.run, f"agent/{ref.agent_id}"
        )
        await wait_for_state(handle, lambda s: s.paused and s.latest_seq == 1)
        assert not fake.calls
        wrong = AgentRef(leta_id=ref.leta_id, agent_id=uuid7())
        with pytest.raises(WorkflowUpdateFailedError):
            await handle.execute_update(AgentWorkflow.receive, incoming(wrong))
        assert fake.seq == 1
        await control_agent(client, ref.agent_id, AgentControl(action="resume"))
        await fake.entered.wait()
        await control_agent(client, ref.agent_id, AgentControl(action="stop"))
        await handle.result()
        await retain_history(handle, "paused-receive")


async def test_paused_rotation_keeps_inbox_and_drains_updates(temporal_environment):
    client, fake = temporal_environment.client, ControlledAgent()
    fake.paused = True
    ref = AgentStart(leta_id=uuid7(), agent_id=uuid7(), history_events=35)
    async with (
        Worker(
            client,
            task_queue=ORCHESTRATION_QUEUE,
            workflows=[AgentWorkflow],
            activities=fake.sql(),
        ),
        asyncio.timeout(20),
    ):
        handle = await start_agent(client, ref)
        original_run = handle.result_run_id
        messages = [incoming(ref) for _ in range(12)]
        for value in messages:
            await deliver_agent_input(client, value)
        assert fake.seq == 12 and not fake.calls
        state = await wait_for_state(handle, lambda s: s.latest_seq == 12)
        assert state.paused and state.cursor == 0
        assert (await handle.describe()).run_id != original_run
        assert (await deliver_agent_input(client, messages[0])).seq == 1
        await control_agent(client, ref.agent_id, AgentControl(action="stop"))
        await handle.result()
        await retain_history(
            client.get_workflow_handle(handle.id, run_id=original_run),
            "paused-rotation",
        )


async def test_active_rotation_yields_and_continues_same_run(temporal_environment):
    client, fake = temporal_environment.client, ControlledAgent()
    ref = AgentStart(leta_id=uuid7(), agent_id=uuid7(), history_events=40)
    async with (
        Worker(
            client,
            task_queue=ORCHESTRATION_QUEUE,
            workflows=[AgentWorkflow],
            activities=fake.sql(),
        ),
        Worker(
            client,
            task_queue=RUNTIME_QUEUE,
            activities=[fake.run_agent],
            max_heartbeat_throttle_interval=timedelta(seconds=1),
        ),
        asyncio.timeout(20),
    ):
        handle = await start_agent(client, ref)
        original_run = handle.result_run_id
        await deliver_agent_input(client, incoming(ref))
        await fake.entered.wait()
        business_run = fake.calls[0]
        for _ in range(9):
            await deliver_agent_input(client, incoming(ref))
        async with asyncio.timeout(10):
            while len(fake.calls) < 2:
                await asyncio.sleep(0.01)
        assert set(fake.calls) == {business_run}
        assert (await handle.describe()).run_id != original_run
        assert (await handle.query(AgentWorkflow.status)).run_id == business_run
        await control_agent(client, ref.agent_id, AgentControl(action="stop"))
        await handle.result()
        await retain_history(
            client.get_workflow_handle(handle.id, run_id=original_run),
            "active-rotation",
        )


class FailedAgent(ControlledAgent):
    @activity.defn
    async def run_agent(self, value: RunInput) -> RunResult:
        self.calls.append(value.run_id)
        raise ApplicationError("invalid run configuration", non_retryable=True)


async def test_terminal_runner_failure_surfaces_without_spinning(temporal_environment):
    client, fake = temporal_environment.client, FailedAgent()
    ref = AgentStart(leta_id=uuid7(), agent_id=uuid7())
    async with (
        Worker(
            client,
            task_queue=ORCHESTRATION_QUEUE,
            workflows=[AgentWorkflow],
            activities=fake.sql(),
        ),
        Worker(client, task_queue=RUNTIME_QUEUE, activities=[fake.run_agent]),
        asyncio.timeout(15),
    ):
        await deliver_agent_input(client, incoming(ref))
        with pytest.raises(WorkflowFailureError):
            await client.get_workflow_handle(f"agent/{ref.agent_id}").result()
        assert fake.seq == 1 and len(fake.calls) == 1


@workflow.defn
class RotationStopFixture(AgentWorkflow):
    @workflow.init
    def __init__(self, start: AgentStart):
        super().__init__(start)
        self.blocked = self.rotation_seen = self.released = False

    @workflow.run
    async def run(self, start: AgentStart) -> None:
        await super().run(start)

    def rotate(self):
        if self.blocked:
            self.rotation_seen = True
        return self.blocked

    @workflow.update
    async def hold_handler(self) -> bool:
        self.blocked = True
        await workflow.wait_condition(lambda: self.released)
        self.blocked = False
        return True

    @workflow.signal
    def release_handler(self):
        self.released = True

    @workflow.query
    def draining(self) -> bool:
        return self.rotation_seen


async def test_stop_breaks_rotation_drain_before_waiting_for_other_handlers(
    temporal_environment,
):
    client, fake = temporal_environment.client, ControlledAgent()
    fake.paused = True
    ref = AgentStart(leta_id=uuid7(), agent_id=uuid7())
    async with (
        Worker(
            client,
            task_queue=ORCHESTRATION_QUEUE,
            workflows=[RotationStopFixture],
            activities=fake.sql(),
        ),
        asyncio.timeout(15),
    ):
        handle = await client.start_workflow(
            RotationStopFixture.run,
            ref,
            id=f"agent/{ref.agent_id}",
            task_queue=ORCHESTRATION_QUEUE,
        )
        held = await handle.start_update(
            RotationStopFixture.hold_handler,
            wait_for_stage=WorkflowUpdateStage.ACCEPTED,
        )
        async with asyncio.timeout(5):
            while not await handle.query(RotationStopFixture.draining):
                await asyncio.sleep(0.01)
        stopped = await handle.execute_update(
            RotationStopFixture.control, AgentControl(action="stop")
        )
        assert stopped.stopped
        await handle.signal(RotationStopFixture.release_handler)
        assert await held.result()
        await handle.result()
