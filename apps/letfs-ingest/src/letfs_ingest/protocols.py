"""Structural protocols for letfs-ingest service dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence
    from pathlib import Path

    from datalab_sdk import ConvertOptions  # pyright: ignore[reportMissingTypeStubs]
    from openlet_api.letfs.v1 import internal_pb2 as internal
    from qdrant_client import models

    from letfs_ingest.providers import ArtifactEnrichment, EnrichItem


class BlobReader(Protocol):
    """Async object storage reader."""

    async def get_bytes(self, key: str, limit: int) -> bytes:
        """Read at most ``limit`` bytes from ``key``."""
        ...


class BlobStore(BlobReader, Protocol):
    """Async object storage reader and writer."""

    async def download_to_file(self, key: str, target: Path, limit: int) -> int:
        """Download ``key`` into ``target`` up to ``limit`` bytes."""
        ...

    async def put_bytes(self, key: str, data: bytes, media_type: str) -> str:
        """Upload ``data`` to ``key`` and return its base64 CRC32C checksum."""
        ...


class EnrichmentModels(Protocol):
    """Multimodal enrichment model client."""

    async def describe_batch(
        self, items: Sequence[EnrichItem]
    ) -> dict[str, ArtifactEnrichment]:
        """Generate structured titles, descriptions, and slugs for ``items``."""
        ...


class EmbeddingModels(Protocol):
    """Embedding model client."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed ``texts`` into dense float vectors."""
        ...


class IngestModels(EnrichmentModels, EmbeddingModels, Protocol):
    """Combined enrichment and embedding model client."""


class DatalabResult(Protocol):
    """Conversion outcome returned by the Datalab SDK."""

    @property
    def success(self) -> bool:
        """Return whether the Datalab conversion succeeded."""
        ...


class DatalabClient(Protocol):
    """Async Datalab document conversion client."""

    async def convert(
        self,
        *,
        file_url: str | None = None,
        file_path: Path | None = None,
        options: ConvertOptions | None = None,
        stream_response_to: Path | None = None,
    ) -> DatalabResult:
        """Convert a document from URL or local path and stream JSON to disk."""
        ...


class VectorStore(Protocol):
    """Async Qdrant vector store operations used by ingest."""

    async def delete(
        self,
        *,
        collection_name: str,
        points_selector: models.PointsSelector,
        wait: bool = True,
    ) -> object:
        """Delete points matching ``points_selector`` from ``collection_name``."""
        ...

    async def upsert(
        self,
        *,
        collection_name: str,
        points: Sequence[models.PointStruct],
        wait: bool = True,
    ) -> object:
        """Upsert ``points`` into ``collection_name``."""
        ...


class LetFSEnrichStub(Protocol):
    """gRPC stub subset for saving enriched artifact metadata."""

    def SaveEnrichedArtifacts(  # noqa: N802  # Matches generated gRPC service method name.
        self, request: internal.SaveEnrichedArtifactsRequest, /
    ) -> Awaitable[internal.BlobProcessingOutcome]:
        """Persist enriched titles, descriptions, and rewritten Markdown."""
        ...


class LetFSParseStub(Protocol):
    """gRPC stub subset for loading blob info and saving parsed artifacts."""

    def GetBlobArtifacts(  # noqa: N802  # Matches generated gRPC service method name.
        self, request: internal.BlobRequest, /
    ) -> Awaitable[internal.GetBlobArtifactsResponse]:
        """Fetch blob metadata and existing artifacts."""
        ...

    def SaveParsedArtifacts(  # noqa: N802  # Matches generated gRPC service method name.
        self, request: internal.SaveParsedArtifactsRequest, /
    ) -> Awaitable[internal.BlobProcessingOutcome]:
        """Persist parsed artifacts for a blob."""
        ...


class LetFSProcessorStub(LetFSEnrichStub, Protocol):
    """gRPC stub subset used by enrichment and indexing activities."""

    def GetBlobArtifacts(  # noqa: N802  # Matches generated gRPC service method name.
        self, request: internal.BlobRequest, /
    ) -> Awaitable[internal.GetBlobArtifactsResponse]:
        """Fetch blob metadata and parsed artifacts."""
        ...

    def CompleteBlobIndex(  # noqa: N802  # Matches generated gRPC service method name.
        self, request: internal.BlobRequest, /
    ) -> Awaitable[internal.BlobProcessingOutcome]:
        """Mark blob vector indexing as complete."""
        ...
