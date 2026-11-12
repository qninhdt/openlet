from openlet_api.letfs.v1 import internal_pb2 as pb
from temporalio import activity

from .artifacts import heartbeats
from .enrich import enrich
from .index import index
from .telemetry import stage


class Processor:
    def __init__(self, stub, http, ai, qdrant, config):
        self.stub, self.http, self.ai = stub, http, ai
        self.qdrant, self.config = qdrant, config

    @activity.defn(name="EnrichAndIndex")
    async def run(self, request: dict) -> None:
        async with heartbeats():
            identity = {"file_id": request["file_id"], "version": request["version"]}
            query = pb.ProcessingRequest(**identity)
            source = await self.stub.GetProcessingInput(query, timeout=30)
            if source.outcome.obsolete or source.outcome.stage == "ready":
                return
            if source.outcome.stage == "parsed":
                with stage("enrich", identity):
                    result = await self.stub.CommitEnrichment(
                        await enrich(source, identity, self.ai, self.http, self.config["services"]["letfs"]["max_blob_bytes"]), timeout=60,
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
