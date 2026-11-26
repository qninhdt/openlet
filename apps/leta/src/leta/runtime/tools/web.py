from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Literal, cast
from urllib.parse import urljoin, urlparse

import html_to_markdown as h2m
import httpx
from langchain_core.tools import BaseTool, ToolException
from langgraph.prebuilt import ToolRuntime
from openlet_sdk.config import JSON
from pydantic import Field
from tinyfish import AsyncTinyFish, FetchFormat, SDKError

from ..state import AgentState, RuntimeContext
from .base import ToolArgs, ToolResult, make_tool


def _is_public_ip(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return bool(
        addr.is_global
        and not addr.is_private
        and not addr.is_loopback
        and not addr.is_link_local
        and not addr.is_multicast
        and not addr.is_reserved
        and not addr.is_unspecified
    )


def normalize_public_url(url: str) -> str:
    cleaned = url.strip()
    if not cleaned:
        raise ToolException("URL cannot be empty.")
    if "://" not in cleaned and "." in cleaned.split("/", 1)[0]:
        cleaned = "https://" + cleaned
    return cleaned


async def assert_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolException(
            f"Unsupported URL scheme {parsed.scheme!r}; only http:// and https:// URLs are allowed."
        )
    host = (parsed.hostname or "").strip().lower()
    if (
        not host
        or host in ("localhost", "localhost.localdomain")
        or host.endswith((".local", ".internal"))
    ):
        raise ToolException(f"Blocked private or internal host: {host}")
    try:
        ipaddress.ip_address(host)
        if not _is_public_ip(host):
            raise ToolException(f"Blocked non-public IP address: {host}")
        return
    except ValueError:
        pass
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(
            host,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ToolException(f"Could not resolve host {host!r}: {exc}") from None
    if not infos:
        raise ToolException(f"Could not resolve host: {host}")
    for _, _, _, _, sockaddr in infos:
        ip = str(sockaddr[0])
        if not _is_public_ip(ip):
            raise ToolException(f"Host {host} resolved to non-public IP {ip}")


_H2M_PREPROCESSING = h2m.PreprocessingOptions(
    enabled=True, remove_navigation=True, remove_forms=True
)
_H2M_MARKDOWN_OPTIONS = h2m.ConversionOptions(
    output_format=h2m.OutputFormat.MARKDOWN, preprocessing=_H2M_PREPROCESSING
)
_H2M_PLAIN_OPTIONS = h2m.ConversionOptions(
    output_format=h2m.OutputFormat.PLAIN, preprocessing=_H2M_PREPROCESSING
)


def html_to_markdown(html: str) -> str:
    return (h2m.convert(html, _H2M_MARKDOWN_OPTIONS).content or "").strip()


def html_to_text(html: str) -> str:
    return (h2m.convert(html, _H2M_PLAIN_OPTIONS).content or "").strip()


def _looks_like_empty_js_shell(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 120:
        return True
    low = stripped.lower()
    return any(
        marker in low
        for marker in (
            "enable javascript to run this app",
            "please enable javascript",
            "just a moment...",
            "checking your browser",
        )
    )


class WebFetchArgs(ToolArgs):
    url: str = Field(
        min_length=1,
        description="Public URL (https:// auto-prepended if omitted).",
    )
    format: Literal["markdown", "text", "html"] = "markdown"
    timeout: int | None = Field(
        default=None,
        ge=1,
        le=120,
        description="Timeout in seconds (default 30).",
    )


class WebSearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=500)


_CONTENT_TYPES: dict[Literal["markdown", "text", "html"], str] = {
    "markdown": "text/markdown",
    "text": "text/plain",
    "html": "text/html",
}


async def _tinyfish_fetch(
    api_key: str,
    url: str,
    *,
    norm_url: str,
    fmt: Literal["markdown", "text", "html"],
    timeout: float,
) -> ToolResult:
    tf_format: FetchFormat = "html" if fmt in ("html", "text") else "markdown"
    timeout_ms = max(1, min(int(timeout * 1000), 110_000))
    try:
        async with AsyncTinyFish(api_key=api_key, timeout=timeout) as client:
            resp = await client.fetch.get_contents(
                urls=[url],
                format=tf_format,
                per_url_timeout_ms=timeout_ms,
            )
    except SDKError as exc:
        raise ToolException(f"Web fetch failed for {url}: {exc}") from None

    if not resp.results:
        detail = resp.errors[0].error if resp.errors else "no content returned"
        raise ToolException(f"Web fetch failed for {url}: {detail}")

    item = resp.results[0]
    body = item.text or ""
    if fmt == "text" and body:
        body = html_to_text(body)
    final_url = item.final_url or item.url or url
    return (
        body or "(empty response)",
        {
            "url": norm_url,
            "final_url": final_url,
            "title": item.title or "",
            "published_at": item.published_date or "",
            "format": fmt,
            "content_type": _CONTENT_TYPES[fmt],
            "source": "tinyfish",
        },
    )


async def _direct_fetch(
    url: str, *, fmt: str, timeout: float, max_redirects: int, max_bytes: int
) -> tuple[str, str, str, int]:
    cur_url = url
    headers = {
        "User-Agent": "OpenletLeta/2.0 (+https://openlet.ai)",
        "Accept": "text/markdown, text/html;q=0.9, text/plain;q=0.8, */*;q=0.5",
    }
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=timeout, headers=headers
    ) as client:
        for _ in range(max_redirects + 1):
            await assert_public_url(cur_url)
            try:
                async with client.stream("GET", cur_url) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        loc = resp.headers.get("location")
                        if not loc:
                            break
                        cur_url = urljoin(cur_url, loc)
                        continue
                    status_code = resp.status_code
                    ctype = (
                        resp.headers.get("content-type", "text/plain")
                        .split(";")[0]
                        .strip()
                        .lower()
                    )
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > max_bytes:
                            break
                    body = buf.decode("utf-8", errors="replace")
                    if ctype == "text/html":
                        if fmt == "markdown":
                            body = html_to_markdown(body)
                        elif fmt == "text":
                            body = html_to_text(body)
                    return body, cur_url, ctype, status_code
            except httpx.TimeoutException:
                raise ToolException(
                    f"Request timed out after {int(timeout)}s fetching {cur_url}."
                ) from None
            except httpx.HTTPError as exc:
                raise ToolException(
                    f"Network error fetching {cur_url}: {exc}"
                ) from None
    raise ToolException(f"Exceeded maximum redirects ({max_redirects}) fetching {url}.")


async def handle_webfetch(
    url: str,
    format: Literal["markdown", "text", "html"] = "markdown",
    timeout: int | None = None,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    rt = runtime.context
    web_cfg = rt.services.settings.web
    api_key = rt.services.settings.web_search_api_key
    norm_url = normalize_public_url(url)
    eff_timeout = float(
        min(
            timeout or web_cfg.fetch_default_timeout_seconds,
            web_cfg.fetch_max_timeout_seconds,
        )
    )

    if web_cfg.fetch_mode == "tinyfish":
        if not api_key:
            raise ToolException(
                "Web fetch provider is unavailable in this environment."
            )
        await assert_public_url(norm_url)
        return await _tinyfish_fetch(
            api_key,
            norm_url,
            norm_url=norm_url,
            fmt=format,
            timeout=eff_timeout,
        )

    body, final_url, ctype, status_code = await _direct_fetch(
        norm_url,
        fmt=format,
        timeout=eff_timeout,
        max_redirects=web_cfg.fetch_max_redirects,
        max_bytes=web_cfg.fetch_max_response_bytes,
    )
    if (
        web_cfg.fetch_mode == "direct_with_fallback"
        and api_key
        and (status_code == 403 or _looks_like_empty_js_shell(body))
    ):
        return await _tinyfish_fetch(
            api_key,
            final_url,
            norm_url=norm_url,
            fmt=format,
            timeout=eff_timeout,
        )
    if status_code >= 400:
        hint = (
            " Try websearch to locate an alternate public source or verify the URL."
            if status_code in (401, 403, 404, 410)
            else ""
        )
        raise ToolException(f"HTTP {status_code} fetching {final_url}.{hint}")
    return (
        body or "(empty response)",
        {
            "url": norm_url,
            "final_url": final_url,
            "format": format,
            "content_type": ctype,
            "source": "direct",
        },
    )


async def handle_websearch(
    query: str,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    rt = runtime.context
    web_cfg = rt.services.settings.web
    api_key = rt.services.settings.web_search_api_key
    if not api_key:
        raise ToolException("Web search is unavailable in this environment.")

    try:
        async with AsyncTinyFish(
            api_key=api_key,
            timeout=float(web_cfg.fetch_default_timeout_seconds),
        ) as client:
            resp = await client.search.query(query=query)
    except SDKError as exc:
        raise ToolException(f"Web search failed: {exc}") from None

    results: list[dict[str, JSON]] = []
    md_blocks: list[str] = []
    for item in resp.results[: web_cfg.search_max_results]:
        title = item.title
        url = item.url
        snippet = item.snippet
        published = item.date or ""
        results.append(
            {
                "title": title,
                "url": url,
                "published_at": published,
                "snippet": snippet,
            }
        )
        block = f"## [{title or url}]({url})"
        if published:
            block += f"\nPublished: {published}"
        if snippet:
            block += f"\n\n{snippet}"
        md_blocks.append(block)
    return (
        "\n\n".join(md_blocks) if md_blocks else "No web search results found.",
        {"provider": "tinyfish", "results": cast(JSON, results)},
    )


def build_web_tools() -> list[BaseTool]:
    return [
        make_tool(
            name="websearch",
            description="Search the public web; returns ranked Markdown snippets and URLs. Follow up with webfetch for full pages.",
            args_schema=WebSearchArgs,
            coroutine=handle_websearch,
        ),
        make_tool(
            name="webfetch",
            description="Fetch a public HTTP/HTTPS URL (read-only; large pages spill to /home/.tool-output/).",
            args_schema=WebFetchArgs,
            coroutine=handle_webfetch,
        ),
    ]
