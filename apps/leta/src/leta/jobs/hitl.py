import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    import json

    from openlet_sdk.config import JSON
    from pydantic import BaseModel

    from ..agents import stable
    from ..auth import Actor
    from ..hitl import Decision, OpenRequest
    from ..messages import Message, conversation


class HitlInput(BaseModel):
    request: OpenRequest
    bridge_queue: str


@workflow.defn
class HitlRequest:
    def __init__(self) -> None:
        self.opened: dict[str, JSON] | None = None
        self.decision: dict[str, JSON] | None = None
        self.lock = asyncio.Lock()

    @workflow.update
    async def open(self) -> dict[str, JSON]:
        await workflow.wait_condition(lambda: self.opened is not None)
        assert self.opened is not None
        return self.opened

    @workflow.update
    async def decide(self, decision: Decision) -> dict[str, JSON]:
        return await self.resolve(decision)

    async def resolve(self, decision: Decision) -> dict[str, JSON]:
        await workflow.wait_condition(lambda: self.opened is not None)
        async with self.lock:
            request = self.input.request
            if decision.request_id != request.id:
                raise ApplicationError("wrong request", non_retryable=True)
            now = workflow.now()
            if request.expires_at and now >= request.expires_at:
                decision = Decision(
                    request_id=request.id,
                    actor=Actor("agent", request.requester_agent_id),
                    status="expired",
                    resolved_at=now,
                )
            else:
                decision = decision.model_copy(update={"resolved_at": now})
            result = await workflow.execute_local_activity(
                "resolve_hitl_request",
                decision,
                start_to_close_timeout=timedelta(seconds=15),
                result_type=dict[str, JSON],
            )
            self.decision = result
            return result

    @workflow.run
    async def run(self, input: HitlInput) -> None:
        self.input = input
        opened = await workflow.execute_activity(
            "open_hitl_request",
            input.request,
            start_to_close_timeout=timedelta(seconds=30),
            result_type=dict[str, JSON],
        )
        self.opened = opened
        if opened["status"] != "pending":
            self.decision = opened
        if self.decision is None:
            try:
                await workflow.wait_condition(
                    lambda: self.decision is not None,
                    timeout=(input.request.expires_at - workflow.now())
                    if input.request.expires_at
                    else None,
                )
            except asyncio.TimeoutError:
                await self.resolve(
                    Decision(
                        request_id=input.request.id,
                        actor=Actor("agent", input.request.requester_agent_id),
                        status="expired",
                        resolved_at=workflow.now(),
                    )
                )
        assert self.decision is not None
        result = self.decision.copy()
        if result["type"] == "approval" and result["status"] == "accepted":
            result["outcome"] = await workflow.execute_activity(
                "apply_hitl_outcome",
                input.request.id,
                start_to_close_timeout=timedelta(minutes=2),
                result_type=dict[str, JSON],
            )
        message = Message(
            id=stable(input.request.id, "result"),
            recipient_agent_id=input.request.requester_agent_id,
            source_kind="hitl",
            source_id=input.request.id,
            conversation_id=conversation(
                input.request.requester_agent_id, "hitl", input.request.id
            ),
            content=json.dumps(
                {
                    "request_id": str(input.request.id),
                    "status": result["status"],
                    "response": result.get("response"),
                    "outcome": result.get("outcome"),
                },
                ensure_ascii=False,
            ),
        )
        await workflow.execute_activity(
            "deliver_input",
            message,
            task_queue=input.bridge_queue,
            start_to_close_timeout=timedelta(minutes=2),
        )
        await workflow.wait_condition(workflow.all_handlers_finished)
