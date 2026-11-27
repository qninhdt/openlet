"""Pure Pydantic data models for HITL payloads, responses, and outcomes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AskOption(BaseModel):
    """Selectable option inside an HITL ask question."""

    id: str
    label: str


class AskQuestionForm(BaseModel):
    """Normalized question schema stored in an ask request payload."""

    id: str
    text: str
    type: Literal["text", "single_choice", "multiple_choice"]
    options: list[AskOption] = Field(default_factory=list[AskOption])


class AskPayload(BaseModel):
    """Payload schema for HITL ask requests."""

    model_config = ConfigDict(extra="ignore")

    questions: list[AskQuestionForm]


class ApprovalPayload(BaseModel):
    """Payload schema for HITL storage access approval requests."""

    model_config = ConfigDict(extra="ignore")

    role: Literal["viewer", "editor"]
    storage_id: str | None = None
    reason: str | None = None


class AskResponse(BaseModel):
    """Validated user response payload for an HITL ask request."""

    model_config = ConfigDict(extra="ignore")

    answers: dict[str, str | list[str]]
    note: str | None = None


class ApprovalResponse(BaseModel):
    """Optional user response note for an HITL approval decision."""

    model_config = ConfigDict(extra="ignore")

    note: str | None = None


class HitlOutcome(BaseModel):
    """Recorded side-effect outcome after applying an approved HITL request."""

    model_config = ConfigDict(extra="ignore")

    applied: bool
    storage_id: str | None = None
    role: Literal["viewer", "editor"] | None = None
    reason: str | None = None
