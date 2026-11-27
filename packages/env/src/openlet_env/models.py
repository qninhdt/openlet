"""Typed data models for openlet_env."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypedDict

from openlet_sdk.types import JSON, JsonObject, MutableJsonObject
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

type JSONObject = MutableJsonObject
type EnvMode = Literal["mock", "live"]

__all__ = [
    "JSON",
    "Account",
    "AgentManifest",
    "CacheEmbedding",
    "CacheEnrichment",
    "CacheInput",
    "CacheLegacyParser",
    "CacheMetadata",
    "CacheParseLimits",
    "CachePointMeta",
    "ConversationManifest",
    "Endpoints",
    "EnvMode",
    "EnvState",
    "EnvStatus",
    "GrantManifest",
    "JSONObject",
    "JsonObject",
    "NormalizedCacheInput",
    "PersistedAccount",
    "PrepareCacheReport",
    "RootManifest",
    "SeedResult",
    "SeededStorage",
    "SeededWorkspace",
    "SigningKeyMeta",
    "SyncMarker",
    "UserProfile",
    "WireMockRequest",
    "WorkspaceManifest",
    "WorkspaceSpec",
]


class UserProfile(BaseModel):
    """User profile entry in a dataset root manifest."""

    first_name: str
    last_name: str
    email: str | None = None


class RootManifest(BaseModel):
    """Root dataset manifest mapping user handles to profiles."""

    users: dict[str, UserProfile]


class AgentManifest(BaseModel):
    """Agent configuration entry in a workspace seed manifest."""

    name: str
    title: str
    owner: str | None = None
    operators: list[str] = Field(default_factory=list)
    description: str = ""
    system_prompt: str = ""
    model_id: str | None = None
    reasoning_effort: str | None = None
    appearance: dict[str, str] | None = None


class ConversationManifest(BaseModel):
    """Seeded direct conversation pairing between an agent and user."""

    agent: str
    user: str


class GrantManifest(BaseModel):
    """Storage permission grant entry in a workspace seed manifest."""

    storage: str
    actor: str
    role: Literal["editor", "viewer"]


class WorkspaceManifest(BaseModel):
    """Workspace seed manifest schema."""

    name: str
    owner: str
    members: list[str] = Field(default_factory=list)
    agents: dict[str, AgentManifest] = Field(default_factory=dict)
    conversations: dict[str, ConversationManifest] = Field(default_factory=dict)
    grants: list[GrantManifest] = Field(default_factory=list[GrantManifest])


class SyncMarker(BaseModel):
    """Persisted metadata tracking synced HuggingFace dataset workspaces."""

    repo_id: str = ""
    revision: str = ""
    full: bool = False
    workspaces: list[str] = Field(default_factory=list)


class SigningKeyMeta(BaseModel):
    """Persisted key ID metadata for the local RS256 signing key."""

    kid: str


class CacheEmbedding(TypedDict, total=False):
    """Embedding settings recorded in a `.letfs-cache` fingerprint."""

    model: str
    dimensions: int


class CacheEnrichment(TypedDict, total=False):
    """Enrichment settings recorded in a `.letfs-cache` fingerprint."""

    output_mode: Literal["tools", "json_schema", "text"]
    max_input_characters: int
    max_image_pixels: int
    image_max_side: int
    image_jpeg_quality: int


class CacheParseLimits(TypedDict, total=False):
    """Parser safety limits recorded in a `.letfs-cache` fingerprint."""

    max_pages: int
    max_page_pixels: int
    max_office_expanded_bytes: int
    max_spreadsheet_cells: int
    max_sheets: int
    max_output_bytes: int


@dataclass(frozen=True, slots=True)
class NormalizedCacheInput:
    """Normalized content-only cache fingerprint across cache format versions."""

    source: str
    sha256: str
    embedding: CacheEmbedding
    enrichment: CacheEnrichment
    prompt_label: str | None
    split_tokens: int | None
    limits: CacheParseLimits | None
    chunk_size_tokens: int | None
    chunk_overlap_tokens: int | None


class CacheLegacyParser(BaseModel):
    """Legacy format-6 parser configuration block inside cached metadata."""

    model_config = ConfigDict(extra="ignore")

    split_tokens: int | None = None
    limits: CacheParseLimits | None = None


class CacheInput(BaseModel):
    """Serialized cache fingerprint input settings."""

    model_config = ConfigDict(extra="ignore")

    format: int = 7
    source: str = ""
    sha256: str = ""
    embedding: CacheEmbedding = Field(default_factory=CacheEmbedding)
    enrichment: CacheEnrichment = Field(default_factory=CacheEnrichment)
    prompt_label: str | None = None
    split_tokens: int | None = None
    limits: CacheParseLimits | None = None
    parser: CacheLegacyParser | None = None
    chunk_size_tokens: int | None = None
    chunk_overlap_tokens: int | None = None

    def normalized(self) -> NormalizedCacheInput:
        """Normalize format 6 (legacy HF) and format 7 inputs to content-only keys."""
        return NormalizedCacheInput(
            source=self.source,
            sha256=self.sha256,
            embedding=self.embedding,
            enrichment=self.enrichment,
            prompt_label=self.prompt_label,
            split_tokens=self.split_tokens
            if self.split_tokens is not None
            else (self.parser.split_tokens if self.parser is not None else None),
            limits=self.limits
            if self.limits is not None
            else (self.parser.limits if self.parser is not None else None),
            chunk_size_tokens=self.chunk_size_tokens,
            chunk_overlap_tokens=self.chunk_overlap_tokens,
        )


class CachePointMeta(BaseModel):
    """Metadata for one cached Qdrant chunk payload."""

    path: str
    text: str
    kind: str
    title: str = ""
    chunk_index: int = 0


class CacheMetadata(BaseModel):
    """Serialized `.letfs-cache` `metadata.json` payload."""

    input: CacheInput = Field(default_factory=CacheInput)
    files: dict[str, list[str]] = Field(default_factory=dict)
    points: list[CachePointMeta] = Field(default_factory=list[CachePointMeta])


class WireMockRequest(BaseModel):
    """Recorded HTTP request entry from WireMock's ``/__admin/requests/find`` API."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    url: str = ""
    method: str = ""
    body: str = ""
    logged_date: int = Field(default=0, alias="loggedDate")


