import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid5, uuid7

import pytest
from temporalio.client import ScheduleOverlapPolicy
from test_agent_workflow import retain_history
from test_lifecycle_integration import unused_runtime
from test_store_integration import active_root

from leta.domain import NewSchedule, SchedulePatch
from leta.temporal.bridges import change_schedule
from leta.temporal.human_activities import HumanActivities
from leta.temporal.schedule_activities import ScheduleActivities
from leta.temporal.schedule_types import ScheduleChange
from leta.worker import agent_workers

pytestmark = pytest.mark.integration


def change(root, schedule_id=None, *, action="create", spec=None, **patch):
    schedule_id = schedule_id or uuid7()
    return ScheduleChange(
        leta_id=root.id,
        schedule_id=schedule_id,
        requester_agent_id=root.id,
        requested_at=datetime.now(UTC),
        action=action,
        creation=NewSchedule(
            id=schedule_id,
            leta_id=root.id,
            creator_agent_id=root.id,
            target_agent_id=root.id,
            title="Reminder",
            content="Do it",
            spec=spec or {"type": "at", "after_seconds": 5},
        )
        if action == "create"
        else None,
        patch=SchedulePatch(**({"spec": spec} if spec is not None else {}) | patch)
        if action == "update"
        else None,
    )


async def saved_occurrence(store, root, schedule_id, when):
    message_id = uuid5(schedule_id, when.astimezone(UTC).isoformat())
    from openlet.errors import AppError

    async with asyncio.timeout(20):
        while True:
            try:
                return await store.get_message(root.id, message_id)
            except AppError as error:
                if error.reason != "NOT_FOUND":
                    raise
            await asyncio.sleep(0.05)


async def test_native_at_delivery_edit_consumption_and_rearm(
    store, persistent_temporal
):
    root = await active_root(store)
    await store.set_paused(root.id, True)
    client = persistent_temporal
    schedules = ScheduleActivities(store, client)
    human = HumanActivities(store, SimpleNamespace(), client)
    async with (
        agent_workers(client, store, unused_runtime, human=human, schedules=schedules),
        asyncio.timeout(45),
    ):
        command = change(root)
        created = await change_schedule(client, command, command_id="create")
        when = datetime.fromisoformat(created.spec["at"])
        message = await saved_occurrence(store, root, created.id, when)
        assert message["content"] == "Do it"
        assert message["data"]["scheduled_at"] == when.isoformat()
        handle = client.get_schedule_handle(f"schedule/{created.id}")
        description = await handle.describe()
        native = client.get_workflow_handle(
            description.info.recent_actions[0].action.workflow_id
        )
        assert await native.result() == "delivered"
        await retain_history(native, "schedule-native-delivery")
        assert description.schedule.state.remaining_actions == 0
        assert description.schedule.policy.overlap == ScheduleOverlapPolicy.BUFFER_ONE
        edited = await change_schedule(
            client,
            change(root, created.id, action="update", title="Edited"),
            command_id="title",
        )
        assert edited.title == "Edited"
        assert (await handle.describe()).schedule.state.remaining_actions == 0
        assert (await store.bootstrap_agent(root.id, root.id))["latest_seq"] == 1
        assert (
            await change_schedule(client, command, command_id="create")
        ).spec == created.spec
        assert (await store.get_schedule(root.id, created.id))["title"] == "Edited"
        for paused in [True, False]:
            await change_schedule(
                client,
                change(root, created.id, action="update", paused=paused),
                command_id=f"pause-{paused}",
            )
        assert (await store.bootstrap_agent(root.id, root.id))["latest_seq"] == 1
        new_at = datetime.now(UTC) - timedelta(seconds=60)
        changed = await change_schedule(
            client,
            change(
                root,
                created.id,
                action="update",
                spec={"type": "at", "at": new_at.isoformat()},
            ),
            command_id="rearm",
        )
        new_at = datetime.fromisoformat(changed.spec["at"])
        assert (await saved_occurrence(store, root, created.id, new_at))[
            "content"
        ] == "Do it"
        assert (await store.bootstrap_agent(root.id, root.id))["latest_seq"] == 2
        deleted = await change_schedule(
            client, change(root, created.id, action="delete"), command_id="delete"
        )
        coordinator = client.get_workflow_handle(f"schedule-changes/{created.id}")
        await coordinator.result()
        await retain_history(coordinator, "schedule-changes")
        assert deleted.deleted_at is not None
        assert await store.list_schedules(root.id) == []
        assert (
            await change_schedule(
                client,
                change(root, created.id, action="delete"),
                command_id="delete-again",
            )
        ).deleted_at == deleted.deleted_at


