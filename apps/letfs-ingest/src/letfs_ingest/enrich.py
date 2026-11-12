import asyncio
import json
from collections import defaultdict
from pathlib import PurePosixPath

from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as pb
from temporalio import activity

from .artifacts import check_transfer
from .readme import own_body, render


async def image_bytes(http, url, limit):
    data = bytearray()
    async with http.stream("GET", url) as response:
        check_transfer(response)
        async for chunk in response.aiter_bytes():
            if len(data) + len(chunk) > limit:
                raise ValueError("image exceeds blob limit")
            data.extend(chunk)
    return bytes(data)


async def enrich(source, identity, ai, http, max_blob_bytes):
    files = {item.path: item for item in source.artifacts if item.node.HasField("file")}
    metadata, children = {}, defaultdict(list)
    readmes = sorted((path for path in files if PurePosixPath(path).name == "README.md"), key=lambda path: path.count("/"), reverse=True)
    for path in files:
        location = PurePosixPath(path)
        if location.name != "README.md":
            children[location.parent].append(path)
        elif location.parent != PurePosixPath("."):
            children[location.parent.parent].append(path)

    async def describe(path, summaries=""):
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
    rendered = {}
    for path in readmes:
        parent = PurePosixPath(path).parent
        summaries = {
            PurePosixPath(child).relative_to(parent).as_posix(): {
                key: metadata[child].model_dump()[key] for key in ("title", "description", "semantic_type")
            }
            for child in children[parent]
        }
        await describe(path, json.dumps(summaries, ensure_ascii=False))
        rendered[path] = render(metadata[path], files[path].text_content, summaries)
    updates = []
    for path, result in metadata.items():
        update = internal.EnrichedArtifact(
            node_id=files[path].node.id, metadata=pb.FileMetadata(**result.model_dump()),
        )
        if path in rendered:
            update.text_content = rendered[path]
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
