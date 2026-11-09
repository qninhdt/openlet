import asyncio
from contextlib import suppress
from datetime import timedelta
from uuid import UUID

from openlet.errors import AppError
from temporalio.client import (
    Client,
    WithStartWorkflowOperation,
    WorkflowUpdateFailedError,
    WorkflowUpdateRPCTimeoutOrCancelledError,
)
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from leta.temporal.agent import AgentWorkflow
from leta.temporal.lifecycle_types import BoxChange, LetaChange
from leta.temporal.types import (
    ORCHESTRATION_QUEUE,
    AgentControl,
    AgentInput,
    AgentStart,
    AgentState,
    InboxReceipt,
)


async def start_agent(client: Client, start: AgentStart):
    return await client.start_workflow(
        AgentWorkflow.run,
        start,
        id=f"agent/{start.agent_id}",
        task_queue=ORCHESTRATION_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )


async def deliver_agent_input(client: Client, value: AgentInput) -> InboxReceipt:
    message = value.message
    operation = WithStartWorkflowOperation(
        AgentWorkflow.run,
        AgentStart(leta_id=message.leta_id, agent_id=message.recipient_agent_id),
        id=f"agent/{message.recipient_agent_id}",
        task_queue=ORCHESTRATION_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    try:
        return await client.execute_update_with_start_workflow(
            AgentWorkflow.receive,
            value,
            start_workflow_operation=operation,
            id=str(message.id),
            rpc_timeout=timedelta(seconds=30),
        )
    except WorkflowUpdateFailedError as error:
        failure = error.cause
        if isinstance(failure, ApplicationError) and failure.non_retryable:
            reason = failure.type or "INBOX_FAILED"
            raise AppError(
                failure.message,
                reason=reason,
                kind={
                    "FORBIDDEN": "forbidden",
                    "VALIDATION": "invalid",
                    "NOT_FOUND": "missing",
                }.get(reason, "conflict"),
                retryable=False,
            ) from error
        raise
    except WorkflowUpdateRPCTimeoutOrCancelledError, RPCError, asyncio.CancelledError:
        # The SDK fails its separate start future before raising the RPC error.
        with suppress(Exception, asyncio.CancelledError):
            await operation.workflow_handle()
        raise


async def control_agent(
    client: Client, agent_id: UUID, value: AgentControl
) -> AgentState:
    return await client.get_workflow_handle_for(
        AgentWorkflow.run, f"agent/{agent_id}"
    ).execute_update(AgentWorkflow.control, value, rpc_timeout=timedelta(seconds=30))


async def change_leta(
    client: Client, value: LetaChange, *, command_id: str | None = None
):
    from leta.temporal.lifecycle import LetaLifecycleWorkflow
    from leta.temporal.lifecycle_types import LifecycleStart

    operation = WithStartWorkflowOperation(
        LetaLifecycleWorkflow.run,
        LifecycleStart(leta_id=value.leta_id),
        id=f"leta-lifecycle/{value.leta_id}",
        task_queue=ORCHESTRATION_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    return await lifecycle_update(
        client,
        LetaLifecycleWorkflow.change,
        value,
        start_workflow_operation=operation,
        **({"id": command_id} if command_id is not None else {}),
    )


async def change_box(
    client: Client, value: BoxChange, *, command_id: str | None = None
):
    from leta.temporal.box import BoxLifecycleWorkflow
    from leta.temporal.lifecycle_types import LifecycleStart

    operation = WithStartWorkflowOperation(
        BoxLifecycleWorkflow.run,
        LifecycleStart(leta_id=value.leta_id, box_id=value.box_id),
        id=f"box-lifecycle/{value.box_id}",
        task_queue=ORCHESTRATION_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    return await lifecycle_update(
        client,
        BoxLifecycleWorkflow.change,
        value,
        start_workflow_operation=operation,
        **({"id": command_id} if command_id is not None else {}),
    )


async def lifecycle_update(client, method, value, **kwargs):
    try:
        return await client.execute_update_with_start_workflow(method, value, **kwargs)
    except WorkflowUpdateFailedError as error:
        _raise_update_failure(error, "LIFECYCLE_FAILED", not_found_kind="missing")
        raise
    except (
        WorkflowUpdateRPCTimeoutOrCancelledError,
        RPCError,
        WorkflowAlreadyStartedError,
        asyncio.CancelledError,
    ):
        with suppress(Exception, asyncio.CancelledError):
            await kwargs["start_workflow_operation"].workflow_handle()
        raise


def _raise_update_failure(error, fallback, *, not_found_kind):
    failure = error.cause
    while failure is not None:
        if isinstance(failure, ApplicationError) and failure.non_retryable:
            raise AppError(
                failure.message,
                reason=failure.type or fallback,
                kind={
                    "FORBIDDEN": "forbidden",
                    "VALIDATION": "invalid",
                    "NOT_FOUND": not_found_kind,
                }.get(failure.type, "conflict"),
                retryable=False,
            ) from error
        failure = getattr(failure, "cause", None)


async def open_human_request(client, store, value):
    from leta.temporal.human import HumanRequestWorkflow
    from leta.temporal.human_types import HumanRequestRef, HumanRequestState

    operation = WithStartWorkflowOperation(
        HumanRequestWorkflow.run,
        HumanRequestRef(leta_id=value.leta_id, request_id=value.request_id),
        id=f"human-request/{value.request_id}",
        task_queue=ORCHESTRATION_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    try:
        return await lifecycle_update(
            client,
            HumanRequestWorkflow.open,
            value,
            start_workflow_operation=operation,
        )
    except (WorkflowAlreadyStartedError, RPCError) as error:
        await completed_human_request(client, operation, value.request_id, error)
        # A completed finite request is never reopened; still compare retry content.
        row = (
            await store.create_request(
                value.creation, timeout_seconds=value.timeout_seconds
            )
            if value.creation is not None
            else await store.get_request(value.leta_id, value.request_id)
        )
        return HumanRequestState.from_row(row)


async def resolve_human_request(client, store, value):
    from temporalio.client import WorkflowExecutionStatus

    from leta.temporal.human import HumanRequestWorkflow
    from leta.temporal.human_types import HumanRequestState

    handle = client.get_workflow_handle_for(
        HumanRequestWorkflow.run, f"human-request/{value.request_id}"
    )
    try:
        return await handle.execute_update(HumanRequestWorkflow.resolve, value)
    except WorkflowUpdateFailedError as error:
        _raise_update_failure(error, "HITL_FAILED", not_found_kind="conflict")
        raise
    except RPCError as error:
        if (
            error.status != RPCStatusCode.NOT_FOUND
            or (await handle.describe()).status != WorkflowExecutionStatus.COMPLETED
        ):
            raise
        return HumanRequestState.from_row(await store.resolve_request(value))


async def settle_hitl(client, value):
    from leta.temporal.human import HumanRequestWorkflow
    from leta.temporal.human_types import HumanRequestRef

    operation = WithStartWorkflowOperation(
        HumanRequestWorkflow.run,
        HumanRequestRef(leta_id=value.leta_id, request_id=value.request_id),
        id=f"human-request/{value.request_id}",
        task_queue=ORCHESTRATION_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    try:
        return await lifecycle_update(
            client,
            HumanRequestWorkflow.settle,
            value,
            start_workflow_operation=operation,
        )
    except (WorkflowAlreadyStartedError, RPCError) as error:
        result = await completed_human_request(
            client, operation, value.request_id, error
        )
        if result.leta_id != value.leta_id:
            raise AppError(
                "request targets another Leta",
                reason="FORBIDDEN",
                kind="forbidden",
                retryable=False,
            )
        return result


async def completed_human_request(client, operation, request_id, error):
    from leta.temporal.human import HumanRequestWorkflow

    if isinstance(error, RPCError) and error.status != RPCStatusCode.ALREADY_EXISTS:
        raise error
    try:
        await operation.workflow_handle()
    except WorkflowAlreadyStartedError, RPCError:
        pass  # Observe the SDK start future as well as the multi-operation failure.
    return await client.get_workflow_handle_for(
        HumanRequestWorkflow.run, f"human-request/{request_id}"
    ).result()


async def change_schedule(client, value, *, command_id):
    from leta.temporal.schedule_types import ScheduleStart
    from leta.temporal.schedules import ScheduleChangesWorkflow

    workflow_id = f"schedule-changes/{value.schedule_id}"
    operation = WithStartWorkflowOperation(
        ScheduleChangesWorkflow.run,
        ScheduleStart(leta_id=value.leta_id, schedule_id=value.schedule_id),
        id=workflow_id,
        task_queue=ORCHESTRATION_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
    )
    try:
        return await lifecycle_update(
            client,
            ScheduleChangesWorkflow.change,
            value,
            id=command_id,
            start_workflow_operation=operation,
        )
    except (WorkflowAlreadyStartedError, RPCError) as error:
        if isinstance(error, RPCError) and error.status != RPCStatusCode.ALREADY_EXISTS:
            raise
        try:
            await operation.workflow_handle()
        except WorkflowAlreadyStartedError, RPCError:
            pass
        result = await client.get_workflow_handle_for(
            ScheduleChangesWorkflow.run, workflow_id
        ).result()
        if result.leta_id != value.leta_id:
            raise AppError(
                "schedule belongs to another Leta",
                reason="FORBIDDEN",
                kind="forbidden",
                retryable=False,
            )
        if value.action != "delete":
            raise AppError(
                "schedule is deleted",
                reason="RESOURCE_INACTIVE",
                kind="conflict",
                retryable=False,
            )
        return result
