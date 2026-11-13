import base64
import io

import pytest
from letfs_ingest.providers import Metadata, SemanticType, evidence, vision
from letfs_ingest.readme import own_body, render
from openlet_sdk.config import Config
from PIL import Image
from pydantic import ValidationError


def test_evidence_covers_middle_and_end_within_budget() -> None:
    text = "first topic " * 500 + "middle subject " * 1000 + "final topic " * 500
    sampled = evidence(text, "text/markdown", 800)
    assert len(sampled) <= 800
    assert all(
        topic in sampled for topic in ("first topic", "middle subject", "final topic")
    )
    csv = evidence("name,value\n" + "record,12\n" * 10000, "text/csv", 800)
    assert "name, value" in csv and csv.count("record, 12") == 8


def test_metadata_taxonomy_readme_body_and_image_size(config: Config) -> None:
    metadata = Metadata(
        title="  Report  ",
        description="Annual results",
        semantic_type=SemanticType.DOCUMENT_REPORT,
        context="Sales trends",
    )
    assert metadata.title == "Report"
    with pytest.raises(ValidationError):
        Metadata.model_validate(
            {**metadata.model_dump(), "semantic_type": "made-up:type"}
        )
    body = "# Original content\n\nKeep this evidence."
    rendered = render(metadata, body, {"table-1.csv": {"title": "Revenue"}})
    assert own_body(rendered) == body
    assert render(metadata, rendered, {}) == render(metadata, body, {})
    data = io.BytesIO()
    Image.new("RGBA", (2400, 1200), "red").save(data, "PNG")
    settings = config["models"]["enrichment"]
    settings.update(
        max_image_pixels=3000000, image_max_side=1600, image_jpeg_quality=85
    )
    encoded = vision(data.getvalue(), settings)
    with Image.open(io.BytesIO(base64.b64decode(encoded.split(",", 1)[1]))) as image:
        assert image.size == (1600, 800)
        assert image.mode == "RGB"
    with pytest.raises(ValueError, match="pixel limit"):
        vision(data.getvalue(), {**settings, "max_image_pixels": 10})


@pytest.mark.parametrize(
    ("mode", "valid"),
    [("tools", True), ("json_schema", True), ("text", True), ("tools", False)],
)
async def test_instructor_owns_correction_and_records_each_paid_attempt(
    config: Config, monkeypatch: pytest.MonkeyPatch, mode: str, valid: bool
) -> None:
    import asyncio
    import json
    from contextlib import nullcontext
    from typing import Literal, cast

    from langfuse import Langfuse
    from langfuse.api.prompts.types.prompt import Prompt_Text
    from langfuse.model import TextPromptClient
    from letfs_ingest import providers
    from litellm.types.utils import ModelResponse  # pyright: ignore[reportMissingTypeStubs]  # Upstream has no py.typed.

    updates: list[dict[str, object]] = []
    requests: list[dict[str, object]] = []

    class Observation:
        def update(self, **kwargs: object) -> None:
            updates.append(kwargs)

    class Prompts:
        def get_prompt(self, *args: object, **kwargs: object) -> TextPromptClient:
            return TextPromptClient(
                Prompt_Text(
                    name="letfs/enrichment",
                    version=1,
                    prompt="Describe the file.",
                    labels=[],
                    tags=[],
                    config={"model": "chat", "max_tokens": 512},
                )
            )

        def start_as_current_observation(
            self, **kwargs: object
        ) -> nullcontext[Observation]:
            return nullcontext(Observation())

    async def complete(**kwargs: object) -> ModelResponse:
        requests.append(kwargs)
        payload = (
            {}
            if len(requests) == 1 or not valid
            else {
                "title": "Report",
                "description": "Results",
                "semantic_type": "document:report",
                "context": "Annual results",
            }
        )
        if mode == "tools":
            message: dict[str, object] = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call-{len(requests)}",
                        "type": "function",
                        "function": {
                            "name": "Metadata",
                            "arguments": json.dumps(payload),
                        },
                    }
                ],
            }
        else:
            message = {"role": "assistant", "content": json.dumps(payload)}
        result = ModelResponse(
            model="chat",
            choices=[
                {
                    "index": 0,
                    "finish_reason": "tool_calls" if mode == "tools" else "stop",
                    "message": message,
                }
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        cast(dict[str, object], getattr(result, "_hidden_params"))["response_cost"] = (
            len(requests) / 10
        )
        return result

    monkeypatch.setenv("LITELLM_MASTER_KEY", "fixture")
    config["models"]["enrichment"]["output_mode"] = cast(
        Literal["tools", "json_schema", "text"], mode
    )
    monkeypatch.setattr(providers, "get_client", lambda: cast(Langfuse, Prompts()))
    monkeypatch.setattr(providers.litellm, "acompletion", complete)
    config["services"]["letfs_ingest"]["io"]["model_concurrency"] = 1
    ai = providers.Models(config, "production")
    pending = ai.describe("report.txt", "Annual results", "text/plain", "")
    # Enrichment holds this slot across artifact download and generation.
    async with ai.slots, asyncio.timeout(3):
        if valid:
            assert (await pending).title == "Report"
        else:
            from instructor.core.exceptions import InstructorRetryException

            with pytest.raises(InstructorRetryException):
                await pending
    assert len(requests) == len(updates) == 2
    assert [update["cost_details"] for update in updates] == [
        {"total": 0.1},
        {"total": 0.2},
    ]
    assert [update["usage_details"] for update in updates] == [
        {"input": 10, "output": 5}
    ] * 2
    assert all(request["num_retries"] == 0 for request in requests)
    assert "validation" in str(requests[1]["messages"]).lower()
