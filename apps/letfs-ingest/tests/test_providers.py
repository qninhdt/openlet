import json
from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest
from letfs_ingest.providers import (
    BatchEnrichment,
    EnrichItem,
    Models,
    evidence,
    pack_batches,
    vision,
)
from openlet_sdk.config import Config
from PIL import Image


def test_evidence_samples_text_and_csv_within_budget() -> None:
    text = ("HEAD " * 40) + ("MID " * 80) + ("TAIL " * 40)
    sampled = evidence(text, "text/plain", 160)
    assert (
        len(sampled) <= 160
        and "HEAD" in sampled
        and "TAIL" in sampled
        and "..." in sampled
    )

    rows = ["colA,colB", "a,1", "b,2"] + [f"row{i},{i}" for i in range(20)] + ["z,99"]
    csv_sample = evidence("\n".join(rows), "text/csv", 120)
    assert (
        "colA,colB" in csv_sample
        and "z,99" in csv_sample
        and "Total rows: 24" in csv_sample
    )


def test_batch_enrichment_validates_expected_ids() -> None:
    payload = {
        "items": [
            {
                "id": "01-intro.md",
                "title": "Intro",
                "description": "Summary",
                "slug": "intro",
            }
        ]
    }
    valid = BatchEnrichment.model_validate(
        payload, context={"expected_ids": ["01-intro.md"]}
    )
    assert valid.items[0].slug == "intro"

    with pytest.raises(ValueError, match="mismatch"):
        BatchEnrichment.model_validate(
            payload, context={"expected_ids": ["01-intro.md", "02-body.md"]}
        )


def test_batch_enrichment_uses_2x_hard_caps_for_title_and_description() -> None:
    within_hard_caps = {
        "items": [
            {
                "id": "01-intro.md",
                "title": "t" * 128,
                "description": "d" * 512,
                "slug": "intro",
            }
        ]
    }
    parsed = BatchEnrichment.model_validate(within_hard_caps)
    assert len(parsed.items[0].title) == 128
    assert len(parsed.items[0].description) == 512

    with pytest.raises(ValueError, match="128"):
        BatchEnrichment.model_validate(
            {
                "items": [
                    {
                        "id": "01-intro.md",
                        "title": "t" * 129,
                        "description": "ok",
                    }
                ]
            }
        )

    with pytest.raises(ValueError, match="512"):
        BatchEnrichment.model_validate(
            {
                "items": [
                    {
                        "id": "01-intro.md",
                        "title": "ok",
                        "description": "d" * 513,
                    }
                ]
            }
        )


def test_pack_batches_enforces_chars_items_and_image_caps() -> None:
    items = [
        EnrichItem(id=f"doc-{i}.md", media_type="text/markdown", text_sample="x" * 2000)
        for i in range(25)
    ]
    batches = pack_batches(items, char_budget=36_000, max_items=20, max_images=6)
    assert len(batches) == 2
    assert len(batches[0]) == 17  # 17 * ~2050 = ~34850 <= 36000; 18th overflows 36k
    assert len(batches[1]) == 8

    imgs = [
        EnrichItem(id=f"img-{i}.png", media_type="image/png", image_b64="a" * 100)
        for i in range(8)
    ]
    img_batches = pack_batches(imgs, char_budget=36_000, max_items=20, max_images=6)
    assert [len(b) for b in img_batches] == [6, 2]


def test_vision_resizes_image(config: Config) -> None:
    img = Image.new("RGB", (2000, 1000), "red")
    buf = BytesIO()
    img.save(buf, format="PNG")
    b64 = vision(buf.getvalue(), config["models"]["enrichment"])
    assert len(b64) > 0


