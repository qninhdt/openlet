import asyncio
import base64
import csv
import io
from enum import StrEnum
from itertools import islice
from typing import TypedDict, cast

import instructor
import litellm
from langfuse import get_client, propagate_attributes
from litellm.types.utils import EmbeddingResponse, ModelResponse, Usage  # pyright: ignore[reportMissingTypeStubs]  # LiteLLM does not ship py.typed.
from openai.types.chat import ChatCompletionContentPartParam
from openlet_sdk.config import Config, EnrichmentSettings, secret
from openlet_sdk.inference import InferenceSettings, response_cost, usage_details
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field


class SemanticType(StrEnum):
    DOCUMENT_RESEARCH_PAPER = "document:research_paper"
    DOCUMENT_REPORT = "document:report"
    DOCUMENT_ARTICLE = "document:article"
    DOCUMENT_BOOK = "document:book"
    DOCUMENT_MANUAL = "document:manual"
    DOCUMENT_CONTRACT = "document:contract"
    DOCUMENT_OTHER = "document:other"
    TEXT_CONTENT = "text:content"
    TEXT_SUMMARY = "text:summary"
    TEXT_NOTES = "text:notes"
    TEXT_OVERVIEW = "text:overview"
    TEXT_TRANSCRIPT = "text:transcript"
    TEXT_OTHER = "text:other"
    IMAGE_PHOTO = "image:photo"
    IMAGE_SCREENSHOT = "image:screenshot"
    IMAGE_CHART = "image:chart"
    IMAGE_DIAGRAM = "image:diagram"
    IMAGE_ILLUSTRATION = "image:illustration"
    IMAGE_OTHER = "image:other"
    TABLE_RECORDS = "table:records"
    TABLE_SUMMARY = "table:summary"
    TABLE_TIME_SERIES = "table:time_series"
    TABLE_OTHER = "table:other"
    SPREADSHEET_DATASET = "spreadsheet:dataset"
    SPREADSHEET_FINANCIAL = "spreadsheet:financial"
    SPREADSHEET_TRACKER = "spreadsheet:tracker"
    SPREADSHEET_OTHER = "spreadsheet:other"
    PRESENTATION_LECTURE = "presentation:lecture"
    PRESENTATION_PITCH = "presentation:pitch"
    PRESENTATION_REPORT = "presentation:report"
    PRESENTATION_OTHER = "presentation:other"
    CODE_SOURCE = "code:source"
    CODE_CONFIGURATION = "code:configuration"
    CODE_NOTEBOOK = "code:notebook"
    CODE_OTHER = "code:other"
    UNKNOWN = "other:unknown"


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=600)
    semantic_type: SemanticType
    context: str = Field(min_length=1, max_length=3000)


def sample(text: str, characters: int) -> str:
    if characters < 64:
        raise ValueError("evidence budget must be at least 64 characters")
    if len(text) <= characters:
        return text
    marker = "\n[omitted]\n"
    windows = min(8, characters // 64)
    width = (characters - len(marker) * (windows - 1)) // windows
    return marker.join(
        text[start : start + width]
        for start in (
            round(index * (len(text) - width) / (windows - 1))
            for index in range(windows)
        )
    )


def evidence(text: str, media: str, characters: int) -> str:
    if media == "text/csv":
        text = "\n".join(
            ", ".join(row) for row in islice(csv.reader(io.StringIO(text)), 9)
        )
    return sample(text, characters)


def vision(data: bytes, settings: EnrichmentSettings) -> str:
    with Image.open(io.BytesIO(data)) as image:
        if image.width * image.height > settings["max_image_pixels"]:
            raise ValueError("image exceeds pixel limit")
        image.thumbnail((settings["image_max_side"], settings["image_max_side"]))
        with io.BytesIO() as output:
            image.convert("RGB").save(
                output, format="JPEG", quality=settings["image_jpeg_quality"]
            )
            return "data:image/jpeg;base64," + base64.b64encode(
                output.getvalue()
            ).decode("ascii")


class ConnectionParameters(TypedDict):
    api_base: str
    api_key: str
    timeout: int
    num_retries: int


class EmbeddingData(TypedDict):
    index: int
    embedding: list[float]


class Models:
    def __init__(self, config: Config, prompt_label: str) -> None:
        self.settings = config["models"]
        self.langfuse = get_client()
        self.prompt_label = prompt_label
        gateway = self.settings["gateway"]
        self.connection: ConnectionParameters = {
            "api_base": gateway["base_url"],
            "api_key": secret(gateway["api_key"]),
            "timeout": gateway["timeout_seconds"],
            "num_retries": 0,
        }
        self.client = instructor.from_litellm(
            self.complete,
            async_client=True,
            mode={
                "tools": instructor.Mode.TOOLS,
                "json_schema": instructor.Mode.JSON_SCHEMA,
                "text": instructor.Mode.MD_JSON,
            }[self.settings["enrichment"]["output_mode"]],
        )
        self.slots = asyncio.Semaphore(
            config["services"]["letfs_ingest"]["io"]["model_concurrency"]
        )

    async def describe(
        self,
        name: str,
        text: str,
        media: str,
        children: str,
        image: bytes | None = None,
    ) -> Metadata:
        settings = self.settings["enrichment"]
        budget = settings["max_input_characters"]
        own = evidence(text, media, budget)
        content: list[ChatCompletionContentPartParam] = [
            {
                "type": "text",
                "text": sample(
                    f"Name: {name}\nMedia type: {media}\nContent:\n{own}\nChild summaries:\n{children}",
                    budget,
                ),
            }
        ]
        if image is not None:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": await asyncio.to_thread(vision, image, settings)
                    },
                }
            )
        prompt = await asyncio.to_thread(
            self.langfuse.get_prompt,
            "letfs/enrichment",
            label=self.prompt_label,
            type="text",
            cache_ttl_seconds=60,
        )
        defaults = InferenceSettings.model_validate(prompt.config)
        with propagate_attributes(prompt=prompt):
            return await self.client.chat.completions.create(
                model="litellm_proxy/" + defaults.model,
                response_model=Metadata,
                max_retries=1,
                **self.connection,
                **defaults.parameters(),
                messages=[
                    {"role": "system", "content": prompt.compile()},
                    {"role": "user", "content": content},
                ],
            )

    async def complete(self, **kwargs: object) -> ModelResponse:
        # Record each paid attempt before Instructor accumulates retry usage.
        model = str(kwargs["model"]).removeprefix("litellm_proxy/")
        with self.langfuse.start_as_current_observation(
            name="enrichment",
            as_type="generation",
            model=model,
            input=kwargs.get("messages"),
        ) as observation:
            response = cast(ModelResponse, await litellm.acompletion(**kwargs))
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
        model = self.settings["embedding"]
        async with self.slots:
            with self.langfuse.start_as_current_observation(
                name="embedding",
                as_type="embedding",
                model=model["model"],
                input=texts,
            ) as observation:
                response: EmbeddingResponse = await litellm.aembedding(
                    model="litellm_proxy/" + model["model"],
                    input=texts,
                    dimensions=model["dimensions"],
                    encoding_format="float",
                    **self.connection,
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
        if [item["index"] for item in ordered] != list(range(len(texts))):
            raise ValueError("embedding provider returned invalid indices")
        vectors = [item["embedding"] for item in ordered]
        if any(len(vector) != model["dimensions"] for vector in vectors):
            raise ValueError("embedding provider returned invalid dimensions")
        return vectors
