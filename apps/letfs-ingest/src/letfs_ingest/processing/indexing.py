import json
import math
from uuid import NAMESPACE_URL, uuid5

from letfs_ingest.parser.text_split import estimate_tokens, split_text
from letfs_ingest.processing.readme import own_body


def evidence_points(
    nodes,
    contents,
    filesystem_id,
    scope_id,
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
                "scope_id": scope_id,
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


async def index_tree(
    nodes,
    contents,
    ai,
    qdrant,
    space,
    filesystem_id,
    scope_id,
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
        scope_id,
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
