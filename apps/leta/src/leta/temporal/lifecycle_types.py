from typing import Literal

from pydantic import Field, model_validator

from leta.domain import ID, AgentConfiguration, Input, NewBox, NewLeta
from leta.temporal.types import AgentControl


class LifecycleStart(Input):
    leta_id: ID
    box_id: ID | None = None
    history_events: int = Field(default=8000, ge=1)
    history_bytes: int = Field(default=8 << 20, ge=1)


class LetaChange(Input):
    leta_id: ID
    action: Literal[
        "create", "configure", "pause", "resume", "active", "deleting", "archived"
    ]
    creation: NewLeta | None = None
    agent_id: ID | None = None
    configuration: AgentConfiguration | None = None
    workspace_deletion: bool = False

    @model_validator(mode="after")
    def validate_command(self):
        if self.workspace_deletion and self.action != "deleting":
            raise ValueError("workspace cleanup requires deleting")
        if (self.action == "create") != (self.creation is not None):
            raise ValueError("only create requires a Leta specification")
        if self.creation is not None and self.creation.id != self.leta_id:
            raise ValueError("creation targets another Leta")
        if (self.action == "configure") != (self.configuration is not None):
            raise ValueError("only configure requires a configuration")
        if self.agent_id is not None and self.action != "configure":
            raise ValueError("only configure accepts a target agent")
        return self


class BoxChange(Input):
    leta_id: ID
    box_id: ID
    action: Literal["create", "active", "deleting", "archived"]
    creation: NewBox | None = None

    @model_validator(mode="after")
    def validate_command(self):
        if (self.action == "create") != (self.creation is not None):
            raise ValueError("only create requires a box specification")
        if self.creation is not None and (
            self.creation.id != self.box_id or self.creation.leta_id != self.leta_id
        ):
            raise ValueError("creation targets another box")
        return self


class LifecycleSnapshot(Input):
    leta_id: ID
    box_id: ID | None = None
    status: str
    agent_ids: list[ID] = Field(default_factory=list)
    box_ids: list[ID] = Field(default_factory=list)
    schedule_ids: list[ID] = Field(default_factory=list)
    request_ids: list[ID] = Field(default_factory=list)


class ResourceRef(Input):
    leta_id: ID
    box_id: ID | None = None
    remove: bool = False


class LifecycleAgentControl(Input):
    leta_id: ID
    agent_id: ID
    control: AgentControl
