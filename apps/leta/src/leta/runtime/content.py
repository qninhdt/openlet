"""Centralized typed helpers for LangChain message content blocks and ToolMessage artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, TypedDict

from langchain_core.messages import ToolMessage
from openlet_sdk.types import is_mapping, is_object_sequence, is_str_mapping
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Mapping

    from langchain_core.messages import AIMessageChunk, BaseMessage
    from openlet_sdk.config import JSON


class ToolArtifactMeta(BaseModel):
    """Typed runtime control fields extracted from a ToolMessage artifact."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    truncated: bool = False
    output_path: str | None = None
    end_turn: bool = False
    path: str = ""
    pre_truncated: bool = Field(default=False, alias="_pre_truncated")
    note: str | None = Field(default=None, alias="_note")


class TextContentBlock(TypedDict):
    """Typed multimodal text block."""

    type: Literal["text"]
    text: str


class ImageUrlPayload(TypedDict):
    """Nested URL payload inside an image content block."""

    url: str


class ImageUrlContentBlock(TypedDict):
    """Typed multimodal image_url block."""

    type: Literal["image_url"]
    image_url: ImageUrlPayload


type MessageContentBlock = TextContentBlock | ImageUrlContentBlock


def extract_text_from_content(content: object) -> str:
    """Extract displayable text from a LangChain message content field."""
    if isinstance(content, str):
        return content
    if not is_object_sequence(content):
        return ""
    parts: list[str] = []
    for blk in content:
        if isinstance(blk, str):
            parts.append(blk)
        elif is_str_mapping(blk):
            btype = blk.get("type")
            if btype == "text":
                parts.append(str(blk.get("text", "")))
            elif btype == "image_url":
                parts.append("[inline image attached]")
    return "\n".join(parts)


def extract_chunk_reasoning_delta(chunk: AIMessageChunk) -> str:
    """Extract reasoning/thinking text delta from a streaming AIMessageChunk."""
    parts: list[str] = []
    kw = chunk.additional_kwargs
    for key in ("reasoning_content", "reasoning"):
        val = kw.get(key)
        if isinstance(val, str) and val:
            parts.append(val)
    if isinstance(chunk.content, list):
        for blk in chunk.content:
            if is_str_mapping(blk) and blk.get("type") in ("thinking", "reasoning"):
                txt = blk.get("thinking") or blk.get("text")
                if isinstance(txt, str) and txt:
                    parts.append(txt)
    return "".join(parts)


def extract_chunk_text_delta(chunk: AIMessageChunk) -> str:
    """Extract visible text delta from a streaming AIMessageChunk."""
    if isinstance(chunk.content, str):
        return chunk.content
    parts: list[str] = []
    for blk in chunk.content:
        if isinstance(blk, str):
            parts.append(blk)
        elif is_str_mapping(blk) and blk.get("type") == "text":
            txt = blk.get("text")
            if isinstance(txt, str):
                parts.append(txt)
    return "".join(parts)


def image_block_data_url_bytes(block: object) -> int:
    """Return byte length of an inline data:image/... block, or 0 if not an inline image."""
    if not is_str_mapping(block) or block.get("type") != "image_url":
        return 0
    img = block.get("image_url")
    if is_str_mapping(img):
        url = img.get("url", "")
        if isinstance(url, str) and url.startswith("data:image/"):
            return len(url)
    return 0


def message_artifact_dict(msg: BaseMessage) -> dict[str, JSON]:
    """Safely extract a ToolMessage's artifact mapping (empty dict if absent/non-mapping)."""
    if not isinstance(msg, ToolMessage):
        return {}
    raw: object = msg.artifact
    if not is_mapping(raw):
        return {}
    return _coerce_json_dict(raw)


def parse_tool_artifact(msg: BaseMessage) -> ToolArtifactMeta:
    """Parse typed runtime control metadata from a ToolMessage artifact."""
    data = message_artifact_dict(msg)
    return ToolArtifactMeta.model_validate(data) if data else ToolArtifactMeta()


def _coerce_json_value(value: object) -> JSON:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if is_mapping(value):
        return {str(k): _coerce_json_value(v) for k, v in value.items()}
    if is_object_sequence(value):
        return [_coerce_json_value(v) for v in value]
    return str(value)


def _coerce_json_dict(raw: Mapping[object, object]) -> dict[str, JSON]:
    return {str(k): _coerce_json_value(v) for k, v in raw.items()}
