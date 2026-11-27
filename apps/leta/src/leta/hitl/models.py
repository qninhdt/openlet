"""Pure Pydantic data models for HITL payloads, responses, and outcomes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AskOption(BaseModel):
    id: str
    label: str


class AskQuestionForm(BaseModel):
    id: str
    text: str
    type: Literal["text", "single_choice", "multiple_choice"]
    options: list[AskOption] = Field(default_factory=list[AskOption])


class AskPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    questions: list[AskQuestionForm]


class ApprovalPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: Literal["viewer", "editor"]
    storage_id: str | None = None
    reason: str | None = None


class AskResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answers: dict[str, str | list[str]]
    note: str | None = None


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    note: str | None = None


class HitlOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    applied: bool
    storage_id: str | None = None
    role: Literal["viewer", "editor"] | None = None
    reason: str | None = None
