import asyncio
import json
from collections import defaultdict
from pathlib import PurePosixPath

import httpx
from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as pb
from temporalio import activity

from .artifacts import check_transfer
from .naming import artifact_paths, rewrite_artifact_links
from .providers import Metadata, Models
from .readme import own_body, render
from .telemetry import ProcessingIdentity


async def image_bytes(http: httpx.AsyncClient, url: str, limit: int) -> bytes:
    data = bytearray()
    async with http.stream("GET", url) as response:
        check_transfer(response)
        async for chunk in response.aiter_bytes():
            if len(data) + len(chunk) > limit:
                raise ValueError("image exceeds blob limit")
            data.extend(chunk)
    return bytes(data)


async def enrich(source: internal.ProcessingInput, identity: ProcessingIdentity, ai: Models, http: httpx.AsyncClient, max_blob_bytes: int) -> internal.CommitEnrichmentRequest:
    files = {item.path: item for item in source.artifacts if item.node.HasField("file")}
    metadata: dict[str, Metadata] = {}
    children: defaultdict[PurePosixPath, list[str]] = defaultdict(list)
    readmes = sorted((path for path in files if PurePosixPath(path).name == "README.md"), key=lambda path: path.count("/"), reverse=True)
    for path in files:
        location = PurePosixPath(path)
        if location.name != "README.md":
            children[location.parent].append(path)
        elif location.parent != PurePosixPath("."):
            children[location.parent.parent].append(path)

    async def describe(path: str, summaries: str = "") -> None:
        item = files[path]
        async with ai.slots:
            image = await image_bytes(http, item.download_url, max_blob_bytes) if item.node.file.media_type.startswith("image/") else None
            metadata[path] = await ai.describe(
                path, own_body(item.text_content), item.node.file.media_type, summaries, image,
            )
        activity.heartbeat()

    async with asyncio.TaskGroup() as group:
        for path in files:
            if PurePosixPath(path).name != "README.md":
                group.create_task(describe(path))
    for path in readmes:
        parent = PurePosixPath(path).parent
        summaries = {
            PurePosixPath(child).relative_to(parent).as_posix(): {
                key: metadata[child].model_dump()[key] for key in ("title", "description", "semantic_type")
            }
            for child in children[parent]
        }
        await describe(path, json.dumps(summaries, ensure_ascii=False))
    paths = artifact_paths(source.artifacts, metadata)
    updates = []
    for item in source.artifacts:
        path = item.path
        update = internal.EnrichedArtifact(node_id=item.node.id)
        if PurePosixPath(paths[path]).name != PurePosixPath(path).name:
            update.name = PurePosixPath(paths[path]).name
        if item.node.HasField("file"):
            update.metadata.CopyFrom(pb.FileMetadata(**metadata[path].model_dump()))
            if PurePosixPath(path).suffix == ".md":
                is_readme = PurePosixPath(path).name == "README.md"
                body = rewrite_artifact_links(own_body(item.text_content) if is_readme else item.text_content, path, paths)
                if is_readme:
                    parent = PurePosixPath(paths[path]).parent
                    summaries = {
                        PurePosixPath(paths[child]).relative_to(parent).as_posix(): {
                            key: metadata[child].model_dump()[key] for key in ("title", "description", "semantic_type")
                        }
                        for child in children[PurePosixPath(path).parent]
                    }
                    body = render(metadata[path], body, summaries)
                update.text_content = body
        updates.append(update)
    root = metadata.get("README.md")
    if root is None:
        async with ai.slots:
            image = await image_bytes(http, source.download_url, max_blob_bytes) if source.media_type.startswith("image/") else None
            root = await ai.describe(source.source_name, "", source.media_type, "\n".join(
                f"{path}: {value.description}" for path, value in metadata.items()
            ), image)
    return internal.CommitEnrichmentRequest(
        **identity, artifacts=updates, source_metadata=pb.FileMetadata(**root.model_dump()),
    )
