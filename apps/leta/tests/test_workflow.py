import asyncio
from collections.abc import Awaitable, Callable
from typing import cast
from uuid import UUID, uuid4

import pytest
from leta.jobs.agent import Agent, AgentInput, RunResult
from leta.messages import Message
from openlet_sdk.config import JSON
from temporalio import workflow


async def test_consumed_late_admissions_do_not_wake_again_but_new_input_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(AgentInput(agent_id=uuid4(), runtime_queue="runtime"))
    runs: list[asyncio.Future[RunResult]] = []
    admissions: dict[UUID, asyncio.Future[dict[str, JSON]]] = {}

    async def load(self: Agent) -> dict[str, JSON]:
        return {"active": True, "paused": False, "run_id": None}

    async def local(name: str, *args: object, **kwargs: object) -> dict[str, JSON]:
        if name == "admit_input":
            messages = cast(list[Message], args[0])
            return await admissions[messages[-1].id]
        return {}

    def start(*args: object, **kwargs: object) -> workflow.ActivityHandle[RunResult]:
        result = asyncio.get_running_loop().create_future()
        runs.append(result)
        return cast(workflow.ActivityHandle[RunResult], result)

    async def condition(check: Callable[[], bool]) -> None:
        while not check():
            await asyncio.sleep(0.001)

    monkeypatch.setattr(Agent, "load", load)

    def rotate(self: Agent) -> None:
        pass

    monkeypatch.setattr(Agent, "rotate", rotate)
    monkeypatch.setattr(workflow, "start_activity", start)
    monkeypatch.setattr(workflow, "execute_local_activity", local)
    monkeypatch.setattr(workflow, "wait_condition", condition)
    monkeypatch.setattr(workflow, "uuid4", uuid4)
    monkeypatch.setattr(workflow, "all_handlers_finished", lambda: True)

    async def until(check: Callable[[], bool]) -> None:
        await asyncio.wait_for(condition(check), 2)

    def message() -> Message:
        value = Message(
            id=uuid4(),
            conversation_id=uuid4(),
            recipient_agent_id=agent.input.agent_id,
            source_kind="user",
            source_id=uuid4(),
            content="Work",
        )
        admissions[value.id] = asyncio.get_running_loop().create_future()
        return value

    execution = asyncio.create_task(agent.run(agent.input))
    await until(lambda: len(runs) == 1)
    first, second = message(), message()
    handlers = [
        asyncio.ensure_future(
            cast(Awaitable[dict[str, JSON]], Agent.receive(agent, [value]))
        )
        for value in (first, second)
    ]
    # SQL admission can commit before its workflow handler returns. The activity
    # already consumed both, and the handlers later complete out of order.
    runs[0].set_result(RunResult(status="completed", inbox_cursor=2))
    await until(lambda: agent.active is None)
    admissions[second.id].set_result({"seq": 2})
    admissions[first.id].set_result({"seq": 1})
    await asyncio.gather(*handlers)
    await asyncio.sleep(0.01)
    assert len(runs) == 1 and agent.admitted_seq == 2

    quiet = message().model_copy(update={"silent": True})
    admissions[quiet.id].set_result({"seq": 3})
    await cast(Awaitable[dict[str, JSON]], Agent.receive(agent, [quiet]))
    await asyncio.sleep(0.01)
    assert len(runs) == 1 and agent.admitted_seq == 2

    third = message()
    admissions[third.id].set_result({"seq": 3})
    await cast(Awaitable[dict[str, JSON]], Agent.receive(agent, [third]))
    await until(lambda: len(runs) == 2)
    assert agent.run_id is not None
    await cast(Awaitable[None], Agent.cancel_current(agent, agent.run_id))
    await asyncio.sleep(0.01)
    assert len(runs) == 2 and agent.suppressed_through == 3

    fourth, fifth = message(), message()
    admissions[fifth.id].set_result({"seq": 5})
    await cast(Awaitable[dict[str, JSON]], Agent.receive(agent, [fourth, fifth]))
    await until(lambda: len(runs) == 3)
    assert agent.admitted_seq == 5
    runs[2].set_result(RunResult(status="completed", inbox_cursor=5))
    await until(lambda: agent.active is None)
    agent.stopping = True
    await asyncio.wait_for(execution, 2)


async def test_silent_delivery_never_calls_temporal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from leta import messages
    from leta.config import Services
    from leta.worker import deliver

    message = Message(
        id=uuid4(),
        recipient_agent_id=uuid4(),
        source_kind="user",
        source_id=uuid4(),
        conversation_id=uuid4(),
        content="Feedback",
        silent=True,
    )

    async def admit(db: object, auth: object, value: list[Message]) -> dict[str, JSON]:
        assert value == [message]
        return {"seq": 1}

    monkeypatch.setattr(messages, "admit", admit)
    # No config or Temporal client exists: this must only persist the input.
    services = cast(Services, SimpleNamespace(db=None, auth=None))
    assert await deliver(services, [message]) == {"seq": 1}
