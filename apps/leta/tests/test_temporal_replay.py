from pathlib import Path

import pytest
from temporalio.client import WorkflowHistory
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Replayer

from leta.temporal.agent import AgentWorkflow
from leta.temporal.human import HumanRequestWorkflow

pytestmark = pytest.mark.replay


@pytest.mark.parametrize(
    "name", ["busy-receive", "paused-receive", "paused-rotation", "active-rotation"]
)
async def test_agent_history_replays_without_running_effects(name):
    raw = (Path(__file__).parent / "fixtures" / "temporal" / f"{name}.json").read_text()
    history = WorkflowHistory.from_json(name, raw)
    result = await Replayer(
        workflows=[AgentWorkflow], data_converter=pydantic_data_converter
    ).replay_workflow(history)
    assert result.replay_failure is None


@pytest.mark.parametrize(
    "name", ["human-answer", "human-cancel", "human-expiry", "human-approval"]
)
async def test_human_request_history_replays_without_running_effects(name):
    raw = (Path(__file__).parent / "fixtures" / "temporal" / f"{name}.json").read_text()
    result = await Replayer(
        workflows=[HumanRequestWorkflow], data_converter=pydantic_data_converter
    ).replay_workflow(WorkflowHistory.from_json(name, raw))
    assert result.replay_failure is None


@pytest.mark.parametrize(
    "name,workflow_type",
    [
        ("schedule-native-delivery", "delivery"),
        ("schedule-direct-delivery", "delivery"),
        ("schedule-changes", "changes"),
    ],
)
async def test_schedule_histories_replay_without_running_effects(name, workflow_type):
    from leta.temporal.schedules import (
        ScheduleChangesWorkflow,
        ScheduleDeliveryWorkflow,
    )

    raw = (Path(__file__).parent / "fixtures" / "temporal" / f"{name}.json").read_text()
    result = await Replayer(
        workflows=[
            ScheduleDeliveryWorkflow
            if workflow_type == "delivery"
            else ScheduleChangesWorkflow
        ],
        data_converter=pydantic_data_converter,
    ).replay_workflow(WorkflowHistory.from_json(name, raw))
    assert result.replay_failure is None


@pytest.mark.parametrize("name", ["leta-lifecycle", "box-lifecycle"])
async def test_lifecycle_histories_replay_without_running_effects(name):
    from leta.temporal.box import BoxLifecycleWorkflow
    from leta.temporal.lifecycle import LetaLifecycleWorkflow

    raw = (Path(__file__).parent / "fixtures" / "temporal" / f"{name}.json").read_text()
    result = await Replayer(
        workflows=[
            LetaLifecycleWorkflow if name == "leta-lifecycle" else BoxLifecycleWorkflow
        ],
        data_converter=pydantic_data_converter,
    ).replay_workflow(WorkflowHistory.from_json(name, raw))
    assert result.replay_failure is None
