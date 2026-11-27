"""Portable `.letfs-cache/` read/write with content-only fingerprinting."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

import numpy as np

from openlet_env.models import CacheInput, CacheMetadata, CachePointMeta

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from openlet_sdk.config import Config

CACHE_DIR = ".letfs-cache"
CACHE_FORMAT = 7
PARSED = frozenset({".docx", ".pdf", ".pptx", ".xlsx"})
INDEXED = PARSED | frozenset({".gif", ".jpeg", ".jpg", ".png", ".webp"})


@dataclass(frozen=True, slots=True)
class CachedIngest:
    """Loaded `.letfs-cache` directory contents and embeddings."""

    folder: Path
    metadata: CacheMetadata
    vectors: Mapping[bytes, Sequence[float]]


def text_key(text: str) -> bytes:
    """Return the SHA-256 digest key for a cached text chunk."""
    return hashlib.sha256(text.encode("utf-8")).digest()


def fingerprint(path: Path, config: Config) -> CacheInput:
    """Content-only ingest fingerprint (excludes concurrency and rate-limit knobs)."""
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    ingest = config["services"]["letfs_ingest"]
    langfuse = config.get("langfuse")
    emb = config["models"]["embedding"]
    enr = config["models"]["enrichment"]
    limits = ingest["cpu"]["limits"]
    return CacheInput(
        format=CACHE_FORMAT,
        source=path.name,
        sha256=digest,
        embedding={
            "model": emb["model"],
            "dimensions": emb["dimensions"],
        },
        enrichment={
            "output_mode": enr["output_mode"],
            "max_input_characters": enr["max_input_characters"],
            "max_image_pixels": enr["max_image_pixels"],
            "image_max_side": enr["image_max_side"],
            "image_jpeg_quality": enr["image_jpeg_quality"],
        },
        prompt_label=langfuse["prompt_label"] if langfuse else None,
        split_tokens=ingest["cpu"]["split_tokens"],
        limits={
            "max_pages": limits["max_pages"],
            "max_page_pixels": limits["max_page_pixels"],
            "max_office_expanded_bytes": limits["max_office_expanded_bytes"],
            "max_spreadsheet_cells": limits["max_spreadsheet_cells"],
            "max_sheets": limits["max_sheets"],
            "max_output_bytes": limits["max_output_bytes"],
        },
        chunk_size_tokens=ingest["io"]["chunk_size_tokens"],
        chunk_overlap_tokens=ingest["io"]["chunk_overlap_tokens"],
    )


def read_cache(path: Path, config: Config) -> CachedIngest | None:
    """Read and validate cached ingest artifacts for ``path``, or return ``None``."""
    folder = path.parent / CACHE_DIR / path.name
    metadata_path = folder / "metadata.json"
    if not metadata_path.is_file():
        return None
    metadata = CacheMetadata.model_validate_json(
        metadata_path.read_text(encoding="utf-8")
    )
    if metadata.input.normalized() != fingerprint(path, config).normalized():
        return None
    with np.load(folder / "embeddings.npz", allow_pickle=False) as data:
        hashes, vectors = data["text_sha256"], data["vectors"]
        width = config["models"]["embedding"]["dimensions"]
        if (
            hashes.dtype != np.uint8
            or hashes.shape != (len(vectors), 32)
            or vectors.dtype != np.float32
            or vectors.shape != (len(hashes), width)
            or not np.isfinite(vectors).all()
        ):
            raise ValueError(f"invalid embeddings in {folder}")
        lookup = dict(zip(map(bytes, hashes), vectors.tolist(), strict=True))
        if len(lookup) != len(hashes):
            raise ValueError(f"duplicate embedding hashes in {folder}")
        return CachedIngest(folder=folder, metadata=metadata, vectors=lookup)


def save_cache(
    source: Path,
    input_settings: CacheInput,
    files: dict[str, list[str]],
    *,
    points: list[CachePointMeta],
    vectors: dict[bytes, list[float]],
    artifacts: dict[str, bytes | None],
    dimensions: int,
) -> None:
    """Atomically write cached ingest artifacts and embeddings for ``source``."""
    parent = source.parent / CACHE_DIR
    parent.mkdir(exist_ok=True)
    target = parent / source.name
    with TemporaryDirectory(dir=parent) as temporary:
        base = Path(temporary)
        output = base / "cache"
        artifact_root = output / "artifacts"
        artifact_root.mkdir(parents=True)
        for name, content in artifacts.items():
            path = artifact_root / name
            if content is None:
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        payload = CacheMetadata(input=input_settings, files=files, points=points)
        (output / "metadata.json").write_text(
            payload.model_dump_json(indent=2, exclude_none=True) + "\n",
            encoding="utf-8",
        )
        np.savez(
            output / "embeddings.npz",
            text_sha256=np.asarray(
                [list(key) for key in vectors], dtype=np.uint8
            ).reshape(len(vectors), 32),
            vectors=np.asarray(list(vectors.values()), dtype=np.float32).reshape(
                len(vectors), dimensions
            ),
        )
        old = base / "old"
        if target.exists():
            target.rename(old)
        try:
            output.rename(target)
        except BaseException:
            if old.exists():
                old.rename(target)
            raise
