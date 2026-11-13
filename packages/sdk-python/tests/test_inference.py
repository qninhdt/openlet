import pytest
from openai.types import CompletionUsage
from openai.types.completion_usage import CompletionTokensDetails, PromptTokensDetails
from openlet_sdk.inference import InferenceSettings, response_cost, usage_details
from pydantic import ValidationError


def test_cost_and_usage_preserve_unknown_zero_and_token_subsets() -> None:
    assert response_cost(None) is None
    assert response_cost(float("nan")) is None
    assert response_cost(-1) is None
    assert response_cost(True) is None
    assert response_cost(0) == {"total": 0.0}
    assert usage_details(
        CompletionUsage(
            prompt_tokens=100,
            completion_tokens=40,
            total_tokens=140,
            prompt_tokens_details=PromptTokensDetails(cached_tokens=80),
            completion_tokens_details=CompletionTokensDetails(reasoning_tokens=30),
        )
    ) == {"input": 20, "output": 10, "input_cached": 80, "output_reasoning": 30}
    assert InferenceSettings(model="chat", max_tokens=512).parameters() == {
        "max_tokens": 512
    }
    with pytest.raises(ValidationError):
        InferenceSettings.model_validate(
            {"model": "chat", "max_tokens": 512, "unknown_parameter": 1}
        )
