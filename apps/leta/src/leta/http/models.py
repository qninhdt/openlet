from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from leta.domain import ID, Input, Named
from leta.human import (
    AskForm,
    MultipleChoiceAnswer,
    PersonalScopeResource,
    SingleChoiceAnswer,
    TextAnswer,
)
from leta.runtime.boxes import LetiDefinition
from leta.schedules import ScheduleInputSpec


class CreateLeta(Named):
    workspace_id: ID
    system_prompt: str = Field(max_length=100_000)
    model_id: str = Field(min_length=1)
    reasoning_effort: str | None


class CreateBox(Named):
    letis: list[LetiDefinition] = Field(min_length=1)
    edges: list[tuple[str, str]]
    representative: str


class ChildConfiguration(Input):
    model_id: str | None = Field(default=None, min_length=1)
    reasoning_effort: str | None = Field(default=None, min_length=1)


class CreateSchedule(Input):
    title: str = Field(min_length=1, max_length=400)
    content: str = Field(max_length=100_000)
    spec: ScheduleInputSpec
    target_agent_id: ID | None = None
    box_id: ID | None = None
    end_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_end(self):
        if self.spec.type == "at" and self.end_at is not None:
            raise ValueError("one-shot schedules have no recurring end_at")
        return self


class SendMessage(Input):
    id: ID
    content: str = Field(max_length=100_000)
    in_reply_to: ID | None = None


class HumanResponse(Input):
    action: Literal["answer", "accept", "deny"]
    answers: (
        dict[str, SingleChoiceAnswer | MultipleChoiceAnswer | TextAnswer] | None
    ) = None
    reason: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_answers(self):
        if (self.action == "answer") != (self.answers is not None):
            raise ValueError("only an answer supplies form responses")
        return self


class CancelRequest(Input):
    reason: str = Field(default="", max_length=4000)


class AgentView(Input):
    id: UUID
    leta_id: UUID
    kind: Literal["leta", "leti"]
    workspace_id: UUID | None = None
    created_by_user_id: UUID | None = None
    box_id: UUID | None = None
    name: str
    description: str
    system_prompt: str
    model_id: str | None
    reasoning_effort: str | None
    status: Literal["initializing", "active", "deleting", "archived"]
    paused: bool
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    run_id: UUID | None = None
    run_status: str | None = None
    pending_input_count: int | None = None


def agent_view(row, *, paused=None):
    value = {key: row[key] for key in AgentView.model_fields if key in row}
    if paused is not None:
        value["paused"] = paused
    return AgentView.model_validate(value).model_dump(mode="json")


class MessageView(Input):
    id: UUID
    leta_id: UUID
    sender_agent_id: UUID | None
    recipient_agent_id: UUID | None
    recipient_user_id: UUID | None
    source_type: str
    source_id: str
    source_label: str
    conversation_key: str | None
    reply_to: dict[str, JsonValue] | None
    in_reply_to_message_id: UUID | None
    seq: int | None
    content: str
    data: dict[str, JsonValue]
    created_at: datetime
    read_at: datetime | None


def message_view(row):
    return MessageView.model_validate(
        {key: row[key] for key in MessageView.model_fields}
    ).model_dump(mode="json")


class Page[T](Input):
    items: list[T]
    next_cursor: str | None


class RunView(Input):
    id: UUID
    agent_id: UUID
    status: Literal["running", "paused", "completed", "failed", "cancelled"]
    started_at: datetime
    finished_at: datetime | None
    attempt: int
    inbox_cursor: int
    result: JsonValue
    error: JsonValue
    events_url: str


class AccessReason(Input):
    reason: str


class RequestView(Input):
    id: UUID
    requester_agent_id: UUID
    kind: Literal["ask", "approval"]
    title: str
    payload: AskForm | AccessReason
    approver_user_id: UUID
    resource: PersonalScopeResource | None
    requested_role: Literal["viewer", "editor"] | None
    status: Literal["pending", "resolved", "cancelled", "expired"]
    expires_at: datetime | None
    decision: dict[str, JsonValue] | None
    outcome: dict[str, JsonValue] | None
    created_at: datetime
    resolved_at: datetime | None


class RequestCard(RequestView):
    leta_id: UUID
    workspace_id: UUID
    created_by_user_id: UUID
    leta_name: str
    requester_name: str
    box_id: UUID | None
    box_name: str | None
    visibility_notice: str


class PendingCommand(Input):
    status: Literal["pending"]
    resource_id: UUID
    idempotency_key: UUID | None
    detail: str


class ScheduleView(Input):
    id: UUID
    leta_id: UUID
    creator_agent_id: UUID
    target_agent_id: UUID
    box_id: UUID | None
    title: str
    content: str
    spec: ScheduleInputSpec
    end_at: datetime | None
    paused: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    upcoming: list[datetime] | None = None
    forecast_status: Literal["available", "unavailable", "deleted"] | None = None
    upcoming_limit: int | None = None


class Occurrence(Input):
    schedule_id: UUID
    title: str
    target_agent_id: UUID
    box_id: UUID | None
    scheduled_at: datetime
    timezone: str
    paused: bool


class PendingRequestSummary(Input):
    id: UUID
    requester_agent_id: UUID
    kind: Literal["ask", "approval"]
    title: str
    status: Literal["pending"]
    expires_at: datetime | None


class ScheduleSummary(Input):
    id: UUID
    target_agent_id: UUID
    title: str
    paused: bool


class RunSummary(Input):
    id: UUID
    agent_id: UUID
    status: str
    started_at: datetime


class BoxView(Input):
    id: UUID
    leta_id: UUID
    name: str
    description: str
    representative_agent_id: UUID
    status: Literal["initializing", "active", "deleting", "archived"]
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    agent_count: int | None = None
    pending_request_count: int | None = None
    schedule_count: int | None = None
    letis: list[AgentView] | None = None
    edges: list[tuple[UUID, UUID]] | None = None
    runs: list[RunSummary] | None = None
    requests: list[PendingRequestSummary] | None = None
    schedules: list[ScheduleSummary] | None = None
