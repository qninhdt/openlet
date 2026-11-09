from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from leta.domain import ID, Input, NewSchedule, SchedulePatch
from leta.temporal.types import AgentInput


class ScheduleRef(Input):
    leta_id: ID
    schedule_id: ID


class ScheduleStart(ScheduleRef):
    history_events: int = Field(default=8000, ge=1)
    history_bytes: int = Field(default=8 << 20, ge=1)


class ScheduleChange(ScheduleRef):
    action: Literal["create", "update", "delete"]
    requester_agent_id: ID
    # Accepted Update input fixes relative times even if the Local marker is lost.
    requested_at: AwareDatetime
    creation: NewSchedule | None = None
    patch: SchedulePatch | None = None

    @model_validator(mode="after")
    def check_change(self):
        if (self.action == "create") != (self.creation is not None):
            raise ValueError("only create requires a definition")
        if (self.action == "update") != (self.patch is not None):
            raise ValueError("only update requires a patch")
        if self.creation is not None and (
            self.creation.id != self.schedule_id
            or self.creation.leta_id != self.leta_id
            or self.creation.creator_agent_id != self.requester_agent_id
        ):
            raise ValueError("creation identity differs from change")
        return self


class ScheduleDefinition(NewSchedule):
    paused: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ScheduleOccurrence(ScheduleRef):
    scheduled_at: AwareDatetime | None = None


class ScheduleSnapshot(Input):
    delivery: AgentInput | None = None
