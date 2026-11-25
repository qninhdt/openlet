from typing import TYPE_CHECKING

from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_sdk.config import Config
from qdrant_client import AsyncQdrantClient
from temporalio import activity

if TYPE_CHECKING:
    from openlet_api.letfs.v1 import internal_pb2_grpc

from .enrich import enrich
from .index import index
from .providers import Models
from .storage import S3Store
from .telemetry import ProcessingIdentity, heartbeats, stage


class Processor:
    def __init__(
        self,
        stub: "internal_pb2_grpc.LetFSInternalServiceAsyncStub",
        s3: S3Store,
        ai: Models,
        qdrant: AsyncQdrantClient,
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