async def test_describe_batch_interleaves_artifacts_and_retries_with_instructor(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured_messages: list[Any] = []
    calls = 0

    class DummyObs:
        def __enter__(self) -> "DummyObs":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def update(self, **kwargs: object) -> None:
            pass

    class DummyLangfuse:
        def get_prompt(self, *args: object, **kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                prompt="Enrich items cleanly.",
                config={"model": "gpt-4o-mini", "max_tokens": 512},
            )

        def start_as_current_observation(self, **kwargs: object) -> DummyObs:
            return DummyObs()

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        nonlocal calls
        calls += 1
        captured_messages.append(kwargs["messages"])
        content = json.dumps(
            {
                "items": [
                    {
                        "id": "01-part.md",
                        "title": "Q1 Revenue Overview",
                        "description": "Summarizes regional revenue breakdown.",
                        "slug": "q1-revenue-overview",
                    }
                ]
                if calls == 1
                else [
                    {
                        "id": "01-part.md",
                        "title": "Q1 Revenue Overview",
                        "description": "Summarizes regional revenue breakdown.",
                        "slug": "q1-revenue-overview",
                    },
                    {
                        "id": "images/01-img.png",
                        "title": "Margin Trend Chart",
                        "description": "Line graph of operating margin by quarter.",
                        "slug": "margin-trend-chart",
                    },
                ]
            }
        )

        def _msg_dump(**_k: object) -> dict[str, object]:
            return {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_{calls}",
                        "type": "function",
                        "function": {"name": "BatchEnrichment", "arguments": content},
                    }
                ],
            }

        def _choice_dump(**_k: object) -> dict[str, object]:
            return {"message": _msg_dump(), "finish_reason": "tool_calls", "index": 0}

        tool_call = SimpleNamespace(
            id=f"call_{calls}",
            type="function",
            function=SimpleNamespace(name="BatchEnrichment", arguments=content),
        )
        msg = SimpleNamespace(
            role="assistant",
            content=None,
            tool_calls=[tool_call],
            model_dump=_msg_dump,
        )
        choice = SimpleNamespace(
            finish_reason="tool_calls",
            index=0,
            message=msg,
            model_dump=_choice_dump,
        )
        return SimpleNamespace(
            id=f"resp_{calls}",
            choices=[choice],
            usage=None,
            _hidden_params={"response_cost": 0.001},
        )

    def _get_langfuse() -> DummyLangfuse:
        return DummyLangfuse()

    def _propagate(**_kw: object) -> DummyObs:
        return DummyObs()

    monkeypatch.setattr("letfs_ingest.providers.get_client", _get_langfuse)
    monkeypatch.setattr("letfs_ingest.providers.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("letfs_ingest.providers.propagate_attributes", _propagate)

    ai = Models(config)
    result = await ai.describe_batch(
        [
            EnrichItem(
                id="01-part.md", media_type="text/markdown", text_sample="# Revenue"
            ),
            EnrichItem(
                id="images/01-img.png", media_type="image/png", image_b64="AQID"
            ),
        ]
    )
    assert calls == 2  # Missing ID triggered automatic instructor retry
    assert set(result) == {"01-part.md", "images/01-img.png"}
    user_parts = captured_messages[0][1]["content"]
    assert user_parts[0] == {
        "type": "text",
        "text": '--- ARTIFACT id="01-part.md" (text/markdown) ---\n# Revenue',
    }
    assert user_parts[1] == {
        "type": "text",
        "text": '--- ARTIFACT id="images/01-img.png" (image/png) ---',
    }
    assert user_parts[2]["type"] == "image_url"
    assert user_parts[2]["image_url"]["url"].startswith("data:image/jpeg;base64,")


async def test_complete_retries_transient_errors(
    monkeypatch: pytest.MonkeyPatch, config: Config
) -> None:
    from litellm.exceptions import ServiceUnavailableError

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    attempts = 0

    class DummyObs:
        def __enter__(self) -> "DummyObs":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def update(self, **kwargs: object) -> None:
            pass

    async def no_sleep(_: float) -> None:
        return None

    async def fake_acompletion(**kwargs: object) -> SimpleNamespace:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ServiceUnavailableError(
                message="overloaded", llm_provider="openai", model="gpt"
            )
        choice = SimpleNamespace(model_dump=lambda: {"message": {"content": "ok"}})
        return SimpleNamespace(
            id="ok",
            choices=[choice],
            usage=None,
            _hidden_params={},
        )

    class DummyLangfuse:
        def start_as_current_observation(self, **_k: object) -> DummyObs:
            return DummyObs()

    monkeypatch.setattr("letfs_ingest.providers.asyncio.sleep", no_sleep)
    monkeypatch.setattr("letfs_ingest.providers.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("letfs_ingest.providers.get_client", lambda: DummyLangfuse())

    ai = Models(config)
    resp = await ai.complete(model="gpt-4o-mini", messages=[])
    assert attempts == 3
    assert resp.id == "ok"
