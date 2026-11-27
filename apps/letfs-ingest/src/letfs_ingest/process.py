from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_sdk.config import Config
from temporalio import activity

from .enrich import enrich
from .index import index
from .protocols import BlobReader, IngestModels, LetFSProcessorStub, VectorStore
from .telemetry import ProcessingIdentity, heartbeats, stage


class Processor:
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
