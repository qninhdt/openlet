"""Validated product inputs; authorization identities come from runtime context."""

import unicodedata
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from openlet.errors import AppError
from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_serializer,
    model_validator,
)

from leta.config import ModelSelection


def fault(reason: str, detail: str, kind: str = "conflict") -> AppError:
    return AppError(detail, reason=reason, kind=kind, retryable=False)


def _nonzero(value: UUID) -> UUID:
    if not value.int:
        raise ValueError("nonzero UUID required")
    return value


ID = Annotated[UUID, AfterValidator(_nonzero)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    @field_validator("*")
    @classmethod
    def validate_text(cls, value):
        if isinstance(value, str):
            if "\0" in value:
                raise ValueError("text cannot contain NUL")
            value.encode("utf-8")
        return value


class Lifecycle(StrEnum):
    INITIALIZING = "initializing"
    ACTIVE = "active"
    DELETING = "deleting"
    ARCHIVED = "archived"


class HumanStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class RunStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActivityKind(StrEnum):
    INBOX_INPUT = "inbox_input"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL_NOTE = "final_note"
    COMPACTION = "compaction"


def box_slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name).casefold()
    result = ""
    for char in normalized:
        if char.isalnum() or char in "-_":
            result += char
        elif result and not result.endswith("-"):
            result += "-"
    result = result.strip("-_")
    if not result:
        raise ValueError("box name must yield a usable path")
    return result


class Named(Input):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_name(self):
        if (
            not self.name.strip()
            or self.name.strip() != self.name
            or any(unicodedata.category(char).startswith("C") for char in self.name)
        ):
            raise ValueError("invalid name")
        return self


class NewLeta(Named):
    id: ID
    workspace_id: ID
    created_by_user_id: ID
    home_scope_id: ID
    system_prompt: str = Field(max_length=100_000)
    model: ModelSelection


class LetiSpec(Named):
    id: ID
    system_prompt: str = Field(max_length=100_000)


class AgentConfiguration(Input):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    model_id: str | None = Field(default=None, min_length=1)
    reasoning_effort: str | None = Field(default=None, min_length=1)
    system_prompt: str | None = Field(default=None, max_length=100_000)

    @model_serializer(mode="wrap")
    def serialize_patch(self, serialize):
        # Preserve omitted fields across Temporal's JSON round trip.
        return {
            key: value
            for key, value in serialize(self).items()
            if key in self.model_fields_set
        }

    @model_validator(mode="after")
    def validate_profile(self):
        for key in ("name", "description", "system_prompt"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        if self.name is not None:
            Named(name=self.name)
        return self


class NewBox(Named):
    id: ID
    leta_id: ID
    home_node_id: ID
    letis: list[LetiSpec] = Field(min_length=1)
    edges: list[tuple[str, str]] = Field(default_factory=list)
    representative: str

    @model_validator(mode="after")
    def validate_graph(self):
        box_slug(self.name)
        names = {agent.name for agent in self.letis}
        ids = {agent.id for agent in self.letis}
        if len(names) != len(self.letis) or len(ids) != len(self.letis):
            raise ValueError("duplicate Leti name or ID")
        if self.leta_id in ids or self.representative not in names:
            raise ValueError("invalid representative or child identity")
        edges = set()
        for left, right in self.edges:
            if left not in names or right not in names or left == right:
                raise ValueError("invalid communication edge")
            pair = tuple(sorted((left, right)))
            if pair in edges:
                raise ValueError("duplicate communication edge")
            edges.add(pair)
        return self


class Source(Input):
    type: str = Field(min_length=1, max_length=100)
    id: str = Field(min_length=1, max_length=200)
    label: str = Field(max_length=400)


class ReplyTo(Input):
    type: Literal["user", "box", "agent"]
    id: ID


class NewMessage(Input):
    id: ID
    leta_id: ID
    sender_agent_id: ID | None = None
    recipient_agent_id: ID | None = None
    recipient_user_id: ID | None = None
    source: Source
    conversation_key: str | None = Field(default=None, max_length=400)
    reply_to: ReplyTo | None = None
    in_reply_to_message_id: ID | None = None
    content: str = Field(max_length=100_000)
    data: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_recipient(self):
        if (self.recipient_agent_id is None) == (self.recipient_user_id is None):
            raise ValueError("exactly one recipient required")
        return self


class NewActivity(Input):
    id: ID
    agent_id: ID
    run_id: ID | None = None
    kind: ActivityKind
    llm_message_id: str | None = None
    tool_call_id: str | None = None
    message_id: ID | None = None
    dedup_key: str = Field(min_length=1, max_length=400)
    data: dict[str, JsonValue]


class NewHumanRequest(Input):
    id: ID
    leta_id: ID
    requester_agent_id: ID
    kind: Literal["ask", "approval"]
    title: str = Field(min_length=1, max_length=400)
    payload: dict[str, JsonValue]
    approver_user_id: ID
    outcome_message_id: ID
    expires_at: AwareDatetime | None = None
    grantee_leta_id: ID | None = None
    resource: dict[str, JsonValue] | None = None
    requested_role: Literal["viewer", "editor"] | None = None
    grant_key: ID | None = None

    @model_validator(mode="after")
    def validate_kind(self):
        grant = (
            self.grantee_leta_id,
            self.resource,
            self.requested_role,
            self.grant_key,
        )
        if self.kind == "ask":
            if any(value is not None for value in grant):
                raise ValueError("ask cannot grant resource access")
        elif (
            any(value is None for value in grant[:-1])
            or self.grantee_leta_id != self.leta_id
        ):
            raise ValueError("approval must grant access to root Leta")
        return self


class NewSchedule(Input):
    id: ID
    leta_id: ID
    creator_agent_id: ID
    target_agent_id: ID
    box_id: ID | None = None
    title: str = Field(min_length=1, max_length=400)
    content: str = Field(max_length=100_000)
    spec: dict[str, JsonValue]
    end_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_spec(self):
        if self.spec.get("type") not in {"at", "interval", "calendar"}:
            raise ValueError("invalid schedule type")
        if self.spec["type"] == "at" and self.end_at is not None:
            raise ValueError("one-shot schedules have no recurring end_at")
        return self


class SchedulePatch(Input):
    title: str | None = Field(default=None, min_length=1, max_length=400)
    content: str | None = Field(default=None, max_length=100_000)
    spec: dict[str, JsonValue] | None = None
    end_at: AwareDatetime | None = None
    paused: bool | None = Field(default=None, strict=True)

    @model_serializer(mode="wrap")
    def serialize_patch(self, serialize):
        return {
            key: value
            for key, value in serialize(self).items()
            if key in self.model_fields_set
        }

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set:
            raise ValueError("schedule patch is empty")
        for key in self.model_fields_set - {"end_at"}:
            if getattr(self, key) is None:
                raise ValueError(f"{key} cannot be null")
        return self


class TimeCursor(Input):
    at: AwareDatetime
    id: ID