async def test_native_forecast_anchors_monthly_dst_and_exact_cap(
    store, persistent_temporal
):
    from openlet.errors import AppError

    from leta.schedules import calendar_occurrences

    root = await active_root(store)
    client = persistent_temporal
    schedules = ScheduleActivities(store, client)
    async with (
        agent_workers(client, store, unused_runtime, schedules=schedules),
        asyncio.timeout(40),
    ):
        specs = [
            {
                "type": "interval",
                "every_seconds": 3600,
                "anchor_at": "2027-01-01T00:03:02Z",
            },
            {
                "type": "interval",
                "every_seconds": 432000,
                "anchor_at": "2027-01-01T00:03:02Z",
            },
            {
                "type": "calendar",
                "timezone": "UTC",
                "fields": {"day_of_month": [31], "hour": [9]},
            },
            {
                "type": "calendar",
                "timezone": "America/New_York",
                "fields": {"hour": [2], "minute": [30]},
            },
            {
                "type": "interval",
                "every_seconds": 1,
                "anchor_at": "2030-01-01T00:00:00Z",
            },
        ]
        saved = []
        for spec in specs:
            result = await change_schedule(
                client, change(root, spec=spec), command_id=str(uuid7())
            )
            saved.append(await store.get_schedule(root.id, result.id))

        def utc(value):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))

        async def times(row, start, end):
            return [
                v["scheduled_at"]
                for v in await calendar_occurrences(
                    client, [row], start=utc(start), end=utc(end)
                )
            ]

        assert await times(
            saved[0], "2027-01-01T00:03:02Z", "2027-01-01T02:03:02Z"
        ) == ["2027-01-01T01:03:02+00:00", "2027-01-01T02:03:02+00:00"]
        assert await times(
            saved[1], "2026-12-31T00:00:00Z", "2027-01-12T00:00:00Z"
        ) == [
            "2027-01-01T00:03:02+00:00",
            "2027-01-06T00:03:02+00:00",
            "2027-01-11T00:03:02+00:00",
        ]
        assert await times(
            saved[2], "2027-01-01T00:00:00Z", "2027-04-01T00:00:00Z"
        ) == ["2027-01-31T09:00:00+00:00", "2027-03-31T09:00:00+00:00"]
        assert await times(
            saved[3], "2027-03-13T00:00:00Z", "2027-03-16T00:00:00Z"
        ) == ["2027-03-13T07:30:00+00:00", "2027-03-15T06:30:00+00:00"]
        exact = await times(saved[4], "2030-01-01T00:00:00Z", "2030-01-01T00:16:40Z")
        assert (
            len(exact) == 1000
            and exact[0] == "2030-01-01T00:00:01+00:00"
            and exact[-1] == "2030-01-01T00:16:40+00:00"
        )
        with pytest.raises(AppError, match="narrow calendar"):
            await times(saved[4], "2030-01-01T00:00:00Z", "2030-01-01T00:16:41Z")
        with pytest.raises(AppError, match="narrow calendar"):
            await calendar_occurrences(
                client,
                [saved[0]] * 33,
                start=utc("2027-01-01T00:00:00Z"),
                end=utc("2027-01-02T00:00:00Z"),
            )
        for row in saved:
            await change_schedule(
                client,
                change(root, row["id"], action="delete"),
                command_id=str(uuid7()),
            )


async def test_local_and_native_commit_lost_ack_keep_original_relative_time(
    store, persistent_temporal
):
    from temporalio import activity

    from leta.schedules import ceil_second
    from leta.temporal.schedule_types import ScheduleDefinition

    root = await active_root(store)
    await store.set_paused(root.id, True)
    client = persistent_temporal
    attempts = {"sql": 0, "native": 0}

    class LoseCompletion(ScheduleActivities):
        @activity.defn
        async def save_schedule_change(
            self, value: ScheduleChange
        ) -> ScheduleDefinition:
            saved = await super().save_schedule_change(value)
            attempts["sql"] += 1
            if attempts["sql"] == 1:
                raise RuntimeError("lost after SQL commit before Local marker")
            return saved

        @activity.defn
        async def apply_temporal_schedule(self, value: ScheduleDefinition) -> None:
            await super().apply_temporal_schedule(value)
            attempts["native"] += 1
            if attempts["native"] == 1:
                raise RuntimeError("lost after native apply")

    schedules = LoseCompletion(store, client)
    human = HumanActivities(store, SimpleNamespace(), client)
    async with (
        agent_workers(client, store, unused_runtime, human=human, schedules=schedules),
        asyncio.timeout(25),
    ):
        command = change(root, spec={"type": "at", "after_seconds": 0})
        result = await change_schedule(client, command, command_id="relative")
        when = datetime.fromisoformat(result.spec["at"])
        assert when == ceil_second(command.requested_at)
        saved = await saved_occurrence(store, root, result.id, when)
        assert saved["data"]["scheduled_at"] == when.isoformat()
        assert attempts == {"sql": 2, "native": 2}
        assert (await store.bootstrap_agent(root.id, root.id))["latest_seq"] == 1
        direct = client.get_workflow_handle(
            f"schedule-delivery/{result.id}-" + when.isoformat().replace("+00:00", "Z")
        )
        await direct.result()
        await retain_history(direct, "schedule-direct-delivery")
        await change_schedule(
            client, change(root, result.id, action="delete"), command_id="delete"
        )


