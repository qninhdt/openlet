"""Structural protocols for letfs-ingest service dependencies."""

from __future__ import annotations

from collections.abc import Awaitable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from openlet_api.letfs.v1 import internal_pb2 as internal
from qdrant_client import models

if TYPE_CHECKING:
    from datalab_sdk import ConvertOptions  # pyright: ignore[reportMissingTypeStubs]

    from .providers import ArtifactEnrichment, EnrichItem


class BlobReader(Protocol):
    async def get_bytes(self, key: str, limit: int) -> bytes: ...


class BlobStore(BlobReader, Protocol):
    async def download_to_file(self, key: str, target: Path, limit: int) -> int: ...
    async def put_bytes(self, key: str, data: bytes, media_type: str) -> str: ...


class EnrichmentModels(Protocol):
    async def describe_batch(
        self, items: Sequence[EnrichItem]
    ) -> dict[str, ArtifactEnrichment]: ...


class EmbeddingModels(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class IngestModels(EnrichmentModels, EmbeddingModels, Protocol):
    pass


class DatalabResult(Protocol):
    @property
    def success(self) -> bool: ...


class DatalabClient(Protocol):
    async def convert(
        self,
        *,
        file_url: str | None = None,
        file_path: Path | None = None,
        options: ConvertOptions | None = None,
        stream_response_to: Path | None = None,
    ) -> DatalabResult: ...


class VectorStore(Protocol):
    async def delete(
        self,
        *,
        collection_name: str,
        points_selector: models.PointsSelector,
        wait: bool = True,
    ) -> object: ...

    async def upsert(
        self,
        *,
        collection_name: str,
        points: Sequence[models.PointStruct],
        wait: bool = True,
    ) -> object: ...


class LetFSEnrichStub(Protocol):
    def SaveEnrichedArtifacts(
        self, request: internal.SaveEnrichedArtifactsRequest, /
    ) -> Awaitable[internal.BlobProcessingOutcome]: ...


class LetFSParseStub(Protocol):
    def GetBlobArtifacts(
        self, request: internal.BlobRequest, /
    ) -> Awaitable[internal.GetBlobArtifactsResponse]: ...

    def SaveParsedArtifacts(
        self, request: internal.SaveParsedArtifactsRequest, /
    ) -> Awaitable[internal.BlobProcessingOutcome]: ...


class LetFSProcessorStub(LetFSEnrichStub, Protocol):
    def GetBlobArtifacts(
        self, request: internal.BlobRequest, /
    ) -> Awaitable[internal.GetBlobArtifactsResponse]: ...

    def CompleteBlobIndex(
        self, request: internal.BlobRequest, /
    ) -> Awaitable[internal.BlobProcessingOutcome]: ...
