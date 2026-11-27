"""Multimodal artifact enrichment and README synthesis for LetFS blobs."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as letfs

from letfs_ingest.naming import artifact_paths, rewrite_artifact_links, rich_csv_paths
from letfs_ingest.providers import (
    ArtifactEnrichment,
    EnrichItem,
    adaptive_item_budget,
    evidence,
    pack_batches,
    vision,
)
from letfs_ingest.readme import own_body
from letfs_ingest.readme import render as render_readme

if TYPE_CHECKING:
    from openlet_sdk.config import Config, EnrichmentSettings

    from letfs_ingest.protocols import BlobReader, EnrichmentModels, LetFSEnrichStub


async def _enrich_standalone_image(
    info: internal.GetBlobArtifactsResponse,
    stub: LetFSEnrichStub,
    s3: BlobReader,
    ai: EnrichmentModels,
    *,
    max_blob_bytes: int,
    enrich_cfg: EnrichmentSettings,
) -> internal.BlobProcessingOutcome:
    if not info.media_type.startswith("image/"):
        return internal.BlobProcessingOutcome(obsolete=False, stage=info.outcome.stage)
    img_bytes = await s3.get_bytes(info.object_key, max_blob_bytes)
    b64 = vision(img_bytes, enrich_cfg)
    results = await ai.describe_batch(
        [EnrichItem(id=".", media_type=info.media_type, image_b64=b64)]
    )
    res = results["."]
    return await stub.SaveEnrichedArtifacts(
        internal.SaveEnrichedArtifactsRequest(
            blob_id=info.blob_id,
            blob_title=res.title,
            blob_description=res.description,
        )
    )


def _collect_child_metadata(
    file_arts: list[internal.BlobArtifact],
    rename_map: dict[str, str],
    results: dict[str, ArtifactEnrichment],
) -> dict[str, tuple[str, str]]:
    child_meta: dict[str, tuple[str, str]] = {}
    for art in file_arts:
        if art.path == "README.md":
            continue
        final_path = rename_map.get(art.path, art.path)
        meta = results.get(art.path)
        if meta is not None:
            child_meta[final_path] = (meta.title, meta.description)
        else:
            child_meta[final_path] = (art.title or final_path, art.description or "")
    return child_meta


def _build_enriched_updates(
    file_arts: list[internal.BlobArtifact],
    contents_by_path: dict[str, str],
    rename_map: dict[str, str],
    results: dict[str, ArtifactEnrichment],
    *,
    max_text_bytes: int,
) -> list[internal.EnrichedArtifactInput]:
    rich_csvs = rich_csv_paths(contents_by_path)
    child_meta = _collect_child_metadata(file_arts, rename_map, results)
    updates: list[internal.EnrichedArtifactInput] = []
    for art in file_arts:
        new_path = rename_map.get(art.path, art.path)
        meta = results.get(art.path)
        updated_text: str | None = None
        if art.path in contents_by_path:
            raw_text = (
                own_body(contents_by_path[art.path])
                if art.path == "README.md"
                else contents_by_path[art.path]
            )
            rewritten = rewrite_artifact_links(
                raw_text,
                new_path,
                art.media_type,
                rename_map,
                is_rich_csv=(art.path in rich_csvs),
            )
            if art.path == "README.md" and meta is not None:
                rendered = render_readme(
                    meta.title, meta.description, child_meta, rewritten
                )
                if len(rendered.encode("utf-8")) <= max_text_bytes:
                    rewritten = rendered
            if rewritten != contents_by_path[art.path]:
                updated_text = rewritten

        entry = internal.EnrichedArtifactInput(artifact_id=art.id)
        if new_path != art.path:
            entry.path = new_path
        if updated_text is not None:
            entry.text_content = updated_text
        if meta is not None:
            entry.title = meta.title
            entry.description = meta.description
        updates.append(entry)
    return updates


async def enrich(
    info: internal.GetBlobArtifactsResponse,
    stub: LetFSEnrichStub,
    s3: BlobReader,
    ai: EnrichmentModels,
    config: Config,
) -> internal.BlobProcessingOutcome:
    """Enrich standalone images or parsed artifact trees using unified multimodal batches."""
    storage_cfg = config["services"]["letfs"]
    max_blob_bytes = int(storage_cfg["max_blob_bytes"])
    max_art_blob_bytes = int(storage_cfg["processing"]["max_artifact_blob_bytes"])
    enrich_cfg = config["models"]["enrichment"]
    io_cfg = config["services"]["letfs_ingest"]["io"]
    sem = asyncio.Semaphore(int(io_cfg["model_concurrency"]))

    if not info.artifacts:
        return await _enrich_standalone_image(
            info,
            stub,
            s3,
            ai,
            max_blob_bytes=max_blob_bytes,
            enrich_cfg=enrich_cfg,
        )

    file_arts = [a for a in info.artifacts if a.kind == letfs.NODE_KIND_FILE]
    if not file_arts:
        return await stub.SaveEnrichedArtifacts(
            internal.SaveEnrichedArtifactsRequest(blob_id=info.blob_id)
        )

    item_budget = adaptive_item_budget(
        len(file_arts), int(enrich_cfg["max_input_characters"])
    )
    items: list[EnrichItem | None] = [None] * len(file_arts)
    contents_by_path: dict[str, str] = {}

    async def load_image_item(idx: int, art: internal.BlobArtifact) -> None:
        async with sem:
            raw = await s3.get_bytes(art.object_key, max_art_blob_bytes)
        items[idx] = EnrichItem(
            id=art.path, media_type=art.media_type, image_b64=vision(raw, enrich_cfg)
        )

    image_tasks: list[asyncio.Task[None]] = []
    for idx, art in enumerate(file_arts):
        if art.media_type.startswith("image/") and art.HasField("object_key"):
            image_tasks.append(asyncio.create_task(load_image_item(idx, art)))
        else:
            text = art.text_content if art.HasField("text_content") else ""
            contents_by_path[art.path] = text
            sampled = (
                evidence(text, art.media_type, item_budget)
                if text.strip()
                else art.path
            )
            items[idx] = EnrichItem(
                id=art.path, media_type=art.media_type, text_sample=sampled
            )
    if image_tasks:
        await asyncio.gather(*image_tasks)

    batches = pack_batches([it for it in items if it is not None])

    async def run_batch(
        batch: list[EnrichItem],
    ) -> dict[str, ArtifactEnrichment]:
        async with sem:
            return await ai.describe_batch(batch)

    batch_results = await asyncio.gather(*(run_batch(b) for b in batches))
    results: dict[str, ArtifactEnrichment] = {}
    for br in batch_results:
        results.update(br)

    existing_paths = [a.path for a in file_arts]
    slugs = {
        a.path: (results[a.path].slug if a.path in results else None) for a in file_arts
    }
    rename_map = artifact_paths(existing_paths, slugs)
    updates = _build_enriched_updates(
        file_arts,
        contents_by_path,
        rename_map,
        results,
        max_text_bytes=int(storage_cfg["max_text_bytes"]),
    )

    readme_meta = results.get("README.md")
    req = internal.SaveEnrichedArtifactsRequest(blob_id=info.blob_id, artifacts=updates)
    if readme_meta is not None:
        req.blob_title = readme_meta.title
        req.blob_description = readme_meta.description
    elif len(file_arts) == 1 and (only_meta := results.get(file_arts[0].path)):
        req.blob_title = only_meta.title
        req.blob_description = only_meta.description

    return await stub.SaveEnrichedArtifacts(req)
