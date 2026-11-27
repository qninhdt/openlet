"""Image media-type detection, optimization, and history image hysteresis pruning."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image

from leta.runtime.content import image_block_data_url_bytes, parse_tool_artifact

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from leta.config import MediaConfig


@dataclass(frozen=True, slots=True)
class PreparedImage:
    """Optimized inline image payload ready for multimodal model messages."""

    media_type: str
    data_url: str
    base64_bytes: int
    width: int
    height: int


def detect_media_type(data: bytes) -> str | None:
    """Detect common image or PDF MIME types from magic bytes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def _has_significant_transparency(img: Image.Image) -> bool:
    if img.mode not in ("RGBA", "LA", "PA") and "transparency" not in img.info:
        return False
    alpha_hist = img.convert("RGBA").getchannel("A").histogram()
    total = sum(alpha_hist)
    return total > 0 and (sum(alpha_hist[:250]) / total) > 0.05


def _encode_jpeg(img: Image.Image, quality: int) -> bytes:
    buf = BytesIO()
    rgb = img.convert("RGB")
    rgb.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _encode_png(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _b64_len(raw_len: int) -> int:
    return ((raw_len + 2) // 3) * 4


def _prepared_image(
    data: bytes, *, media_type: str, width: int, height: int
) -> PreparedImage:
    b64 = base64.b64encode(data).decode("ascii")
    return PreparedImage(
        media_type=media_type,
        data_url=f"data:{media_type};base64,{b64}",
        base64_bytes=len(b64),
        width=width,
        height=height,
    )


def _resize_to_fit(img: Image.Image, cfg: MediaConfig) -> Image.Image:
    w, h = img.size
    if w <= cfg.image_max_width and h <= cfg.image_max_height:
        return img
    scale = min(cfg.image_max_width / max(1, w), cfg.image_max_height / max(1, h))
    nw = max(1, round(w * scale))
    nh = max(1, round(h * scale))
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


def _compress_under_budget(
    img: Image.Image, cfg: MediaConfig, *, transparent: bool
) -> PreparedImage | None:
    cur = _resize_to_fit(img, cfg)
    qualities = cfg.jpeg_qualities or (80, 70, 55, 40)
    for _ in range(8):
        if transparent:
            png_bytes = _encode_png(cur)
            if _b64_len(len(png_bytes)) <= cfg.image_max_base64_bytes:
                return _prepared_image(
                    png_bytes,
                    media_type="image/png",
                    width=cur.size[0],
                    height=cur.size[1],
                )
        for q in qualities:
            jpg_bytes = _encode_jpeg(cur, q)
            if _b64_len(len(jpg_bytes)) <= cfg.image_max_base64_bytes:
                return _prepared_image(
                    jpg_bytes,
                    media_type="image/jpeg",
                    width=cur.size[0],
                    height=cur.size[1],
                )
        nw = max(1, int(cur.size[0] * 0.75))
        nh = max(1, int(cur.size[1] * 0.75))
        if (nw, nh) == cur.size:
            break
        cur = cur.resize((nw, nh), Image.Resampling.LANCZOS)
    return None


def optimize_image_bytes(data: bytes, cfg: MediaConfig) -> PreparedImage | str:
    """Optimize an image using OpenCode v2 rules (2000x2000, 5 MiB base64 cap, smart PNG->JPEG)."""
    if len(data) > cfg.max_ingest_bytes:
        return (
            f"[Image exceeds maximum ingest size ({len(data)} bytes > "
            f"{cfg.max_ingest_bytes} bytes); omitted]"
        )
    detected = detect_media_type(data)
    if detected is None or not detected.startswith("image/"):
        return "[File is not a supported image format; omitted]"

    try:
        with Image.open(BytesIO(data)) as opened:
            opened.load()
            img = opened.copy()
    except OSError, ValueError, EOFError, SyntaxError, Image.DecompressionBombError:
        return "[Image could not be decoded; omitted]"

    w, h = img.size
    orig_b64 = _b64_len(len(data))
    fits_dims = w <= cfg.image_max_width and h <= cfg.image_max_height
    fits_bytes = orig_b64 <= cfg.image_max_base64_bytes

    if not cfg.image_auto_resize:
        if not fits_bytes:
            return (
                "[Image exceeds base64 size limit and auto-resize is disabled; omitted]"
            )
        return _prepared_image(data, media_type=detected, width=w, height=h)

    is_small_png = detected == "image/png" and (
        orig_b64 <= cfg.png_passthrough_max_base64_bytes
        or (w * h) <= cfg.small_png_max_pixels
    )
    if fits_dims and fits_bytes and (detected != "image/png" or is_small_png):
        return _prepared_image(data, media_type=detected, width=w, height=h)

    transparent = _has_significant_transparency(img)
    if fits_dims and fits_bytes and detected == "image/png" and not transparent:
        jpg = _encode_jpeg(img, cfg.jpeg_qualities[0] if cfg.jpeg_qualities else 80)
        if len(jpg) < len(data):
            return _prepared_image(jpg, media_type="image/jpeg", width=w, height=h)
        return _prepared_image(data, media_type="image/png", width=w, height=h)

    compressed = _compress_under_budget(img, cfg, transparent=transparent)
    if compressed is not None:
        return compressed
    return "[Image could not be resized under base64 size limit; omitted]"


def bound_history_images(
    messages: list[BaseMessage], cfg: MediaConfig
) -> list[BaseMessage]:
    """Apply 25 MiB -> 15 MiB hysteresis pruning of oldest inline image blocks before model calls."""
    image_locs: list[tuple[int, int, int, str]] = []
    total = 0
    for mi, msg in enumerate(messages):
        content = msg.content
        if not isinstance(content, list):
            continue
        path_hint = parse_tool_artifact(msg).path
        for bi, block in enumerate(content):
            sz = image_block_data_url_bytes(block)
            if sz > 0:
                image_locs.append((mi, bi, sz, path_hint))
                total += sz

    if total <= cfg.history_image_bytes_trigger:
        return messages

    to_drop: dict[tuple[int, int], str] = {}
    remaining = total
    for mi, bi, sz, path_hint in image_locs:
        if remaining <= cfg.history_image_bytes_target:
            break
        to_drop[(mi, bi)] = path_hint
        remaining -= sz

    if not to_drop:
        return messages

    out: list[BaseMessage] = []
    for mi, msg in enumerate(messages):
        content = msg.content
        if not isinstance(content, list) or not any(
            (mi, bi) in to_drop for bi in range(len(content))
        ):
            out.append(msg)
            continue
        new_blocks: list[object] = []
        for bi, block in enumerate(content):
            if (mi, bi) in to_drop:
                hint = to_drop[(mi, bi)]
                notice = (
                    f"[Image omitted to save context; re-read {hint} if needed]"
                    if hint
                    else "[Image omitted to save context; re-read if needed]"
                )
                new_blocks.append({"type": "text", "text": notice})
            else:
                new_blocks.append(block)
        out.append(msg.model_copy(update={"content": new_blocks}))
    return out
