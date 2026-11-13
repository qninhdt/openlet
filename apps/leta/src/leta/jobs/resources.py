from datetime import timedelta
from uuid import UUID

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from openlet_sdk.config import JSON
    from pydantic import BaseModel

    from ..agents import RootCreation
    from ..boxes import BoxCreation


class ResourceOperation(BaseModel):
    id: UUID
    action: str
    request_id: UUID
    bridge_queue: str
    root: RootCreation | None = None
    box: BoxCreation | None = None


@workflow.defn
class LetaLifecycle:
    def __init__(self) -> None:
        self.result: dict[str, JSON] | None = None

    @workflow.update
    async def open(self) -> dict[str, JSON]:
        await workflow.wait_condition(lambda: self.result is not None)
        assert self.result is not None
        return self.result

    @workflow.run
    async def run(self, operation: ResourceOperation) -> dict[str, JSON]:
        if operation.action == "create":
            assert operation.root is not None
            self.result = await workflow.execute_local_activity(
                "prepare_leta",
                operation.root,
                start_to_close_timeout=timedelta(seconds=15),
                result_type=dict[str, JSON],
            )
            await workflow.execute_activity(
                "provision_leta",
                operation.root,
                start_to_close_timeout=timedelta(minutes=2),
            )
        elif operation.action == "delete":
            await workflow.execute_local_activity(
                "close_leta", operation.id, start_to_close_timeout=timedelta(seconds=15)
            )
            self.result = {"id": str(operation.id), "state": "deleting"}
            await workflow.execute_activity(
                "cleanup_leta",
                operation.id,
                task_queue=operation.bridge_queue,
                start_to_close_timeout=timedelta(hours=1),
                heartbeat_timeout=timedelta(seconds=30),
            )
        else:
            await workflow.execute_local_activity(
                "set_leta_paused",
                operation,
                start_to_close_timeout=timedelta(seconds=15),
            )
            self.result = {
                "id": str(operation.id),
                "paused": operation.action == "pause",
            }
            await workflow.execute_activity(
                "refresh_leta_agents",
                operation.id,
                task_queue=operation.bridge_queue,
                start_to_close_timeout=timedelta(minutes=2),
            )
        await workflow.wait_condition(workflow.all_handlers_finished)
        assert self.result is not None
        return self.result


@workflow.defn
class BoxLifecycle:
    def __init__(self) -> None:
        self.result: dict[str, JSON] | None = None

    @workflow.update
    async def open(self) -> dict[str, JSON]:
        await workflow.wait_condition(lambda: self.result is not None)
        assert self.result is not None
        return self.result

    @workflow.run
    async def run(self, operation: ResourceOperation) -> dict[str, JSON]:
        if operation.action == "create":
            assert operation.box is not None
            home = await workflow.execute_activity(
                "provision_box",
                operation.box,
                start_to_close_timeout=timedelta(minutes=2),
                result_type=UUID,
            )
            self.result = await workflow.execute_local_activity(
                "prepare_box",
                args=[operation.box, home],
                start_to_close_timeout=timedelta(seconds=15),
                result_type=dict[str, JSON],
            )
        else:
            await workflow.execute_local_activity(
                "close_box", operation.id, start_to_close_timeout=timedelta(seconds=15)
            )
            await workflow.execute_activity(
                "cleanup_box",
                operation.id,
                task_queue=operation.bridge_queue,
                start_to_close_timeout=timedelta(hours=1),
                heartbeat_timeout=timedelta(seconds=30),
            )
            self.result = {"id": str(operation.id), "state": "archived"}
        await workflow.wait_condition(workflow.all_handlers_finished)
        assert self.result is not None
        return self.result
