"""DeepEval judge factory for OpenAI-compatible endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from deepeval.models import OpenAIModel

if TYPE_CHECKING:
    from openlet_sdk.types import MutableJsonObject


def make_judge(
    *,
    model: str,
    base_url: str,
    api_key: str,
    reasoning_effort: str | None = None,
) -> OpenAIModel:
    """Build a DeepEval OpenAIModel configured for the given endpoint."""
    gen_kwargs: MutableJsonObject = {}
    if reasoning_effort:
        gen_kwargs["extra_body"] = {"reasoning_effort": reasoning_effort}

    return OpenAIModel(
        model=model,
        api_key=api_key,
        base_url=base_url,
        cost_per_input_token=0.0,
        cost_per_output_token=0.0,
        generation_kwargs=gen_kwargs or None,
    )
