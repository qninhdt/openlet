"""Inference settings, generation parameters, and usage normalization helpers."""

import math
from typing import NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from openlet_sdk.config import ReasoningEffort


class GenerationParameters(TypedDict):
    """Normalized model generation parameters."""

    max_tokens: int
    reasoning_effort: NotRequired[ReasoningEffort]
    temperature: NotRequired[float]
    top_p: NotRequired[float]
    top_k: NotRequired[int]


class InferenceSettings(BaseModel):
    """Task defaults versioned with the managed prompt."""

    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1)
    reasoning_effort: ReasoningEffort = None
    max_tokens: int = Field(gt=0)
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, gt=0, le=1)
    top_k: int | None = Field(default=None, gt=0)

    def parameters(self) -> GenerationParameters:
        """Build model generation parameters excluding unset optional fields."""
        result = GenerationParameters(max_tokens=self.max_tokens)
        if self.reasoning_effort is not None:
            result["reasoning_effort"] = self.reasoning_effort
        if self.temperature is not None:
            result["temperature"] = self.temperature
        if self.top_p is not None:
            result["top_p"] = self.top_p
        if self.top_k is not None:
            result["top_k"] = self.top_k
        return result


class _PromptTokensDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cached_tokens: int | None = None


class _CompletionTokensDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reasoning_tokens: int | None = None


class _UsagePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    prompt_tokens_details: _PromptTokensDetails | None = None
    completion_tokens_details: _CompletionTokensDetails | None = None


def response_cost(value: object) -> dict[str, float] | None:
    """Normalize a non-negative finite response cost into Langfuse cost details."""
    if (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    ):
        return {"total": float(value)}
    return None


def usage_details(value: object) -> dict[str, int] | None:
    """Extract additive token usage counts for Langfuse from a provider usage object."""
    if not isinstance(value, BaseModel):
        return None
    try:
        parsed = _UsagePayload.model_validate(value.model_dump(exclude_none=True))
    except ValidationError:
        return None
    result: dict[str, int] = {}
    if parsed.prompt_tokens is not None:
        result["input"] = parsed.prompt_tokens
    if parsed.completion_tokens is not None:
        result["output"] = parsed.completion_tokens
    if (
        parsed.prompt_tokens_details is not None
        and parsed.prompt_tokens_details.cached_tokens is not None
    ):
        cached = parsed.prompt_tokens_details.cached_tokens
        result["input_cached"] = cached
        # Langfuse usage categories are additive; provider detail counts are subsets.
        if "input" in result:
            result["input"] = max(0, result["input"] - cached)
    if (
        parsed.completion_tokens_details is not None
        and parsed.completion_tokens_details.reasoning_tokens is not None
    ):
        reasoning = parsed.completion_tokens_details.reasoning_tokens
        result["output_reasoning"] = reasoning
        if "output" in result:
            result["output"] = max(0, result["output"] - reasoning)
    return result or None