async def test_worker_stopped_across_due_time_recovers_native_delivery(
    store, persistent_temporal
):
    from openlet.errors import AppError

    root = await active_root(store)
    await store.set_paused(root.id, True)
    client = persistent_temporal
    schedules = ScheduleActivities(store, client)
    async with asyncio.timeout(30):
        async with agent_workers(client, store, unused_runtime, schedules=schedules):
            created = await change_schedule(
                client,
                change(root, spec={"type": "at", "after_seconds": 3}),
                command_id="create",
            )
        handle = client.get_schedule_handle(f"schedule/{created.id}")
        while not (await handle.describe()).info.recent_actions:
            await asyncio.sleep(0.05)
        when = datetime.fromisoformat(created.spec["at"])
        with pytest.raises(AppError):
            await store.get_message(root.id, uuid5(created.id, when.isoformat()))
        async with agent_workers(client, store, unused_runtime, schedules=schedules):
            assert (await saved_occurrence(store, root, created.id, when))[
                "content"
            ] == "Do it"
            assert (await store.bootstrap_agent(root.id, root.id))["latest_seq"] == 1
            await change_schedule(
                client, change(root, created.id, action="delete"), command_id="delete"
            )


async def test_delete_rechecks_source_and_pause_preserves_admitted_snapshot(
    store, persistent_temporal
):
    from temporalio import activity

    from leta.temporal.types import AgentInput

    root = await active_root(store)
    await store.set_paused(root.id, True)
    client = persistent_temporal
    entered, release = asyncio.Queue(), asyncio.Event()

    class HoldDelivery(HumanActivities):
        @activity.defn
        async def deliver_agent_input(self, value: AgentInput) -> str:
            await entered.put(value)
            await release.wait()
            return await super().deliver_agent_input(value)

    schedules = ScheduleActivities(store, client)
    human = HoldDelivery(store, SimpleNamespace(), client)
    async with (
        agent_workers(client, store, unused_runtime, human=human, schedules=schedules),
        asyncio.timeout(30),
    ):
        try:
            for action in ["pause", "delete"]:
                release.clear()
                created = await change_schedule(
                    client,
                    change(root, spec={"type": "at", "after_seconds": 0}),
                    command_id=str(uuid7()),
                )
                pending = await entered.get()
                command = (
                    change(root, created.id, action="delete")
                    if action == "delete"
                    else change(root, created.id, action="update", paused=True)
                )
                await change_schedule(client, command, command_id=str(uuid7()))
                release.set()
                delivery = client.get_workflow_handle(
                    f"schedule-delivery/{created.id}-"
                    + pending.message.data["scheduled_at"].replace("+00:00", "Z")
                )
                assert await delivery.result() == (
                    "skipped" if action == "delete" else "delivered"
                )
            assert (await store.bootstrap_agent(root.id, root.id))["latest_seq"] == 1
        finally:
            release.set()


async def test_native_buffer_one_bounds_overlapping_delivery_workflows(
    store, persistent_temporal
):
    from temporalio import activity

    from leta.temporal.types import AgentInput

    root = await active_root(store)
    await store.set_paused(root.id, True)
    client = persistent_temporal
    entered, release = asyncio.Event(), asyncio.Event()

    class HoldFirst(HumanActivities):
        @activity.defn
        async def deliver_agent_input(self, value: AgentInput) -> str:
            entered.set()
            await release.wait()
            return await super().deliver_agent_input(value)

    schedules = ScheduleActivities(store, client)
    human = HoldFirst(store, SimpleNamespace(), client)
    async with (
        agent_workers(client, store, unused_runtime, human=human, schedules=schedules),
        asyncio.timeout(25),
    ):
        try:
            created = await change_schedule(
                client,
                change(root, spec={"type": "interval", "every_seconds": 1}),
                command_id="create",
            )
            await entered.wait()
            handle = client.get_schedule_handle(f"schedule/{created.id}")
            while True:
                described = await handle.describe()
                info = described.raw_description.info
                if info.buffer_size == 1 and (
                    info.buffer_dropped >= 1 or info.overlap_skipped >= 1
                ):
                    break
                await asyncio.sleep(0.05)
            assert (
                described.info.num_actions == 1
                and len(described.info.running_actions) == 1
            )
            # Stop new ticks after the observed overlap, keeping the buffer runnable.
            first_at = described.info.recent_actions[0].scheduled_at
            await change_schedule(
                client,
                change(
                    root,
                    created.id,
                    action="update",
                    end_at=first_at + timedelta(seconds=2),
                ),
                command_id="cutoff",
            )
            release.set()
            while True:
                finished = await handle.describe()
                if finished.info.num_actions == 2 and not finished.info.running_actions:
                    break
                await asyncio.sleep(0.05)
            assert (await store.bootstrap_agent(root.id, root.id))["latest_seq"] == 2
            assert finished.raw_description.info.buffer_size == 0
            await change_schedule(
                client, change(root, created.id, action="delete"), command_id="delete"
            )
        finally:
            release.set()


