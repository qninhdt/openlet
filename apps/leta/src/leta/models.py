import asyncio
from time import monotonic

import httpx
from openlet_sdk.config import ReasoningEffort
from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    access_groups: list[str] = Field(default_factory=list)
    max_input_tokens: int | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    supported_reasoning_efforts: list[ReasoningEffort] | None = None


class Deployment(BaseModel):
    model_name: str
    model_info: ModelInfo


class ModelList(BaseModel):
    data: list[Deployment]


class Model(BaseModel):
    model_id: str
    reasoning_efforts: list[ReasoningEffort]
    context_window_tokens: int
    max_output_tokens: int


class Models:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self.items: dict[str, Model] = {}
        self.expires = 0.0
        self.lock = asyncio.Lock()

    async def catalog(self) -> dict[str, Model]:
        if monotonic() < self.expires:
            return self.items
        async with self.lock:
            if monotonic() < self.expires:
                return self.items
            response = await self.client.get("/model/info")
            response.raise_for_status()
            groups: dict[str, Model] = {}
            for deployment in ModelList.model_validate(response.json()).data:
                info = deployment.model_info
                if "leta" not in info.access_groups:
                    continue
                if info.max_input_tokens is None or info.max_output_tokens is None:
                    raise ValueError(
                        f"gateway limits missing for {deployment.model_name}"
                    )
                item = Model(
                    model_id=deployment.model_name,
                    reasoning_efforts=list(
                        dict.fromkeys([None, *(info.supported_reasoning_efforts or [])])
                    ),
                    context_window_tokens=info.max_input_tokens,
                    max_output_tokens=info.max_output_tokens,
                )
                if existing := groups.get(item.model_id):
                    item.context_window_tokens = min(
                        item.context_window_tokens, existing.context_window_tokens
                    )
                    item.max_output_tokens = min(
                        item.max_output_tokens, existing.max_output_tokens
                    )
                    item.reasoning_efforts = [
                        effort
                        for effort in item.reasoning_efforts
                        if effort in existing.reasoning_efforts
                    ]
                groups[item.model_id] = item
            self.items, self.expires = groups, monotonic() + 60
            return groups

    async def get(self, model_id: str, effort: ReasoningEffort) -> Model:
        item = (await self.catalog()).get(model_id)
        if item is None:
            raise ValueError("unknown model")
        if effort not in item.reasoning_efforts:
            raise ValueError("unsupported reasoning effort for model")
        return item
