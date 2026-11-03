import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

import httpx

from letfs_ingest.readme import own_body
from letfs_ingest.text_split import estimate_tokens, split_text


@dataclass(frozen=True)
class VectorSpace:
    model: str
    collection: str
    dimension: int

    def validate(self):
        if not self.model.strip() or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,100}", self.collection
        ):
            raise ValueError("invalid vector model/collection")
        if not 1 <= self.dimension <= 65536:
            raise ValueError("invalid vector dimension")


@dataclass(frozen=True)
class IndexSettings:
    url: str
    api_key: str
    batch_size: int = 16
    chunk_tokens: int = 1024
    overlap: int = 128

    @classmethod
    def from_env(cls):
        settings = cls(
            url=os.environ["QDRANT_URL"],
            api_key=Path(os.environ["QDRANT_API_KEY_FILE"]).read_text().strip(),
            batch_size=int(os.environ.get("EMBEDDING_BATCH_SIZE", "16")),
            chunk_tokens=int(os.environ.get("CHUNK_TOKENS", "1024")),
            overlap=int(os.environ.get("CHUNK_OVERLAP_TOKENS", "128")),
        )
        parsed = urlparse(settings.url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not settings.api_key
            or not 1 <= settings.batch_size <= 128
            or not 32 <= settings.chunk_tokens <= 8192
            or not 0 <= settings.overlap < settings.chunk_tokens
        ):
            raise ValueError("invalid index configuration")
        return settings


def evidence_points(
    nodes,
    contents,
    filesystem_id,
    source_id,
    generation,
    space,
    chunk_tokens=1024,
    overlap=128,
):
    by_id = {node["id"]: node for node in nodes}
    readmes = {
        node["parent_id"]: node
        for node in nodes
        if node["name"] == "README.md" and node["path"]
    }
    if chunk_tokens < 32 or not 0 <= overlap < chunk_tokens:
        raise ValueError("invalid chunk bounds")

    def point(node, kind, ordinal, text):
        point_id = uuid5(
            NAMESPACE_URL,
            json.dumps(
                [
                    source_id,
                    generation,
                    space.model,
                    space.collection,
                    space.dimension,
                    node["id"],
                    kind,
                    ordinal,
                ],
                separators=(",", ":"),
            ),
        )
        return {
            "id": str(point_id),
            "payload": {
                "filesystem_id": filesystem_id,
                "source_id": source_id,
                "file_id": node["id"],
                "generation": generation,
                "embedding_model": space.model,
                "vector_dimension": space.dimension,
                "text": text,
            },
        }

    for node in nodes:
        if node["kind"] != "file":
            continue
        ancestors = []
        parent = node["parent_id"]
        while parent in by_id:
            ancestor = by_id[parent]
            owner = readmes.get(ancestor["id"], ancestor)
            ancestors.append(f"{owner['title']}: {owner['description']}")
            parent = ancestor["parent_id"]
        ancestors.reverse()
        overview = "\n".join(ancestors + [f"{node['title']}: {node['context']}"])
        own = node
        mime = own["media_type"] or ""
        if own["id"] not in contents or mime == "text/csv" or mime.startswith("image/"):
            yield point(node, "file", 0, overview)
            continue
        body = contents[own["id"]].decode("utf-8", errors="replace")
        if node["name"] == "README.md" and node["path"]:
            body = own_body(body)
        if estimate_tokens(body) <= chunk_tokens:
            yield point(node, "file", 0, overview + "\n\n" + body)
            continue
        yield point(node, "file", 0, overview)
        prefix = "\n".join(ancestors + [f"{node['title']}: {node['description']}"])
        for ordinal, chunk in enumerate(split_text(body, chunk_tokens, overlap)):
            yield point(node, "chunk", ordinal, prefix + "\n\n" + chunk)


class Qdrant:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def ensure_collection(self, space: VectorSpace):
        space.validate()
        path = f"/collections/{space.collection}"
        response = await self.client.get(path)
        indexes = {}
        if response.status_code == 404:
            response = await self.client.put(
                path,
                json={
                    "vectors": {
                        "dense": {"size": space.dimension, "distance": "Cosine"}
                    }
                },
            )
            response.raise_for_status()
        else:
            response.raise_for_status()
            vector = response.json()["result"]["config"]["params"]["vectors"]["dense"]
            if vector["size"] != space.dimension or vector["distance"] != "Cosine":
                raise ValueError("Qdrant vector space differs from processing snapshot")
            indexes = response.json()["result"]["payload_schema"]
        schemas = dict.fromkeys(
            ("filesystem_id", "source_id", "embedding_model"), "keyword"
        )
        schemas["text"] = {
            "type": "text",
            "tokenizer": "word",
            "lowercase": True,
            "scoring": {"type": "bm25"},
        }
        for field, schema in schemas.items():
            current = indexes.get(field)
            if current and (
                current["data_type"] == schema
                if isinstance(schema, str)
                else current.get("params") == schema
            ):
                continue
            if current:
                response = await self.client.delete(
                    path + "/index/" + field, params={"wait": "true"}
                )
                response.raise_for_status()
            response = await self.client.put(
                path + "/index",
                params={"wait": "true"},
                json={"field_name": field, "field_schema": schema},
            )
            response.raise_for_status()

    async def upsert(self, space, points):
        response = await self.client.put(
            f"/collections/{space.collection}/points",
            params={"wait": "true"},
            json={"points": points},
        )
        response.raise_for_status()
        if response.json()["result"]["status"] != "completed":
            raise ValueError("Qdrant upsert was not confirmed")


async def index_tree(
    nodes,
    contents,
    ai,
    qdrant,
    space,
    filesystem_id,
    source_id,
    generation,
    batch_size=16,
    chunk_tokens=1024,
    overlap=128,
):
    space.validate()
    if not 1 <= batch_size <= 128:
        raise ValueError("invalid embedding batch size")
    await qdrant.ensure_collection(space)
    batch = []
    total = 0

    async def flush():
        nonlocal total
        embeddings = await ai.embed(
            [p["payload"]["text"] for p in batch], space.model, space.dimension
        )
        if len(embeddings) != len(batch):
            raise ValueError("embedding result count mismatch")
        for item, vector in zip(batch, embeddings, strict=True):
            if len(vector) != space.dimension or any(
                not isinstance(v, (int, float)) or not math.isfinite(v) for v in vector
            ):
                raise ValueError("invalid embedding vector")
            item["vector"] = {"dense": vector}
        await qdrant.upsert(space, batch)
        total += len(batch)
        batch.clear()

    for point in evidence_points(
        nodes,
        contents,
        filesystem_id,
        source_id,
        generation,
        space,
        chunk_tokens,
        overlap,
    ):
        batch.append(point)
        if len(batch) == batch_size:
            await flush()
    if batch:
        await flush()
    return total
