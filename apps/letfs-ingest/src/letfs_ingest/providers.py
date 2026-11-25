import asyncio
import base64
import csv
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO, StringIO
from typing import Any, TypedDict, cast

import instructor
import litellm
from langfuse import get_client, propagate_attributes
from litellm.exceptions import (
    APIConnectionError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)
from litellm.types.utils import EmbeddingResponse, ModelResponse, Usage  # pyright: ignore[reportMissingTypeStubs]
from openai.types.chat import ChatCompletionContentPartParam
from openlet_sdk.config import Config, EnrichmentSettings, secret
from openlet_sdk.inference import InferenceSettings, response_cost, usage_details
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from .telemetry import retry_transient

BATCH_CHAR_BUDGET = 36_000
MAX_ITEMS_PER_BATCH = 20
MAX_IMAGES_PER_BATCH = 6
_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    ServiceUnavailableError,
    RateLimitError,
    APIConnectionError,
    Timeout,
    InternalServerError,
    TimeoutError,
    OSError,
)


def _is_transient_llm_error(exc: BaseException) -> bool:
    return isinstance(exc, _TRANSIENT_ERRORS)


class ArtifactEnrichment(BaseModel):
    """Structured enrichment metadata with 2x Pydantic hard caps above prompt soft caps."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    # Prompt soft cap: 64 chars; system hard cap (2x): 128 chars.
    title: str = Field(min_length=1, max_length=128)
    # Prompt soft cap: 256 chars; system hard cap (2x): 512 chars.
    description: str = Field(min_length=1, max_length=512)
    slug: str | None = Field(default=None, min_length=1, max_length=64)


class BatchEnrichment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ArtifactEnrichment]

    @model_validator(mode="after")
    def validate_expected_ids(self, info: ValidationInfo) -> "BatchEnrichment":
        ctx: object = info.context
        if not isinstance(ctx, dict):
            return self
        ctx_map = cast(dict[object, object], ctx)
        expected = ctx_map.get("expected_ids")
        if expected is None:
            return self
        expected_set = set(cast(Sequence[str], expected))
        got_ids = [item.id for item in self.items]
        if len(got_ids) != len(set(got_ids)):
            raise ValueError("duplicate artifact IDs returned in enrichment batch")
        missing = expected_set - set(got_ids)
        extra = set(got_ids) - expected_set
        if missing or extra:
            raise ValueError(
                f"enrichment IDs mismatch (missing={sorted(missing)}, extra={sorted(extra)})"
            )
        return self


@dataclass(frozen=True)
class EnrichItem:
    id: str
    media_type: str
    text_sample: str | None = None
    image_b64: str | None = None

    def estimated_chars(self) -> int:
        if self.image_b64 is not None:
            return 1_500
        return len(self.id) + len(self.media_type) + len(self.text_sample or "") + 40


def sample_text(text: str, characters: int) -> str:
    if characters <= 0 or len(text) <= characters:
        return text
    marker = "\n...\n"
    usable = max(60, characters - 2 * len(marker))
    head = int(usable * 0.40)
    mid = int(usable * 0.30)
    tail = usable - head - mid
    mid_start = max(head, (len(text) - mid) // 2)
    return (
        text[:head].rstrip()
        + marker
        + text[mid_start : mid_start + mid].strip()
        + marker
        + text[-tail:].lstrip()
    )[:characters]


def sample_csv(text: str, characters: int) -> str:
    rows = list(csv.reader(StringIO(text)))
    if not rows:
        return sample_text(text, characters)
    total_rows = len(rows)
    if len(text) <= characters:
        return f"{text.rstrip()}\nTotal rows: {total_rows}"

    header = rows[:3]
    tail = rows[-2:] if total_rows > 5 else []
    mid_end = total_rows - len(tail)
    sampled_mid: list[list[str]] = []
    if mid_end > 3:
        pool = rows[3:mid_end]
        step = max(1, len(pool) // 5)
        sampled_mid = [pool[i] for i in range(0, len(pool), step)][:5]

    buf = StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerows(header)
    if sampled_mid:
        writer.writerow(["..."])
        writer.writerows(sampled_mid)
    if tail:
        writer.writerow(["..."])
        writer.writerows(tail)
    rendered = f"{buf.getvalue().rstrip()}\nTotal rows: {total_rows}"
    if len(rendered) > characters:
        return sample_text(rendered, characters)
    return rendered


def evidence(text: str, media_type: str, characters: int) -> str:
    if media_type == "text/csv":
        return sample_csv(text, characters)
    return sample_text(text, characters)


def adaptive_item_budget(
    item_count: int,
    max_input_characters: int,
    char_budget: int = BATCH_CHAR_BUDGET,
) -> int:
    effective = max(1, min(item_count, MAX_ITEMS_PER_BATCH))
    per_item = char_budget // effective
    return min(max_input_characters, max(1_500, per_item))


def pack_batches(
    items: Sequence[EnrichItem],
    char_budget: int = BATCH_CHAR_BUDGET,
    max_items: int = MAX_ITEMS_PER_BATCH,
    max_images: int = MAX_IMAGES_PER_BATCH,
) -> list[list[EnrichItem]]:
    batches: list[list[EnrichItem]] = []
    cur: list[EnrichItem] = []
    cur_chars = 0
    cur_images = 0
    for item in items:
        item_chars = item.estimated_chars()
        is_image = item.image_b64 is not None
        if cur and (
            len(cur) >= max_items
            or (cur_chars + item_chars > char_budget)
            or (is_image and cur_images >= max_images)
        ):
            batches.append(cur)
            cur = []
            cur_chars = 0
            cur_images = 0
        cur.append(item)
        cur_chars += item_chars
        if is_image:
            cur_images += 1
    if cur:
        batches.append(cur)
    return batches


def vision(data: bytes, settings: EnrichmentSettings) -> str:
    with Image.open(BytesIO(data)) as image:
        if image.width * image.height > settings["max_image_pixels"]:
            raise ValueError("image exceeds max_image_pixels enrichment limit")
        side = settings["image_max_side"]
        converted = image.convert("RGBA") if image.mode != "RGBA" else image.copy()
        if max(converted.size) > side:
            converted.thumbnail((side, side))
        canvas = Image.new("RGB", converted.size, (255, 255, 255))
        canvas.paste(converted, mask=converted.split()[-1])
        buf = BytesIO()
        canvas.save(
            buf,
            format="JPEG",
            quality=settings["image_jpeg_quality"],
            optimize=True,
        )
        return base64.b64encode(buf.getvalue()).decode("ascii")


class ConnectionParameters(TypedDict):
    api_base: str
    api_key: str
    custom_llm_provider: str
    timeout: int
    max_retries: int


class EmbeddingData(TypedDict):
    index: int
    embedding: list[float]


class Models:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.langfuse = get_client()
        gateway = config["models"]["gateway"]
        self.connection: ConnectionParameters = {
            "api_base": gateway["base_url"],
            "api_key": secret(gateway["api_key"]),
            "custom_llm_provider": "litellm_proxy",
            "timeout": gateway["timeout_seconds"],
            "max_retries": 0,
        }
        modes = {
            "tools": instructor.Mode.TOOLS,
            "json_schema": instructor.Mode.JSON_SCHEMA,
            "text": instructor.Mode.MD_JSON,
        }
        self.client = instructor.from_litellm(
            self.complete,
            mode=modes[config["models"]["enrichment"]["output_mode"]],
        )
        lf = config.get("langfuse")
        self.prompt_label = lf["prompt_label"] if lf else "production"

    async def describe_batch(
        self, items: Sequence[EnrichItem]
    ) -> dict[str, ArtifactEnrichment]:
        if not items:
            return {}
        prompt = await asyncio.to_thread(
            self.langfuse.get_prompt,
            "letfs/enrichment",
            label=self.prompt_label,
            type="text",
            cache_ttl_seconds=60,
        )
        cfg_obj: object = getattr(prompt, "config", None) or {}
        inference = InferenceSettings.model_validate(cfg_obj)
        system_prompt = str(getattr(prompt, "prompt", ""))

        parts: list[ChatCompletionContentPartParam] = []
        for item in items:
            header = f'--- ARTIFACT id="{item.id}" ({item.media_type}) ---'
            if item.image_b64 is not None:
                parts.append({"type": "text", "text": header})
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{item.image_b64}",
                            "detail": "auto",
                        },
                    }
                )
            else:
                parts.append(
                    {"type": "text", "text": f"{header}\n{item.text_sample or ''}"}
                )

        messages: list[dict[str, object]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": parts},
        ]
        expected_ids = [item.id for item in items]
        batch_summary = f"{len(expected_ids)}: " + ", ".join(expected_ids)
        if len(batch_summary) > 150:
            batch_summary = batch_summary[:147] + "..."

        with propagate_attributes(metadata={"blob_items": batch_summary}):
            create_with_completion: Any = self.client.create_with_completion
            result = await create_with_completion(
                response_model=BatchEnrichment,
                messages=messages,
                context={"expected_ids": expected_ids},
                max_retries=2,
                model=inference.model,
                api_base=self.connection["api_base"],
                api_key=self.connection["api_key"],
                custom_llm_provider=self.connection["custom_llm_provider"],
                timeout=self.connection["timeout"],
                **inference.parameters(),
            )
            parsed = cast(BatchEnrichment, result[0])
        return {entry.id: entry for entry in parsed.items}

    async def complete(self, **kwargs: object) -> ModelResponse:
        with self.langfuse.start_as_current_observation(
            name="enrichment",
            as_type="generation",
            model=str(kwargs["model"]),
            input=kwargs.get("messages"),
        ) as observation:
            response = cast(
                ModelResponse,
                await retry_transient(
                    lambda: litellm.acompletion(**kwargs),
                    should_retry=_is_transient_llm_error,
                    sleep=asyncio.sleep,
                ),
            )
            observation.update(
                output=response.choices[0].model_dump(),
                usage_details=usage_details(
                    cast(Usage | None, getattr(response, "usage", None))
                ),
                cost_details=response_cost(
                    cast(
                        dict[str, object], getattr(response, "_hidden_params", {})
                    ).get("response_cost")
                ),
            )
            return response

    async def embed(self, texts: list[str]) -> list[list[float]]:
        model = self.config["models"]["embedding"]
        with propagate_attributes():
            with self.langfuse.start_as_current_observation(
                name="embedding",
                as_type="embedding",
                model=model["model"],
                input=texts,
            ) as observation:
                response: EmbeddingResponse = await retry_transient(
                    lambda: litellm.aembedding(
                        model=model["model"],
                        input=texts,
                        dimensions=model["dimensions"],
                        encoding_format="float",
                        **self.connection,
                    ),
                    should_retry=_is_transient_llm_error,
                    sleep=asyncio.sleep,
                )
                observation.update(
                    usage_details=usage_details(response.usage),
                    cost_details=response_cost(
                        cast(
                            dict[str, object], getattr(response, "_hidden_params", {})
                        ).get("response_cost")
                    ),
                )
        ordered = sorted(
            cast(list[EmbeddingData], getattr(response, "data")),
            key=lambda item: item["index"],
        )
        return [item["embedding"] for item in ordered]
