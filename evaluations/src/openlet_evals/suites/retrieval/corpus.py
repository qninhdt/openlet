"""Load `.letfs-cache/` points, cache query embeddings, and manage ephemeral Qdrant v1.20.0."""

from __future__ import annotations

import hashlib
import json
import posixpath
import socket
import subprocess
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx
import numpy as np
from openai import OpenAI
from openlet_env.cache import CACHE_DIR
from openlet_env.models import CacheMetadata
from pydantic import TypeAdapter
from qdrant_client import QdrantClient, models

_EMBED_CACHE_ADAPTER = TypeAdapter(dict[str, list[float]])

COLLECTION = "files"
QDRANT_IMAGE = (
    "qdrant/qdrant:v1.20.0"
    "@sha256:9bfc89f9914fc14876a88c05270685921a55b8877b254a98bcc1cc2f0a424cd2"
)


def load_shared_corpus(
    datasets_dir: Path,
) -> tuple[
    list[models.PointStruct],
    dict[str, str],
    dict[str, set[str]],
    dict[str, int],
    dict[str, int],
]:
    """Read all `.letfs-cache/` metadata + vectors under `workspaces/*/storages/shared/`."""
    points: list[models.PointStruct] = []
    bid_to_path: dict[str, str] = {}
    indexed_by_ws: dict[str, set[str]] = defaultdict(set)
    blobs_by_ws: Counter[str] = Counter()
    pts_by_ws: Counter[str] = Counter()

    for ws_dir in sorted((datasets_dir / "workspaces").iterdir()):
        shared = ws_dir / "storages" / "shared"
        if not shared.is_dir():
            continue
        for meta_path in sorted(shared.rglob("metadata.json")):
            if CACHE_DIR not in meta_path.parts:
                continue
            bname = meta_path.parent.name
            sub = meta_path.parent.parent.parent.relative_to(shared).parts
            bpath = "/" + "/".join((*sub, bname))
            bid = str(uuid5(NAMESPACE_URL, f"{ws_dir.name}:shared:{bpath}"))
            bid_to_path[bid] = bpath
            blobs_by_ws[ws_dir.name] += 1

            meta = CacheMetadata.model_validate_json(
                meta_path.read_text(encoding="utf-8")
            )
            with np.load(
                meta_path.parent / "embeddings.npz", allow_pickle=False
            ) as npz:
                vmap: dict[bytes, list[float]] = dict(
                    zip(
                        map(bytes, npz["text_sha256"]),
                        npz["vectors"].tolist(),
                        strict=True,
                    )
                )
            for idx, pt in enumerate(meta.points):
                txt = pt.text
                ap = pt.path
                canonical = posixpath.join(bpath, ap) if ap else bpath
                indexed_by_ws[ws_dir.name].add(canonical)
                pid = str(uuid5(NAMESPACE_URL, f"{bid}:{ap}:{pt.kind}:{idx}"))
                points.append(
                    models.PointStruct(
                        id=pid,
                        vector=vmap[hashlib.sha256(txt.encode("utf-8")).digest()],
                        payload={
                            "workspace_id": ws_dir.name,
                            "blob_id": bid,
                            "artifact_path": ap,
                            "text": txt,
                        },
                    )
                )
                pts_by_ws[ws_dir.name] += 1

    return points, bid_to_path, dict(indexed_by_ws), dict(blobs_by_ws), dict(pts_by_ws)


def embed_queries(
    texts: Sequence[str],
    *,
    base_url: str,
    api_key: str,
    model: str,
    dimensions: int,
    cache_path: Path,
) -> list[list[float]]:
    """Embed queries in batches of 20 using `openai.OpenAI` with SHA-256 disk caching."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cached: dict[str, list[float]] = (
        _EMBED_CACHE_ADAPTER.validate_json(cache_path.read_text(encoding="utf-8"))
        if cache_path.is_file()
        else {}
    )
    missing = [
        t
        for t in dict.fromkeys(texts)
        if hashlib.sha256(t.encode("utf-8")).hexdigest() not in cached
    ]
    if missing:
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=120.0)
        try:
            for i in range(0, len(missing), 20):
                batch = missing[i : i + 20]
                resp = client.embeddings.create(
                    model=model,
                    input=batch,
                    dimensions=dimensions,
                    encoding_format="float",
                )
                for text, item in zip(
                    batch, sorted(resp.data, key=lambda d: d.index), strict=True
                ):
                    cached[hashlib.sha256(text.encode("utf-8")).hexdigest()] = list(
                        item.embedding
                    )
        finally:
            client.close()
        cache_path.write_text(json.dumps(cached), encoding="utf-8")

    return [cached[hashlib.sha256(t.encode("utf-8")).hexdigest()] for t in texts]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class EphemeralQdrant:
    """Context manager for a temporary `qdrant/qdrant:v1.20.0` container."""

    def __init__(self, *, dimensions: int = 1536, image: str = QDRANT_IMAGE) -> None:
        self._dimensions = dimensions
        self._image = image
        self._name = ""
        self._client: QdrantClient | None = None

    def __enter__(self) -> QdrantClient:
        hp, gp = _free_port(), _free_port()
        self._name = f"openlet-eval-qdrant-{hp}"
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                self._name,
                "-p",
                f"127.0.0.1:{hp}:6333",
                "-p",
                f"127.0.0.1:{gp}:6334",
                self._image,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        for _ in range(75):
            try:
                if (
                    httpx.get(f"http://127.0.0.1:{hp}/readyz", timeout=2.0).status_code
                    == 200
                ):
                    break
            except Exception:
                pass
            time.sleep(0.2)
        else:
            self.__exit__(None, None, None)
            raise RuntimeError(f"Qdrant container {self._name} failed to start")

        client = QdrantClient(host="127.0.0.1", port=hp, grpc_port=gp, prefer_grpc=True)
        client.create_collection(
            COLLECTION,
            vectors_config=models.VectorParams(
                size=self._dimensions, distance=models.Distance.COSINE
            ),
        )
        for field in ("workspace_id", "blob_id"):
            client.create_payload_index(
                COLLECTION, field, models.PayloadSchemaType.KEYWORD, wait=True
            )
        client.create_payload_index(
            COLLECTION,
            "text",
            models.TextIndexParams(
                type=models.TextIndexType.TEXT,
                tokenizer=models.TokenizerType.WORD,
                scoring=True,
            ),
            wait=True,
        )
        self._client = client
        return client

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._name:
            subprocess.run(
                ["docker", "rm", "-f", self._name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
