"""Typed data models for openlet_env."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

type JSON = None | bool | int | float | str | list[JSON] | dict[str, JSON]
type JSONObject = dict[str, JSON]
type EnvMode = Literal["mock", "live"]


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
    manifest: JSONObject
    storages: dict[str, Path]


@dataclass(frozen=True, slots=True)
class SeededWorkspace:
    """Identifiers produced after seeding one workspace."""

    handle: str
    workspace_id: str
    agents: dict[str, str]
    conversations: dict[str, str]
    storages: dict[str, dict[str, object]]


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Result returned by Environment.seed()."""

    api_url: str
    object_store_url: str
    zed_token: str
    users: dict[str, Account]
    workspaces: dict[str, SeededWorkspace]


@dataclass(slots=True)
class EnvState:
    """Persisted per-project environment metadata (.local/env/<project>/state.json)."""

    project: str
    mode: EnvMode
    namespace: str
    profiles: tuple[str, ...]
    gateway_port: int
    rustfs_port: int
    wiremock_port: int
    seeded_workspaces: dict[str, str] = field(default_factory=dict[str, str])
    accounts: dict[str, dict[str, str]] = field(
        default_factory=dict[str, dict[str, str]]
    )
