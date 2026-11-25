"""DeepEval OpenAIModel factory configured for OpenAI-compatible gateways (e.g. Vilao)."""

from __future__ import annotations

from deepeval.models import OpenAIModel


def make_judge(
    *,
    model: str,
    base_url: str,
    api_key: str,
    reasoning_effort: str | None = None,
) -> OpenAIModel:
    """Build a DeepEval OpenAIModel with schema/json-mode disabled for Vilao compatibility."""
    gen_kwargs: dict[str, object] = {}
    if reasoning_effort:
        gen_kwargs["extra_body"] = {"reasoning_effort": reasoning_effort}

    judge = OpenAIModel(
        model=model,
        api_key=api_key,
        base_url=base_url,
        cost_per_input_token=0.0,
        cost_per_output_token=0.0,
        generation_kwargs=gen_kwargs or None,
    )
    # Match supports_response_schema: false in infra/config/litellm.yaml
    judge.model_data.supports_structured_outputs = False
    judge.model_data.supports_json = False
    return judge
