import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from uuid import uuid7

import pytest
from temporalio.client import WorkflowUpdateFailedError
from temporalio.worker import Worker
from test_agent_workflow import ControlledAgent, incoming, wait_for_state
from test_store_integration import active_root

from leta.temporal.activities import AgentActivities
from leta.temporal.agent import AgentWorkflow
from leta.temporal.bridges import control_agent, deliver_agent_input, start_agent
from leta.temporal.publication import PublicationActivities
from leta.temporal.types import (
    ORCHESTRATION_QUEUE,
    AgentControl,
    AgentStart,
)
from leta.worker import agent_workers

pytestmark = pytest.mark.integration


async def test_post_commit_worker_loss_retries_exact_row(
    store, persistent_temporal, postgres_dsn, catalog_data
):
    client = persistent_temporal
    root = await active_root(store)
    # Keep graph work paused: this journey verifies delivery/SQL, not a fake runner.
    async with store.database.connection() as connection:
        await connection.execute(
            "UPDATE agents SET paused=true WHERE id=%s", (root.id,)
        )
    ref = AgentStart(leta_id=root.id, agent_id=root.id)
    sql = AgentActivities(store, client)
    value = incoming(ref)
    delivery = None
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("inbox_crash_worker.py")),
        env={
            **os.environ,
            "OPENLET_OWNED_INBOX_CRASH": json.dumps(
                {
                    "address": client.service_client.config.target_host,
                    "database_url": postgres_dsn,
                    "models": catalog_data,
                }
            ),
        },
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        handle = await start_agent(client, ref)
        delivery = asyncio.create_task(deliver_agent_input(client, value))
        async with asyncio.timeout(15):
            _, errors = await process.communicate()
            assert process.returncode == -signal.SIGKILL, errors.decode(
                errors="replace"
            )
        assert (await store.list_inbox(root.id, root.id))[0]["seq"] == 1
        # No worker can claim a successful application receipt during this gap.
        assert not delivery.done()
        async with (
            Worker(
                client,
                task_queue=ORCHESTRATION_QUEUE,
                workflows=[AgentWorkflow],
                activities=[
                    PublicationActivities(None).publish_resource_event,
                    sql.bootstrap_agent,
                    sql.persist_inbox,
                    sql.save_run_control,
                ],
            ),
            asyncio.timeout(20),
        ):
            receipt = await delivery
            assert receipt.message_id == value.message.id and receipt.seq == 1
            assert (await deliver_agent_input(client, value)) == receipt
            # A distinct Update ID forces DB validation rather than SDK dedup.
            changed = value.model_copy(
                update={
                    "message": value.message.model_copy(update={"content": "different"})
                }
            )
            with pytest.raises(WorkflowUpdateFailedError):
                await handle.execute_update(
                    AgentWorkflow.receive, changed, id=str(uuid7())
                )
            assert len(await store.list_inbox(root.id, root.id)) == 1
            state = await wait_for_state(handle, lambda state: state.latest_seq == 1)
            assert state.paused
            await control_agent(client, root.id, AgentControl(action="stop"))
            await handle.result()
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
        if delivery is not None and not delivery.done():
            delivery.cancel()
            await asyncio.gather(delivery, return_exceptions=True)


async def test_input_waits_for_worker_then_commits_once(store, persistent_temporal):
    client = persistent_temporal
    root = await active_root(store)
    ref = AgentStart(leta_id=root.id, agent_id=root.id)
    runner = ControlledAgent()
    value = incoming(ref)
    delivery = asyncio.create_task(deliver_agent_input(client, value))
    try:
        # Server persists the start/update before any worker has processed it.
        async with asyncio.timeout(10):
            while True:
                executions = [entry async for entry in client.list_workflows()]
                if executions:
                    break
                await asyncio.sleep(0.01)
        assert not delivery.done()
        assert await store.list_inbox(root.id, root.id) == []
        async with (
            agent_workers(client, store, runner.run_agent),
            asyncio.timeout(20),
        ):
            assert (await delivery).seq == 1
            await runner.entered.wait()
            assert (await deliver_agent_input(client, value)).seq == 1
            await control_agent(client, root.id, AgentControl(action="stop"))
            assert runner.cleaned.is_set()
    finally:
        if not delivery.done():
            delivery.cancel()
            await asyncio.gather(delivery, return_exceptions=True)


async def test_stop_before_runtime_pickup_cancels_reserved_run(
    store, persistent_temporal
):
    client = persistent_temporal
    root = await active_root(store)
    sql = AgentActivities(store, client)
    ref = AgentStart(leta_id=root.id, agent_id=root.id)
    async with (
        Worker(
            client,
            task_queue=ORCHESTRATION_QUEUE,
            workflows=[AgentWorkflow],
            activities=[
                PublicationActivities(None).publish_resource_event,
                sql.bootstrap_agent,
                sql.persist_inbox,
                sql.save_run_control,
            ],
        ),
        asyncio.timeout(15),
    ):
        handle = await start_agent(client, ref)
        await deliver_agent_input(client, incoming(ref))
        state = await wait_for_state(handle, lambda s: s.run_id is not None)
        # No runtime worker exists. The run still has a durable identity for yield.
        async with asyncio.timeout(5):
            while not any(
                event.HasField("activity_task_scheduled_event_attributes")
                for event in (await handle.fetch_history()).events
            ):
                await asyncio.sleep(0.01)
        await control_agent(
            client, root.id, AgentControl(action="yield", run_id=state.run_id)
        )
        async with store.database.connection() as connection:
            row = await (
                await connection.execute(
                    "SELECT yield_requested FROM runs WHERE id=%s", (state.run_id,)
                )
            ).fetchone()
            assert row == (True,)
        await control_agent(client, root.id, AgentControl(action="stop"))
        await handle.result()
        runs = await store.list_runs(root.id, root.id)
        assert len(runs) == 1 and runs[0]["status"] == "cancelled"
