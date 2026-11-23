from datetime import timedelta
from uuid import UUID

from temporalio import workflow
from temporalio.exceptions import ApplicationError

from .retry import RETRY

with workflow.unsafe.imports_passed_through():
    from openlet_sdk.config import JSON
    from pydantic import BaseModel

    from ..agents import LetaCreation, LetaRequest
    from ..boxes import BoxCreation


class ResourceOperation(BaseModel):
    id: UUID
    action: str
    request_id: UUID
    bridge_queue: str
    leta: LetaRequest | None = None
    box: BoxCreation | None = None


@workflow.defn
class LetaLifecycle:
    @workflow.init
    def __init__(self, operation: ResourceOperation) -> None:
        self.result: dict[str, JSON] | None = None
        self.command = operation

    @workflow.update
    async def open(self, command: ResourceOperation) -> dict[str, JSON]:
        if command != self.command:
            raise ApplicationError(
                "resource request ID was already used with different input"
            )
        await workflow.wait_condition(lambda: self.result is not None)
        assert self.result is not None
        return self.result

    @workflow.run
    async def run(self, operation: ResourceOperation) -> dict[str, JSON]:
        if operation.action == "create":
            assert operation.leta is not None
            creation = LetaCreation(
                workspace_id=operation.leta.workspace_id,
                owner_id=operation.leta.owner_id,
                request=operation.leta.request,
                leta_id=workflow.uuid4(),
                storage_id=workflow.uuid4(),
                root_node_id=workflow.uuid4(),
            )
            self.result = await workflow.execute_local_activity(
                "prepare_leta",
                creation,
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(seconds=15),
                result_type=dict[str, JSON],
            )
            await workflow.execute_activity(
                "provision_leta",
                creation,
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(minutes=2),
            )
        elif operation.action == "delete":
            await workflow.execute_local_activity(
                "close_leta",
                operation.id,
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(seconds=15),
            )
            self.result = {"id": str(operation.id), "state": "deleting"}
            await workflow.execute_activity(
                "cleanup_leta",
                operation.id,
                task_queue=operation.bridge_queue,
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(hours=1),
                heartbeat_timeout=timedelta(seconds=30),
            )
        else:
            await workflow.execute_local_activity(
                "set_leta_paused",
                operation,
                retry_policy=RETRY,
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
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(minutes=2),
            )
        await workflow.wait_condition(workflow.all_handlers_finished)
        assert self.result is not None
        return self.result


@workflow.defn
class BoxLifecycle:
    @workflow.init
    def __init__(self, operation: ResourceOperation) -> None:
        self.result: dict[str, JSON] | None = None
        self.command = operation

    @workflow.update
    async def open(self, command: ResourceOperation) -> dict[str, JSON]:
        if command != self.command:
            raise ApplicationError(
                "resource request ID was already used with different input"
            )
        await workflow.wait_condition(lambda: self.result is not None)
        assert self.result is not None
        return self.result

    @workflow.run
    async def run(self, operation: ResourceOperation) -> dict[str, JSON]:
        if operation.action == "create":
            assert operation.box is not None
            self.result = await workflow.execute_activity(
                "provision_box",
                operation.box,
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(minutes=2),
                result_type=dict[str, JSON],
            )
        else:
            await workflow.execute_local_activity(
                "close_box",
                operation.id,
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(seconds=15),
            )
            await workflow.execute_activity(
                "cleanup_box",
                operation.id,
                task_queue=operation.bridge_queue,
                retry_policy=RETRY,
                start_to_close_timeout=timedelta(hours=1),
                heartbeat_timeout=timedelta(seconds=30),
            )
            self.result = {"id": str(operation.id), "state": "archived"}
        await workflow.wait_condition(workflow.all_handlers_finished)
        assert self.result is not None
        return self.result
