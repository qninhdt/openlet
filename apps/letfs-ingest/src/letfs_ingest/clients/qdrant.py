import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from openlet.clients.letfs import VectorSpace


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
            ("filesystem_id", "scope_id", "source_id", "embedding_model"), "keyword"
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