class PersistedAccount(BaseModel):
    """Persisted user identity stored in environment state."""

    user_id: str
    clerk_user_id: str
    email: str
    first_name: str
    last_name: str


class EnvState(BaseModel):
    """Persisted per-project environment metadata (.local/env/<project>/state.json)."""

    project: str
    mode: EnvMode
    namespace: str
    profiles: tuple[str, ...] = ()
    gateway_port: int
    rustfs_port: int
    wiremock_port: int
    seeded_workspaces: dict[str, str] = Field(default_factory=dict)
    accounts: dict[str, PersistedAccount] = Field(default_factory=dict)


class EnvStatus(TypedDict):
    """JSON-serializable summary returned by ``Environment.status()``."""

    project: str
    mode: EnvMode
    profiles: list[str]
    api_url: str
    object_store_url: str
    wiremock_url: str
    seeded_workspaces: dict[str, str]
    users: list[str]


class PrepareCacheReport(TypedDict):
    """Summary returned after preparing `.letfs-cache` artifacts."""

    prepared: list[str]
    count: int


@dataclass(frozen=True, slots=True)
class Endpoints:
    """Host-accessible loopback endpoints for a running Openlet stack."""

    api_url: str
    object_store_url: str
    wiremock_url: str
    postgres_port: int
    spicedb_address: str
    qdrant_port: int
    temporal_address: str


@dataclass(frozen=True, slots=True)
class Account:
    """A provisioned local user account with signing identity."""

    handle: str
    user_id: str
    clerk_user_id: str
    email: str
    first_name: str
    last_name: str
    token: str = ""


@dataclass(frozen=True, slots=True)
class WorkspaceSpec:
    """Parsed workspace seed specification from a dataset directory."""

    handle: str
    manifest: WorkspaceManifest
    storages: Mapping[str, Path]


@dataclass(frozen=True, slots=True)
class SeededStorage:
    """Identifiers and relative node paths for one seeded storage."""

    id: str
    root_node_id: str
    nodes: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class SeededWorkspace:
    """Identifiers produced after seeding one workspace."""

    handle: str
    workspace_id: str
    agents: Mapping[str, str]
    conversations: Mapping[str, str]
    storages: Mapping[str, SeededStorage]


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Result returned by Environment.seed()."""

    api_url: str
    object_store_url: str
    zed_token: str
    users: Mapping[str, Account]
    workspaces: Mapping[str, SeededWorkspace]
