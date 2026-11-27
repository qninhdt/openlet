"""Image filtering, deduplication, and artifact persistence for parsed documents."""

from __future__ import annotations

import hashlib
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_MIN_DIMENSION = 48
_MICRO_ICON_SIDE = 96
_MICRO_ICON_MAX_AREA = 7_500
_SMALL_ICON_MIN_BYTES = 1_200
_SMALL_ICON_MAX_BYTES = 7_000
_SMALL_ICON_MAX_AREA = 45_000
_EXTREME_SHORT_SIDE = 80
_EXTREME_ASPECT_RATIO = 6.0
_MIN_GRAY_STDDEV = 3.0
_DECORATIVE_BLOCK_TYPES = frozenset({"PageHeader", "PageFooter", "Footnote"})


def image_digest(data: bytes) -> bytes:
    """Return the SHA-256 digest of raw image bytes."""
    return hashlib.sha256(data).digest()


def ignored_repeated_digests(
    counts: Mapping[bytes, int], min_count: int = 3
) -> set[bytes]:
    """Return image digests that repeat at least ``min_count`` times."""
    return {digest for digest, count in counts.items() if count >= min_count}


def normalize_image(
    data: bytes, block_type: str | None = None
) -> tuple[bool, bytes, str, str]:
    """Apply 4-layer structural image quality filtering cleanly.

    Returns (keep, output_bytes, media_type, extension).
    """
    if block_type in _DECORATIVE_BLOCK_TYPES:
        return False, b"", "", ""
    try:
        with Image.open(BytesIO(data)) as raw:
            im = ImageOps.exif_transpose(raw)
            if im.mode in {"P", "PA"} or (
                im.mode != "RGBA" and "transparency" in im.info
            ):
                im = im.convert("RGBA")
            w, h = im.size
            if w < _MIN_DIMENSION or h < _MIN_DIMENSION:
                return False, b"", "", ""
            short_side, long_side = min(w, h), max(w, h)
            if long_side <= _MICRO_ICON_SIDE and w * h <= _MICRO_ICON_MAX_AREA:
                return False, b"", "", ""
            if (
                _SMALL_ICON_MIN_BYTES < len(data) < _SMALL_ICON_MAX_BYTES
                and w * h <= _SMALL_ICON_MAX_AREA
            ):
                return False, b"", "", ""
            if (
                short_side < _EXTREME_SHORT_SIDE
                and long_side / max(1, short_side) > _EXTREME_ASPECT_RATIO
            ):
                return False, b"", "", ""
            stddev = ImageStat.Stat(im.convert("L")).stddev[0]
            if stddev < _MIN_GRAY_STDDEV:
                return False, b"", "", ""
            fmt = (raw.format or "PNG").upper()
            if fmt == "JPEG":
                return True, data, "image/jpeg", ".jpg"
            if fmt == "WEBP":
                return True, data, "image/webp", ".webp"
            if fmt == "PNG":
                return True, data, "image/png", ".png"
            out = BytesIO()
            im.convert("RGBA").save(out, format="PNG")
            return True, out.getvalue(), "image/png", ".png"
    except UnidentifiedImageError, OSError, ValueError:
        return False, b"", "", ""


class ImageDeduplicator:
    """Track seen image digests and skip ignored or duplicate images."""

    def __init__(self, ignored_digests: set[bytes] | None = None) -> None:
        self.ignored = ignored_digests or set()
        self.seen: dict[bytes, str] = {}

    def accept(
        self, data: bytes, block_type: str | None = None
    ) -> tuple[bool, str | None, bytes, str, str]:
        """Returns (keep, existing_rel_path_if_dup, out_bytes, media_type, ext)."""
        digest = image_digest(data)
        if digest in self.ignored:
            return False, None, b"", "", ""
        if digest in self.seen:
            return True, self.seen[digest], b"", "", ""
        keep, out_bytes, media, ext = normalize_image(data, block_type=block_type)
        if not keep:
            return False, None, b"", "", ""
        norm_digest = image_digest(out_bytes)
        if norm_digest in self.ignored:
            return False, None, b"", "", ""
        if norm_digest in self.seen:
            self.seen[digest] = self.seen[norm_digest]
            return True, self.seen[norm_digest], b"", "", ""
        return True, None, out_bytes, media, ext

    def register(self, raw_data: bytes, out_bytes: bytes, rel_path: str) -> None:
        """Record raw and normalized digests against the saved relative path."""
        self.seen[image_digest(raw_data)] = rel_path
        self.seen[image_digest(out_bytes)] = rel_path


class ImageArtifactWriter:
    """Filter, deduplicate, budget-check, and persist image artifacts to disk."""

    def __init__(
        self,
        output: Path,
        max_blob: int,
        max_output: int,
        max_artifacts: int | None = None,
        ignored_digests: set[bytes] | None = None,
    ) -> None:
        self.output = output
        self.max_blob = max_blob
        self.max_output = max_output
        self.max_artifacts = max_artifacts
        self.dedup = ImageDeduplicator(ignored_digests=ignored_digests)
        self.count = 0
        self.total_bytes = 0

    def save(
        self, raw_data: bytes, block_type: str | None = None
    ) -> tuple[bool, str | None]:
        """Filter, deduplicate, and persist ``raw_data`` under ``images/``."""
        keep, dup_path, out_bytes, _, ext = self.dedup.accept(
            raw_data, block_type=block_type
        )
        if not keep:
            return False, None
        if dup_path is not None:
            return True, dup_path
        if (
            len(out_bytes) > self.max_blob
            or self.total_bytes + len(out_bytes) > self.max_output
        ):
            raise ValueError("images exceed byte budget")
        if self.max_artifacts is not None and self.count >= self.max_artifacts:
            raise ValueError("images exceed artifact count")
        self.total_bytes += len(out_bytes)
        self.count += 1
        rel = f"images/{self.count:02d}-img{ext}"
        dest = self.output / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(out_bytes)
        self.dedup.register(raw_data, out_bytes, rel)
        return True, rel
