from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openlet_api.letfs.v1.internal_pb2_grpc import LetFSInternalServiceAsyncStub


import httpx
from langfuse import propagate_attributes
from openlet_api.letfs.v1 import internal_pb2 as pb
from openlet_sdk.config import Config
from qdrant_client import AsyncQdrantClient
from temporalio import activity

from .artifacts import heartbeats
from .enrich import enrich
from .index import index
from .providers import Models
from .telemetry import ProcessingIdentity, stage


class Processor:
    def __init__(
        self,
        stub: LetFSInternalServiceAsyncStub,
        http: httpx.AsyncClient,
        ai: Models,
        qdrant: AsyncQdrantClient,
        config: Config,
    ) -> None:
        self.stub, self.http, self.ai = stub, http, ai
        self.qdrant, self.config = qdrant, config

    @activity.defn(name="EnrichAndIndex")
    async def run(self, request: ProcessingIdentity) -> None:
        with propagate_attributes(
            metadata={
                "file_id": request["file_id"],
                "source_version": str(request["version"]),
            }
        ):
            async with heartbeats():
                identity: ProcessingIdentity = {
                    "file_id": request["file_id"],
                    "version": request["version"],
                }
                query = pb.ProcessingRequest(**identity)
                source = await self.stub.GetProcessingInput(query, timeout=30)
                if source.outcome.obsolete or source.outcome.stage == "ready":
                    return
                if source.outcome.stage == "parsed":
                    with stage("enrich", identity):
                        result = await self.stub.CommitEnrichment(
                            await enrich(
                                source,
                                identity,
                                self.ai,
                                self.http,
                                self.config["services"]["letfs"]["max_blob_bytes"],
                            ),
                            timeout=60,
                        )
                    if result.obsolete:
                        return
                    source = await self.stub.GetProcessingInput(query, timeout=30)
                if source.outcome.obsolete or source.outcome.stage != "enriched":
                    return
                if source.allow_indexing:
                    with stage("index", identity):
                        await index(source, identity, self.ai, self.qdrant, self.config)
                await self.stub.CompleteIndex(query, timeout=30)
