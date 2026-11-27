"""Typed data models for openlet_env."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

from openlet_sdk.types import JSON, JsonObject, MutableJsonObject
from pydantic import BaseModel, ConfigDict, Field

type JSONObject = MutableJsonObject
type EnvMode = Literal["mock", "live"]

__all__ = [
    "Account",
    "AgentManifest",
    "CacheInput",
    "CacheLegacyParser",
    "CacheMetadata",
    "CachePointMeta",
    "ConversationManifest",
    "Endpoints",
    "EnvMode",
    "EnvState",
    "EnvStatus",
    "GrantManifest",
    "JSON",
    "JSONObject",
    "JsonObject",
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
    first_name: str
    last_name: str
    email: str | None = None


class RootManifest(BaseModel):
    users: dict[str, UserProfile]


class AgentManifest(BaseModel):
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
    agent: str
    user: str


class GrantManifest(BaseModel):
    storage: str
    actor: str
    role: Literal["editor", "viewer"]


class WorkspaceManifest(BaseModel):
    name: str
    owner: str
    members: list[str] = Field(default_factory=list)
    agents: dict[str, AgentManifest] = Field(default_factory=dict)
    conversations: dict[str, ConversationManifest] = Field(default_factory=dict)
    grants: list[GrantManifest] = Field(default_factory=list[GrantManifest])


class SyncMarker(BaseModel):
    repo_id: str = ""
    revision: str = ""
    full: bool = False
    workspaces: list[str] = Field(default_factory=list)


class SigningKeyMeta(BaseModel):
    kid: str


class CacheLegacyParser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    split_tokens: int | None = None
    limits: dict[str, int] | None = None


class CacheInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format: int = 7
    source: str = ""
    sha256: str = ""
    embedding: dict[str, str | int] = Field(default_factory=dict)
    enrichment: dict[str, str | int] = Field(default_factory=dict)
    prompt_label: str | None = None
    split_tokens: int | None = None
    limits: dict[str, int] | None = None
    parser: CacheLegacyParser | None = None
    chunk_size_tokens: int | None = None
    chunk_overlap_tokens: int | None = None

    def normalized(self) -> dict[str, object]:
        """Normalize format 6 (legacy HF) and format 7 inputs to content-only keys."""
        return {
            "source": self.source,
            "sha256": self.sha256,
            "embedding": self.embedding,
            "enrichment": self.enrichment,
            "prompt_label": self.prompt_label,
            "split_tokens": self.split_tokens
            if self.split_tokens is not None
            else (self.parser.split_tokens if self.parser is not None else None),
            "limits": self.limits
            if self.limits is not None
            else (self.parser.limits if self.parser is not None else None),
            "chunk_size_tokens": self.chunk_size_tokens,
            "chunk_overlap_tokens": self.chunk_overlap_tokens,
        }


class CachePointMeta(BaseModel):
    path: str
    text: str
    kind: str
    title: str = ""
    chunk_index: int = 0


class CacheMetadata(BaseModel):
    input: CacheInput = Field(default_factory=CacheInput)
    files: dict[str, list[str]] = Field(default_factory=dict)
    points: list[CachePointMeta] = Field(default_factory=list[CachePointMeta])


class WireMockRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    url: str = ""
    method: str = ""
    body: str = ""
    loggedDate: int = 0


class PersistedAccount(BaseModel):
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
    project: str
    mode: EnvMode
    profiles: list[str]
    api_url: str
    object_store_url: str
    wiremock_url: str
    seeded_workspaces: dict[str, str]
    users: list[str]


class PrepareCacheReport(TypedDict):
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
    storages: dict[str, Path]


@dataclass(frozen=True, slots=True)
class SeededStorage:
    """Identifiers and relative node paths for one seeded storage."""

    id: str
    root_node_id: str
    nodes: dict[str, str]


@dataclass(frozen=True, slots=True)
class SeededWorkspace:
    """Identifiers produced after seeding one workspace."""

    handle: str
    workspace_id: str
    agents: dict[str, str]
    conversations: dict[str, str]
    storages: dict[str, SeededStorage]


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Result returned by Environment.seed()."""

    api_url: str
    object_store_url: str
    zed_token: str
    users: dict[str, Account]
    workspaces: dict[str, SeededWorkspace]
