import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from ipaddress import ip_address
from typing import cast
from urllib.parse import urlsplit

import httpx
from openlet_sdk.config import JSON
from pydantic import BaseModel
from tinyfish import (
    APITimeoutError,
    AsyncTinyFish,
    AuthenticationError,
    PaymentRequiredError,
    RateLimitError,
    RequestTimeoutError,
    SDKError,
)
from tinyfish.fetch.types import FetchResponse


class WebClient(AsyncTinyFish):
    def _parse_response[T: BaseModel](
        self, response: httpx.Response, cast_to: type[T]
    ) -> T:
        if cast_to is not FetchResponse:
            return super()._parse_response(response, cast_to)
        data = cast(JSON, response.json())
        if isinstance(data, dict):
            results = data.get("results")
            if isinstance(results, list):
                for item in results:
                    # shortcut: SDK 0.11.0 expects text, remove when it accepts JSON objects.
                    if (
                        isinstance(item, dict)
                        and item.get("format") == "json"
                        and isinstance(item.get("text"), dict)
                    ):
                        item["text"] = json.dumps(
                            item["text"], ensure_ascii=False, separators=(",", ":")
                        )
        return cast_to.model_validate(data)


def public_url(value: str) -> str:
    if (
        len(value) > 4096
        or "\\" in value
        or any(ord(char) <= 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("Use a public HTTP or HTTPS URL.")
    try:
        url = urlsplit(value)
        host = url.hostname
        if url.scheme not in {"http", "https"} or not host or "@" in url.netloc:
            raise ValueError
        if url.port == 0:
            raise ValueError
        host = host.rstrip(".")
        try:
            address = ip_address(host)
        except ValueError:
            suffix = host.rsplit(".", 1)[-1]
            if (
                "." not in host
                or suffix
                in {
                    "localhost",
                    "local",
                    "internal",
                    "test",
                    "example",
                    "invalid",
                    "onion",
                }
                or not suffix[0:1].isalpha()
                or "%" in host
                or ":" in host
            ):
                raise ValueError from None
        else:
            if not address.is_global or address.is_multicast:
                raise ValueError
    except ValueError:
        raise ValueError("Use a public HTTP or HTTPS URL.") from None
    return value


@asynccontextmanager
async def web_request() -> AsyncGenerator[None]:
    try:
        async with asyncio.timeout(25):
            yield
    except APITimeoutError, RequestTimeoutError, TimeoutError:
        raise ValueError("The web request timed out.") from None
    except RateLimitError:
        raise ValueError("Web requests are rate limited. Try again later.") from None
    except PaymentRequiredError:
        raise ValueError("The web service has exhausted its quota.") from None
    except AuthenticationError:
        raise ValueError("Web service authentication failed.") from None
    except SDKError, ValueError:
        raise ValueError("The web service could not complete the request.") from None
