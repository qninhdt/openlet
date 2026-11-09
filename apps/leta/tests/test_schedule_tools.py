import json
from uuid import UUID, uuid7

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from openlet.errors import AppError
from test_messaging import context
from test_runtime import RecordingModel, call, harness
from test_store_integration import active_box, active_root, message

from leta.runtime.schedules import create_schedule, get_definition, list_schedules
from leta.temporal.schedule_activities import ScheduleActivities
from leta.worker import agent_workers

pytestmark = pytest.mark.integration


async def test_real_tool_schema_parsing_update_null_and_checkpoint_recovery(
    store, postgres_dsn, persistent_temporal
):
    model = RecordingModel(
        responses=[
            call(
                "create_schedule",
                title="Report",
                content="Write report",
                spec={"type": "interval", "every_seconds": 432000},
                end_at="2030-01-01T00:00:00Z",
            ),
            AIMessage(content="placeholder"),
            AIMessage(content="Scheduled"),
        ]
    )
    client = persistent_temporal
    runner, run, root, _ = await harness(store, postgres_dsn, model, client=client)
    schedule_id = None

    async def following(messages, number):
        nonlocal schedule_id
        if number == 2:
            saved = json.loads(
                next(
                    m.content for m in reversed(messages) if isinstance(m, ToolMessage)
                )
            )
            schedule_id = saved["id"]
            model.responses[1] = call(
                "update_schedule",
                identity="update",
                schedule_id=schedule_id,
                title="New report",
                end_at=None,
                paused=True,
            )

    model.on_call = following
    await store.receive(message(root))
    schedules = ScheduleActivities(store, client)
    async with agent_workers(client, store, runner.run_agent, schedules=schedules):
        assert (await runner.execute(run)).outcome == "completed"
        saved = await store.get_schedule(root.id, UUID(schedule_id))
        assert (
            saved["title"] == "New report"
            and saved["end_at"] is None
            and saved["paused"]
        )
        assert (
            saved["content"] == "Write report"
            and saved["spec"]["every_seconds"] == 432000
        )
        results = [m for m in model.calls[-1] if isinstance(m, ToolMessage)]
        assert len(results) == 2 and all(m.status == "success" for m in results)
        assert {
            "create_schedule",
            "update_schedule",
            "delete_schedule",
            "get_schedule",
            "list_schedules",
        } <= set(model.tools_seen)


async def test_agent_schedule_targets_and_management_are_scoped(
    store, persistent_temporal
):
    from test_lifecycle_integration import unused_runtime

    root = await active_root(store)
    box = await active_box(store, root)
    parent = await context(store, root, root.id, persistent_temporal)
    child = await context(store, root, box.letis[0].id, persistent_temporal)
    peer = await context(store, root, box.letis[1].id, persistent_temporal)
    schedules = ScheduleActivities(store, persistent_temporal)
    async with agent_workers(
        persistent_temporal, store, unused_runtime, schedules=schedules
    ):
        own = await create_schedule(
            child, uuid7(), "Daily", "Check", {"type": "at", "after_seconds": 3600}
        )
        team = await create_schedule(
            parent,
            uuid7(),
            "Team",
            "Report",
            {"type": "interval", "every_seconds": 86400},
            box.name,
        )
        assert own["box_id"] == str(box.id) and team["target_agent_id"] == str(
            box.letis[0].id
        )
        assert len((await list_schedules(parent, box=box.name))["items"]) == 2
        assert len((await list_schedules(child))["items"]) == 2
        with pytest.raises(AppError, match="only itself"):
            await create_schedule(
                child,
                uuid7(),
                "Peer",
                "No",
                {"type": "at", "after_seconds": 3600},
                str(box.id),
            )
        with pytest.raises(AppError, match="only its schedules"):
            await get_definition(peer, own["id"])
        assert (await get_definition(parent, own["id"]))["id"] == UUID(own["id"])
