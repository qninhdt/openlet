import json
import math
from pathlib import PurePosixPath
from uuid import NAMESPACE_URL, uuid5

from langchain_text_splitters import RecursiveCharacterTextSplitter
from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as pb
from qdrant_client import models
from temporalio import activity

from .readme import own_body
from .telemetry import stage


def points(source, identity, settings, embedding, collection):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings["chunk_size_tokens"] * 4,
        chunk_overlap=settings["chunk_overlap_tokens"] * 4,
    )
    space = [embedding["model"], embedding["dimensions"], collection]
    artifacts = list(source.artifacts)
    if source.media_type.startswith("image/"):
        artifacts.append(internal.ProcessingArtifact(
            path=source.source_name,
            node=pb.Node(id=identity["file_id"], file=pb.FileHeader(media_type=source.media_type, metadata=source.source_metadata)),
        ))
    readmes = {
        PurePosixPath(artifact.path).parent: artifact.node.file.metadata
        for artifact in artifacts if PurePosixPath(artifact.path).name == "README.md" and artifact.node.HasField("file")
    }
    for artifact in artifacts:
        node = artifact.node
        if not node.HasField("file"):
            continue
        metadata = node.file.metadata
        ancestors = []
        for parent in reversed(PurePosixPath(artifact.path).parents):
            owner = readmes.get(parent)
            if owner is not None and parent / "README.md" != PurePosixPath(artifact.path):
                ancestors.append(f"{owner.title}: {owner.description}")
        overview = "\n".join([*ancestors, artifact.path, metadata.title, metadata.description, metadata.context])
        body = artifact.text_content if artifact.HasField("text_content") else ""
        if PurePosixPath(artifact.path).name == "README.md":
            body = own_body(body)
        if node.file.media_type == "text/csv" or not body:
            chunks = [("file", overview)]
        elif len(body) <= settings["chunk_size_tokens"] * 4:
            chunks = [("file", overview + "\n\n" + body)]
        else:
            prefix = "\n".join([*ancestors, artifact.path, metadata.title, metadata.description])
            chunks = [("file", overview), *(("chunk", prefix + "\n\n" + chunk) for chunk in splitter.split_text(body))]
        for ordinal, (kind, text) in enumerate(chunks):
            key = json.dumps([identity["file_id"], identity["version"], node.id, kind, ordinal, *space], separators=(",", ":"))
            yield str(uuid5(NAMESPACE_URL, key)), {
                "workspace_id": source.workspace_id, "storage_id": source.storage_id,
                "source_id": identity["file_id"], "source_version": identity["version"],
                "file_id": node.id, "kind": kind, "text": text,
            }


async def index(source, identity, ai, qdrant, config):
    settings = config["services"]["letfs_ingest"]["io"]
    embedding = config["models"]["embedding"]
    collection = config["dependencies"]["qdrant"]["collection"]
    batch = []

    async def flush():
        with stage("embed", identity):
            vectors = await ai.embed([payload["text"] for _, payload in batch])
        if len(vectors) != len(batch) or any(
            len(vector) != embedding["dimensions"] or not all(math.isfinite(value) for value in vector)
            for vector in vectors
        ):
            raise ValueError("embedding provider returned invalid vectors")
        await qdrant.upsert(collection_name=collection, wait=True, points=[
            models.PointStruct(id=key, vector=vector, payload=payload)
            for (key, payload), vector in zip(batch, vectors, strict=True)
        ])
        batch.clear()
        activity.heartbeat()

    for point in points(source, identity, settings, embedding, collection):
        batch.append(point)
        if len(batch) == settings["embedding_batch_size"]:
            await flush()
    if batch:
        await flush()
