from openlet.errors import AppError
from openlet.temporal import application_error
from temporalio import activity
from temporalio.client import Client

from leta.domain import Lifecycle
from leta.store import Store
from leta.temporal.types import (
    AgentInput,
    AgentRef,
    Bootstrap,
    InboxReceipt,
    RunControl,
)


class AgentActivities:
    def __init__(self, store: Store, temporal: Client):
        self.store, self.temporal = store, temporal

    @activity.defn
    async def bootstrap_agent(self, ref: AgentRef) -> Bootstrap:
        try:
            if ref.run_id is not None:
                await self.store.start_run(ref.leta_id, ref.agent_id, ref.run_id)
            row = await self.store.bootstrap_agent(ref.leta_id, ref.agent_id)
            return Bootstrap(
                latest_seq=row["latest_seq"],
                cursor=row["cursor"],
                run_id=row["run_id"],
                paused=row["paused"],
                stopped=any(
                    row[key] in {Lifecycle.DELETING, Lifecycle.ARCHIVED}
                    for key in ("status", "root_status", "box_status")
                ),
            )
        except AppError as error:
            raise application_error(
                error, fallback="BOOTSTRAP_FAILED", message="agent bootstrap failed"
            ) from error

    @activity.defn
    async def persist_inbox(self, value: AgentInput) -> InboxReceipt:
        try:
            row = await self.store.receive(value.message, schedule_id=value.schedule_id)
            return InboxReceipt(
                message_id=row["id"], agent_id=row["recipient_agent_id"], seq=row["seq"]
            )
        except AppError as error:
            raise application_error(
                error, fallback="INBOX_FAILED", message=str(error)
            ) from error

    @activity.defn
    async def save_run_control(self, value: RunControl) -> str:
        try:
            method = (
                self.store.cancel_unfinished_run
                if value.action == "stop"
                else self.store.request_run_yield
            )
            row = await method(value.leta_id, value.agent_id, value.run_id)
            return row["status"]
        except AppError as error:
            raise application_error(
                error, fallback="CONTROL_FAILED", message="run control failed"
            ) from error

    @activity.defn
    async def deliver_agent_input(self, value: AgentInput) -> str:
        from leta.temporal.bridges import deliver_agent_input

        try:
            root = await self.store.bootstrap_agent(
                value.message.leta_id, value.message.recipient_agent_id
            )
            if any(
                root[key] in {Lifecycle.DELETING, Lifecycle.ARCHIVED}
                for key in ("status", "root_status", "box_status")
            ):
                return "skipped"
            await deliver_agent_input(self.temporal, value)
            return "delivered"
        except AppError as error:
            if error.reason in {"NOT_FOUND", "RESOURCE_INACTIVE"}:
                return "skipped"
            raise application_error(
                error, fallback="INBOX_FAILED", message=str(error)
            ) from error
