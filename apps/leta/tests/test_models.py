import asyncio

import httpx
import pytest
from leta.models import Models


async def test_gateway_catalog_is_cached_deduplicated_and_private() -> None:
    requests = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        info = {
            "access_groups": ["leta"],
            "max_input_tokens": 64000,
            "max_output_tokens": 8000,
            "supported_reasoning_efforts": ["low"],
        }
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "model_name": "chat",
                        "model_info": info,
                        "litellm_params": {"api_key": "private"},
                    },
                    {"model_name": "chat", "model_info": info},
                    {"model_name": "embed", "model_info": {"mode": "embedding"}},
                ]
            },
        )

    async with httpx.AsyncClient(
        base_url="http://gateway", transport=httpx.MockTransport(respond)
    ) as client:
        models = Models(client)
        first, second = await asyncio.gather(models.catalog(), models.catalog())
        assert list(first) == ["chat"] and first == second and requests == 1
        assert (await models.get("chat", "low")).reasoning_efforts == [None, "low"]
        with pytest.raises(ValueError, match="effort"):
            await models.get("chat", "high")
        models.expires = 0
        await models.catalog()
        assert requests == 2
