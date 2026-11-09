from typing import Literal

from pydantic import Field, model_validator

from leta.domain import ID, Input, NewMessage

ORCHESTRATION_QUEUE = "openlet-leta"
RUNTIME_QUEUE = "openlet-leta-runtime"


class AgentRef(Input):
    leta_id: ID
    agent_id: ID
    run_id: ID | None = None


class AgentStart(AgentRef):
    cursor: int = Field(default=0, ge=0)
    continuation: bool = False
    paused: bool = False
    history_events: int = Field(default=8000, ge=1)
    history_bytes: int = Field(default=8 << 20, ge=1)


class Bootstrap(Input):
    latest_seq: int = Field(ge=0)
    cursor: int = Field(ge=0)
    run_id: ID | None = None
    paused: bool
    stopped: bool


class AgentInput(Input):
    message: NewMessage
    schedule_id: ID | None = None

    @model_validator(mode="after")
    def require_agent(self):
        if self.message.recipient_agent_id is None:
            raise ValueError("agent inbox requires an agent recipient")
        return self


class InboxReceipt(Input):
    message_id: ID
    agent_id: ID
    seq: int = Field(gt=0)


class RunInput(AgentRef):
    run_id: ID


class RunControl(RunInput):
    action: Literal["yield", "stop"] = "yield"


class RunResult(Input):
    cursor: int = Field(ge=0)
    outcome: Literal["completed", "yielded", "paused"]


class AgentControl(Input):
    action: Literal["pause", "resume", "stop", "yield"]
    run_id: ID | None = None

    @model_validator(mode="after")
    def require_run_for_yield(self):
        if (self.action == "yield") != (self.run_id is not None):
            raise ValueError("only yield requires a run ID")
        return self


class AgentState(Input):
    latest_seq: int = 0
    cursor: int = 0
    run_id: ID | None = None
    continuation: bool = False
    paused: bool = False
    stopped: bool = False
