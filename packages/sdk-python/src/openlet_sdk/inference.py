from typing import NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from openlet_sdk.config import ReasoningEffort
from openlet_sdk.types import is_str_mapping


class GenerationParameters(TypedDict):
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


def response_cost(value: object) -> dict[str, float] | None:
    import math

    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    ):
        return {"total": float(value)}
    return None


def usage_details(value: object) -> dict[str, int] | None:
    from pydantic import BaseModel

    if not isinstance(value, BaseModel):
        return None
    raw = value.model_dump(exclude_none=True)
    result: dict[str, int] = {}
    for source, target in (("prompt_tokens", "input"), ("completion_tokens", "output")):
        count = raw.get(source)
        if isinstance(count, int):
            result[target] = count
    for source, detail, target in (
        ("prompt_tokens_details", "cached_tokens", "input_cached"),
        ("completion_tokens_details", "reasoning_tokens", "output_reasoning"),
    ):
        details = raw.get(source)
        if is_str_mapping(details):
            count = details.get(detail)
            if isinstance(count, int):
                result[target] = count
                # Langfuse usage categories are additive; provider detail counts are subsets.
                total = "input" if source == "prompt_tokens_details" else "output"
                if total in result:
                    result[total] = max(0, result[total] - count)
    return result or None
