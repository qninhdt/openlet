"""Temporal activities for enriching and indexing parsed blob artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openlet_api.letfs.v1 import internal_pb2 as internal
from temporalio import activity

from letfs_ingest.enrich import enrich
from letfs_ingest.index import index
from letfs_ingest.telemetry import ProcessingIdentity, heartbeats, stage

if TYPE_CHECKING:
    from openlet_sdk.config import Config

    from letfs_ingest.protocols import (
        BlobReader,
        IngestModels,
        LetFSProcessorStub,
        VectorStore,
    )


class Processor:
    """Temporal activity host for blob enrichment and vector indexing."""

    def __init__(
        self,
        stub: LetFSProcessorStub,
        s3: BlobReader,
        ai: IngestModels,
        qdrant: VectorStore,
        config: Config,
    ) -> None:
        self.stub = stub
        self.s3 = s3
        self.ai = ai
        self.qdrant = qdrant
        self.config = config

    @activity.defn(name="EnrichBlob")
    async def enrich(self, blob_id: str) -> None:
        """Run multimodal enrichment for ``blob_id`` if not already enriched or obsolete."""
        identity: ProcessingIdentity = {"blob_id": blob_id}
        async with heartbeats():
            with stage("enrich", identity):
                info = await self.stub.GetBlobArtifacts(
                    internal.BlobRequest(blob_id=blob_id)
                )
                if info.outcome.obsolete or info.outcome.stage in {"enriched", "ready"}:
                    return
                await enrich(info, self.stub, self.s3, self.ai, self.config)

    @activity.defn(name="IndexBlob")
    async def index(self, blob_id: str) -> None:
        """Embed and upsert Qdrant chunks for ``blob_id`` and mark indexing complete."""
        identity: ProcessingIdentity = {"blob_id": blob_id}
        async with heartbeats():
            with stage("index", identity):
                info = await self.stub.GetBlobArtifacts(
                    internal.BlobRequest(blob_id=blob_id)
                )
                if info.outcome.obsolete or info.outcome.stage == "ready":
                    return
                await index(info, self.ai, self.qdrant, self.config)
                await self.stub.CompleteBlobIndex(internal.BlobRequest(blob_id=blob_id))
