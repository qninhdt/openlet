import asyncio
import csv
from io import StringIO
from typing import Literal, TypedDict
from uuid import NAMESPACE_DNS, uuid5

from langchain_text_splitters import RecursiveCharacterTextSplitter
from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as letfs
from openlet_sdk.config import Config
from qdrant_client import models

from .protocols import EmbeddingModels, VectorStore
from .readme import own_body

type PointKind = Literal["image", "table", "text", "text_chunk"]


class PointPayload(TypedDict):
    workspace_id: str
    blob_id: str
    artifact_path: str
    kind: PointKind
    title: str
    chunk_index: int
    text: str


def _point_id(
    blob_id: str, artifact_path: str, kind: PointKind, chunk_index: int
) -> str:
    return str(uuid5(NAMESPACE_DNS, f"{blob_id}:{artifact_path}:{kind}:{chunk_index}"))


def _csv_headers(text: str) -> str:
    rows = csv.reader(StringIO(text))
    empty: list[str] = []
    first = next(rows, empty)
    cols = [c.strip() for c in first if c.strip()]
    return ", ".join(cols)


_MIN_FRAGMENT_CHARS = 160


def _merge_small_chunks(
    chunks: list[str], min_chars: int = _MIN_FRAGMENT_CHARS, max_chars: int = 4_000
) -> list[str]:
    """Fold undersized leading or trailing fragments into an adjacent chunk cleanly."""
    if len(chunks) <= 1:
        return chunks
    out = list(chunks)
    i = 0
    while i < len(out) and len(out) > 1:
        cur = out[i]
        if len(cur.strip()) < min_chars:
            if i > 0 and len(out[i - 1]) + 2 + len(cur) <= max_chars:
                out[i - 1] = f"{out[i - 1].rstrip()}\n\n{cur.lstrip()}"
                out.pop(i)
                continue
            if i + 1 < len(out) and len(cur) + 2 + len(out[i + 1]) <= max_chars:
                out[i + 1] = f"{cur.rstrip()}\n\n{out[i + 1].lstrip()}"
                out.pop(i)
                continue
        i += 1
    return out


def points(
    info: internal.GetBlobArtifactsResponse, config: Config
) -> list[tuple[str, PointPayload]]:
    io = config["services"]["letfs_ingest"]["io"]
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=io["chunk_size_tokens"],
        chunk_overlap=io["chunk_overlap_tokens"],
    )
    out: list[tuple[str, PointPayload]] = []

    if not info.artifacts and info.media_type.startswith("image/"):
        text = "\n\n".join(filter(None, [info.title, info.description]))
        if text:
            out.append(
                (
                    _point_id(info.blob_id, "", "image", 0),
                    PointPayload(
                        workspace_id=info.workspace_id,
                        blob_id=info.blob_id,
                        artifact_path="",
                        kind="image",
                        title=info.title,
                        chunk_index=0,
                        text=text,
                    ),
                )
            )
        return out

    for art in info.artifacts:
        if art.kind != letfs.NODE_KIND_FILE or not art.indexable:
            continue
        summary = "\n\n".join(filter(None, [art.title, art.description]))

        if art.media_type.startswith("image/"):
            if summary:
                out.append(
                    (
                        _point_id(info.blob_id, art.path, "image", 0),
                        PointPayload(
                            workspace_id=info.workspace_id,
                            blob_id=info.blob_id,
                            artifact_path=art.path,
                            kind="image",
                            title=art.title,
                            chunk_index=0,
                            text=summary,
                        ),
                    )
                )
            continue

        body = art.text_content if art.HasField("text_content") else ""
        if art.media_type == "text/csv" or art.path.endswith(".csv"):
            headers = _csv_headers(body)
            parts = [summary] if summary else []
            if headers:
                parts.append(f"Columns: {headers}")
            text = "\n".join(parts)
            if text:
                out.append(
                    (
                        _point_id(info.blob_id, art.path, "table", 0),
                        PointPayload(
                            workspace_id=info.workspace_id,
                            blob_id=info.blob_id,
                            artifact_path=art.path,
                            kind="table",
                            title=art.title,
                            chunk_index=0,
                            text=text,
                        ),
                    )
                )
            continue

        if art.path == "README.md":
            body = own_body(body)
        if not body.strip():
            continue
        chunks = _merge_small_chunks(
            splitter.split_text(body),
            max_chars=max(2_400, int(io["chunk_size_tokens"]) * 5),
        )
        if len(chunks) == 1:
            combined = f"{summary}\n\n{chunks[0]}".strip() if summary else chunks[0]
            out.append(
                (
                    _point_id(info.blob_id, art.path, "text_chunk", 0),
                    PointPayload(
                        workspace_id=info.workspace_id,
                        blob_id=info.blob_id,
                        artifact_path=art.path,
                        kind="text_chunk",
                        title=art.title,
                        chunk_index=0,
                        text=combined,
                    ),
                )
            )
        else:
            if summary:
                out.append(
                    (
                        _point_id(info.blob_id, art.path, "text", 0),
                        PointPayload(
                            workspace_id=info.workspace_id,
                            blob_id=info.blob_id,
                            artifact_path=art.path,
                            kind="text",
                            title=art.title,
                            chunk_index=0,
                            text=summary,
                        ),
                    )
                )
            for idx, chunk in enumerate(chunks):
                if not any(ch.isalnum() for ch in chunk):
                    continue
                text = f"{art.title}\n\n{chunk}".strip() if art.title else chunk
                out.append(
                    (
                        _point_id(info.blob_id, art.path, "text_chunk", idx),
                        PointPayload(
                            workspace_id=info.workspace_id,
                            blob_id=info.blob_id,
                            artifact_path=art.path,
                            kind="text_chunk",
                            title=art.title,
                            chunk_index=idx,
                            text=text,
                        ),
                    )
                )
    return out


async def index(
    info: internal.GetBlobArtifactsResponse,
    ai: EmbeddingModels,
    qdrant: VectorStore,
    config: Config,
) -> None:
    io = config["services"]["letfs_ingest"]["io"]
    collection = config["dependencies"]["qdrant"]["collection"]
    # Clear any earlier retry/partial points before idempotent upsert.
    await qdrant.delete(
        collection_name=collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="blob_id", match=models.MatchValue(value=info.blob_id)
                    )
                ]
            )
        ),
        wait=True,
    )

    items = points(info, config)
    if not items:
        return

    batch_size = int(io["embedding_batch_size"])
    sem = asyncio.Semaphore(int(io["model_concurrency"]))

    async def embed_chunk(
        slice_items: list[tuple[str, PointPayload]],
    ) -> list[models.PointStruct]:
        async with sem:
            vectors = await ai.embed([p[1]["text"] for p in slice_items])
        return [
            models.PointStruct(id=pid, vector=vec, payload=dict(payload))
            for (pid, payload), vec in zip(slice_items, vectors, strict=True)
        ]

    batches = [items[i : i + batch_size] for i in range(0, len(items), batch_size)]
    nested = await asyncio.gather(*(embed_chunk(b) for b in batches))
    structs = [pt for group in nested for pt in group]
    for i in range(0, len(structs), 256):
        await qdrant.upsert(
            collection_name=collection,
            points=structs[i : i + 256],
            wait=True,
        )