async def test_box_delete_settles_real_schedule_and_human_coordinators(
    store, persistent_temporal
):
    from temporalio.service import RPCError, RPCStatusCode
    from test_domain import box_input
    from test_human_requests_integration import ask
    from test_lifecycle_integration import RemoteServices

    from leta.temporal.bridges import change_box, open_human_request
    from leta.temporal.human_types import OpenHumanRequest
    from leta.temporal.lifecycle_activities import LifecycleActivities
    from leta.temporal.lifecycle_types import BoxChange

    root = await active_root(store)
    await store.set_paused(root.id, True)
    client = persistent_temporal
    services = RemoteServices(root)
    lifecycle = LifecycleActivities(
        store, services.scopes, services.native, services.graph, client
    )
    schedules = ScheduleActivities(store, client)
    human = HumanActivities(store, services.scopes, client)
    box = box_input(root.id)
    async with (
        agent_workers(
            client,
            store,
            unused_runtime,
            lifecycle=lifecycle,
            human=human,
            schedules=schedules,
        ),
        asyncio.timeout(30),
    ):
        await change_box(
            client,
            BoxChange(leta_id=root.id, box_id=box.id, action="create", creation=box),
        )
        row = await store.get_box(root.id, box.id)
        schedule = change(root, spec={"type": "at", "after_seconds": 3600})
        schedule = schedule.model_copy(
            update={
                "creation": schedule.creation.model_copy(
                    update={
                        "target_agent_id": row["representative_agent_id"],
                        "box_id": box.id,
                    }
                )
            }
        )
        saved = await change_schedule(client, schedule, command_id="create")
        request = ask(root).model_copy(
            update={"requester_agent_id": row["representative_agent_id"]}
        )
        await open_human_request(
            client,
            store,
            OpenHumanRequest(leta_id=root.id, request_id=request.id, creation=request),
        )
        assert (
            await change_box(
                client, BoxChange(leta_id=root.id, box_id=box.id, action="deleting")
            )
        ).status == "archived"
        assert (await store.get_schedule(root.id, saved.id))["deleted_at"] is not None
        assert (await store.get_request(root.id, request.id))["status"] == "cancelled"
        assert (await store.get_box(root.id, box.id))["status"] == "archived"
        assert services.trashed == 1
        with pytest.raises(RPCError) as failure:
            await client.get_schedule_handle(f"schedule/{saved.id}").describe()
        assert failure.value.status == RPCStatusCode.NOT_FOUND


async def test_one_shot_due_during_native_creation_is_delivered(
    store, persistent_temporal, monkeypatch
):
    root = await active_root(store)
    await store.set_paused(root.id, True)
    client = persistent_temporal
    original = client.create_schedule

    async def cross_due(identity, schedule, **kwargs):
        at = schedule.spec.calendars[0]
        # Cross the nominal due time while the real native create RPC is in flight.
        due = datetime(
            at.year[0].start,
            at.month[0].start,
            at.day_of_month[0].start,
            at.hour[0].start,
            at.minute[0].start,
            at.second[0].start,
            tzinfo=UTC,
        )
        await asyncio.sleep(max(0, (due - datetime.now(UTC)).total_seconds()) + 0.05)
        return await original(identity, schedule, **kwargs)

    monkeypatch.setattr(client, "create_schedule", cross_due)
    schedules = ScheduleActivities(store, client)
    async with agent_workers(client, store, unused_runtime, schedules=schedules):
        created = await change_schedule(
            client,
            change(root, spec={"type": "at", "after_seconds": 1}),
            command_id="cross-due",
        )
        when = datetime.fromisoformat(created.spec["at"])
        await saved_occurrence(store, root, created.id, when)
        assert (
            await client.get_schedule_handle(f"schedule/{created.id}").describe()
        ).schedule.state.remaining_actions == 0
        await change_schedule(
            client, change(root, created.id, action="delete"), command_id="delete"
        )
