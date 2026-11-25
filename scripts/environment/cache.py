"""Portable LetFS artifacts and vectors, keyed by source and artifact path."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import numpy as np
from openlet_sdk.config import Config

from .api import JSON

CACHE_DIR = ".letfs-cache"
PARSED = {".docx", ".pdf", ".pptx", ".xlsx"}
INDEXED = PARSED | {".gif", ".jpeg", ".jpg", ".png", ".webp"}


@dataclass
class Cache:
    folder: Path
    metadata: JSON
    vectors: dict[bytes, list[float]]


def text_key(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


def fingerprint(path: Path, config: Config) -> JSON:
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    ingest = config["services"]["letfs_ingest"]
    langfuse = config.get("langfuse")
    return {
        "format": 6,
        "source": path.name,
        "sha256": digest,
        "embedding": config["models"]["embedding"],
        "enrichment": config["models"]["enrichment"],
        "prompt_label": langfuse["prompt_label"] if langfuse else None,
        "parser": ingest["cpu"],
        "chunk_size_tokens": ingest["io"]["chunk_size_tokens"],
        "chunk_overlap_tokens": ingest["io"]["chunk_overlap_tokens"],
    }


def read(path: Path, config: Config) -> Cache | None:
    folder = path.parent / CACHE_DIR / path.name
    metadata_path = folder / "metadata.json"
    if not metadata_path.is_file():
        return None
    metadata = cast(JSON, json.loads(metadata_path.read_text(encoding="utf-8")))
    if metadata["input"] != fingerprint(path, config):
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
        return Cache(folder, metadata, lookup)


def save(
    source: Path,
    input_settings: JSON,
    metadata: JSON,
    vectors: dict[bytes, list[float]],
    artifacts: dict[str, bytes | None],
) -> None:
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
        (output / "metadata.json").write_text(
            json.dumps({"input": input_settings, **metadata}, indent=2) + "\n"
        )
        width = input_settings["embedding"]["dimensions"]
        np.savez(
            output / "embeddings.npz",
            text_sha256=np.asarray(
                [list(key) for key in vectors], dtype=np.uint8
            ).reshape(len(vectors), 32),
            vectors=np.asarray(list(vectors.values()), dtype=np.float32).reshape(
                len(vectors), width
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
