"""Fast batch workspace seeder, unseeder, resetter, and `.letfs-cache` builder."""

from __future__ import annotations

import asyncio
import base64
import re
import struct
import sys
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, cast
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

import boto3
import google_crc32c
import grpc
import psycopg
from authzed.api.v1 import (
    DeleteRelationshipsRequest,
    ObjectReference,
    Relationship,
    RelationshipFilter,
    RelationshipUpdate,
    SubjectReference,
    WriteRelationshipsRequest,
)
from authzed.api.v1.permission_service_pb2_grpc import PermissionsServiceStub
from botocore.config import Config as S3ClientConfig
from openlet_sdk.config import Config, DatabaseSettings
from openlet_sdk.file_types import classify_file
from openlet_sdk.types import is_object_list
from psycopg import sql
from psycopg.rows import TupleRow
from psycopg.types.json import Jsonb
from qdrant_client import QdrantClient, models
from qdrant_client.conversions.common_types import PointId
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from . import cache
from .auth import LocalAuth
from .dataset import iter_seed_files, referenced_users
from .models import (
    Account,
    CacheInput,
    CachePointMeta,
    Endpoints,
    PrepareCacheReport,
    SeededStorage,
    SeededWorkspace,
    SeedResult,
    UserProfile,
    WorkspaceSpec,
)
from .wiremock import WireMockClient

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class _WorkspaceRow(NamedTuple):
    id: UUID
    name: str
    state: str


class _QuotaRow(NamedTuple):
    workspace_id: UUID
    quota_bytes: int
    used_bytes: int


class _StorageRow(NamedTuple):
    id: UUID
    workspace_id: UUID
    name: str
    visibility: str
    root_node_id: UUID
    allow_blob_files: bool
    allow_indexing: bool


class _NodeRow(NamedTuple):
    id: UUID
    storage_id: UUID
    parent_id: UUID | None
    name: str
    kind: str


class _BlobRow(NamedTuple):
    id: UUID
    workspace_id: UUID
    object_key: str
    size_bytes: int
    media_type: str
    checksum: str
    source_name: str
    processing_stage: str | None
    title: str
    description: str


class _FileRow(NamedTuple):
    node_id: UUID
    version: int
    blob_id: UUID | None
    text_content: str | None
    size_bytes: int
    media_type: str


class _ArtifactRow(NamedTuple):
    id: UUID
    blob_id: UUID
    path: str
    parent_path: str
    kind: str
    media_type: str
    size_bytes: int
    checksum: str
    object_key: str | None
    text_content: str | None
    title: str
    description: str
    indexable: bool


class _LetaRow(NamedTuple):
    id: UUID
    workspace_id: UUID
    storage_id: UUID
    state: str


class _AgentRow(NamedTuple):
    id: UUID
    leta_id: UUID
    name: str
    title: str
    description: str
    custom_instructions: str
    model_id: str | None
    reasoning_effort: str | None
    handle: str
    appearance: Jsonb


class _ConversationRow(NamedTuple):
    id: UUID
    workspace_id: UUID
    type: str
    dm_key: str
    storage_id: UUID
    storage_ready: bool
    created_by: UUID


class _ConversationMemberRow(NamedTuple):
    conversation_id: UUID
    workspace_id: UUID
    actor_type: str
    actor_id: UUID
    role: str


def _resolve(value: str, env: Mapping[str, str]) -> str:
    if not (value.startswith("${") and value.endswith("}")):
        raise ValueError(f"expected ${{ENV_VAR}} reference, got {value!r}")
    return env[value[2:-1]]


def _batches[T](rows: Sequence[T], size: int = 500) -> Iterator[Sequence[T]]:
    for offset in range(0, len(rows), size):
        yield rows[offset : offset + size]


def _as_uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


def crc32c_base64(data: bytes) -> str:
    """Hardware/C-accelerated CRC32C encoded as AWS S3 base64 checksum."""
    checksum = cast("int", google_crc32c.value(data))  # pyright: ignore[reportUnknownMemberType]
    return base64.b64encode(struct.pack(">I", checksum)).decode("ascii")


def _graph_relation(
    resource: str,
    resource_id: UUID,
    relation: str,
    subject: str,
    subject_id: UUID,
    subject_relation: str = "",
) -> Relationship:
    return Relationship(
        resource=ObjectReference(object_type=resource, object_id=str(resource_id)),
        relation=relation,
        subject=SubjectReference(
            object=ObjectReference(object_type=subject, object_id=str(subject_id)),
            optional_relation=subject_relation,
        ),
    )


def _copy_rows(
    db: psycopg.Connection[TupleRow],
    table: str,
    columns: str,
    rows: Sequence[tuple[object, ...]],
) -> None:
    if not rows:
        return
    stmt = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns.split())),
    )
    with db.cursor().copy(stmt) as stream:
        for row in rows:
            stream.write_row(row)


def _point_filter(key: str, value: str) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key=key, match=models.MatchValue(value=value))]
    )


class ServiceConnections:
    """Direct host connections to Postgres, SpiceDB, Qdrant, and RustFS."""

    def __init__(
        self,
        scope: ExitStack,
        *,
        config: Config,
        env: Mapping[str, str],
        endpoints: Endpoints,
        has_leta: bool,
    ) -> None:
        self.config = config
        self.env = env
        self.endpoints = endpoints
        pg = config["dependencies"]["postgres"]

        def connect(settings: DatabaseSettings) -> psycopg.Connection[TupleRow]:
            return scope.enter_context(
                psycopg.connect(
                    host="127.0.0.1",
                    port=endpoints.postgres_port,
                    dbname=settings["name"],
                    user=settings["user"],
                    password=_resolve(settings["password"], env),
                    sslmode=pg["sslmode"],
                    autocommit=True,
                    connect_timeout=10,
                )
            )

        self.platform = connect(config["services"]["platform"]["database"])
        self.letfs = connect(config["services"]["letfs"]["database"])
        chat_cfg = config["services"].get("chat")
        self.chat = connect(chat_cfg["database"]) if chat_cfg is not None else None
        self.leta = (
            connect(config["services"]["leta"]["database"]) if has_leta else None
        )

        spice = config["dependencies"]["spicedb"]
        channel = scope.enter_context(grpc.insecure_channel(endpoints.spicedb_address))
        self.graph = PermissionsServiceStub(channel)
        self.graph_headers = (
            ("authorization", "Bearer " + _resolve(spice["key"], env)),
        )

        qdrant_cfg = config["dependencies"]["qdrant"]
        self.qdrant = QdrantClient(
            host="127.0.0.1",
            grpc_port=endpoints.qdrant_port,
            prefer_grpc=True,
            api_key=_resolve(qdrant_cfg["api_key"], env),
            https=qdrant_cfg["tls"],
            check_compatibility=False,
        )
        scope.callback(self.qdrant.close)
        self.collection = qdrant_cfg["collection"]

        s3_cfg = config["dependencies"]["s3"]
        self.bucket = s3_cfg["bucket"]
        self.s3: S3Client = boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "s3",
            endpoint_url=endpoints.object_store_url,
            region_name=s3_cfg["region"],
            aws_access_key_id=_resolve(s3_cfg["access_key_id"], env),
            aws_secret_access_key=_resolve(s3_cfg["secret_access_key"], env),
            config=S3ClientConfig(s3={"addressing_style": "path"}),
        )
        scope.callback(self.s3.close)


def _put_objects(services: ServiceConnections, objects: Mapping[str, Path]) -> None:
    if not objects:
        return

    def _put(item: tuple[str, Path]) -> None:
        key, path = item
        _, media = classify_file(path.name)
        with path.open("rb") as stream:
            services.s3.put_object(
                Bucket=services.bucket, Key=key, Body=stream, ContentType=media
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        for _ in pool.map(_put, objects.items()):
            pass


@dataclass(slots=True)
class _ColdBlob:
    blob_id: UUID
    path: Path
    settings: CacheInput
    parse: bool


@dataclass(slots=True)
class _SeedBatch:
    services: ServiceConnections
    specs: Sequence[WorkspaceSpec]
    users: dict[str, UUID]
    output: dict[str, SeededWorkspace] = field(
        default_factory=dict[str, SeededWorkspace]
    )
    workspaces: list[_WorkspaceRow] = field(default_factory=list[_WorkspaceRow])
    quotas: list[_QuotaRow] = field(default_factory=list[_QuotaRow])
    storages: list[_StorageRow] = field(default_factory=list[_StorageRow])
    nodes: list[_NodeRow] = field(default_factory=list[_NodeRow])
    blobs: list[_BlobRow] = field(default_factory=list[_BlobRow])
    file_rows: list[_FileRow] = field(default_factory=list[_FileRow])
    artifacts: list[_ArtifactRow] = field(default_factory=list[_ArtifactRow])
    letas: list[_LetaRow] = field(default_factory=list[_LetaRow])
    agents: list[_AgentRow] = field(default_factory=list[_AgentRow])
    conversations: list[_ConversationRow] = field(
        default_factory=list[_ConversationRow]
    )
    conversation_members: list[_ConversationMemberRow] = field(
        default_factory=list[_ConversationMemberRow]
    )
    relations: list[Relationship] = field(default_factory=list[Relationship])
    objects: dict[str, Path] = field(default_factory=dict[str, Path])
    points: list[models.PointStruct] = field(default_factory=list[models.PointStruct])

    def plan(self) -> None:
        for spec in self.specs:
            self._plan_workspace(spec)

    def _plan_workspace(self, spec: WorkspaceSpec) -> None:
        workspace = uuid4()
        data = spec.manifest
        name = data.name
        if not name.strip() or len(name) > 200:
            raise ValueError(f"invalid workspace name for {spec.handle}")
        self.workspaces.append(_WorkspaceRow(workspace, name, "active"))

        owner_handle = data.owner
        member_handles = data.members
        owner = self.users[owner_handle]
        members = {self.users[member] for member in member_handles} - {owner}
        platform = self.services.config["services"]["platform"]
        if len(members) + 1 > platform["max_members"]:
            raise ValueError(
                f"{spec.handle} exceeds max_members ({platform['max_members']})"
            )

        self.relations.append(
            _graph_relation("workspace", workspace, "owner", "user", owner)
        )
        for member in sorted(members):
            self.relations.append(
                _graph_relation("workspace", workspace, "member", "user", member)
            )

        storages: dict[str, SeededStorage] = {}
        self._plan_storage(
            workspace, spec, storages, "shared", "Shared", "workspace", workspace
        )
        for handle in dict.fromkeys([owner_handle, *member_handles]):
            self._plan_storage(
                workspace,
                spec,
                storages,
                f"personal/{handle}",
                "Personal",
                "user",
                self.users[handle],
            )

        agents_map: dict[str, UUID] = {}
        for handle, agent in data.agents.items():
            agent_id = agents_map[handle] = uuid4()
            agent_owner = self.users[agent.owner or owner_handle]
            operators = {self.users[user] for user in agent.operators}
            agent_name = agent.name
            title = agent.title
            if (
                not agent_name.strip()
                or not title.strip()
                or max(len(agent_name), len(title)) > 255
            ):
                raise ValueError(f"invalid Leta name or title for {handle}")
            storage_id, _ = self._plan_storage(
                workspace,
                spec,
                storages,
                f"personal/{handle}",
                agent_name,
                "agent",
                agent_id,
            )
            self.letas.append(_LetaRow(agent_id, workspace, storage_id, "active"))
            agent_handle = "-the-".join(
                re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
                for text in (agent_name, title)
            )
            self.agents.append(
                _AgentRow(
                    agent_id,
                    agent_id,
                    agent_name,
                    title,
                    agent.description,
                    agent.system_prompt,
                    agent.model_id,
                    agent.reasoning_effort,
                    agent_handle,
                    Jsonb(agent.appearance or {"shape": "squircle", "color": "vert"}),
                )
            )
            self.relations.extend(
                (
                    _graph_relation("workspace", workspace, "agent", "agent", agent_id),
                    _graph_relation(
                        "agent", agent_id, "workspace", "workspace", workspace
                    ),
                    _graph_relation("agent", agent_id, "owner", "user", agent_owner),
                )
            )
            for operator in sorted(operators):
                self.relations.append(
                    _graph_relation("agent", agent_id, "operator", "user", operator)
                )

        conversations_out: dict[str, str] = {}
        for handle, pair in data.conversations.items():
            agent_handle = pair.agent
            agent_id = agents_map[agent_handle]
            user_id = self.users[pair.user]
            spec_agent = data.agents[agent_handle]
            allowed_actors = {
                spec_agent.owner or owner_handle,
                *spec_agent.operators,
            }
            if pair.user not in allowed_actors:
                raise ValueError(f"actor cannot use Leta in conversation {handle}")
            conversation = uuid5(agent_id, f"user/{user_id}")
            storage_id, _ = self._plan_storage(
                workspace,
                spec,
                storages,
                f"conversation/{handle}",
                f"Conversation · {spec_agent.name} · user {user_id} · {conversation}",
                "conversation",
                conversation,
            )
            conversations_out[handle] = str(conversation)
            dm_pair = sorted((f"agent:{agent_id}", f"user:{user_id}"))
            dm_key = f"{dm_pair[0]}|{dm_pair[1]}"
            self.conversations.append(
                _ConversationRow(
                    conversation, workspace, "dm", dm_key, storage_id, True, user_id
                )
            )
            self.conversation_members.extend(
                (
                    _ConversationMemberRow(
                        conversation, workspace, "agent", agent_id, "member"
                    ),
                    _ConversationMemberRow(
                        conversation, workspace, "user", user_id, "member"
                    ),
                )
            )
            self.relations.extend(
                (
                    _graph_relation(
                        "conversation",
                        conversation,
                        "workspace",
                        "workspace",
                        workspace,
                    ),
                    _graph_relation(
                        "conversation", conversation, "agent_member", "agent", agent_id
                    ),
                    _graph_relation(
                        "conversation", conversation, "member", "agent", agent_id
                    ),
                    _graph_relation(
                        "conversation", conversation, "member", "user", user_id
                    ),
                )
            )

        for grant in data.grants:
            actor = grant.actor
            scope_id = UUID(storages[grant.storage].id)
            if actor in agents_map:
                self.relations.append(
                    _graph_relation(
                        "storage", scope_id, grant.role, "agent", agents_map[actor]
                    )
                )
            else:
                self.relations.append(
                    _graph_relation(
                        "storage", scope_id, grant.role, "user", self.users[actor]
                    )
                )

        self.output[spec.handle] = SeededWorkspace(
            handle=spec.handle,
            workspace_id=str(workspace),
            agents={h: str(aid) for h, aid in agents_map.items()},
            conversations=conversations_out,
            storages=storages,
        )

    def _plan_storage(
        self,
        workspace: UUID,
        spec: WorkspaceSpec,
        output: dict[str, SeededStorage],
        key: str,
        name: str,
        owner_type: str,
        owner: UUID,
    ) -> tuple[UUID, UUID]:
        storage = uuid5(owner, "storage") if owner_type == "conversation" else uuid4()
        root = uuid5(owner, "root") if owner_type == "conversation" else uuid4()
        public = owner_type == "workspace"
        self.storages.append(
            _StorageRow(
                storage,
                workspace,
                name,
                "public" if public else "private",
                root,
                True,
                True,
            )
        )
        self.nodes.append(_NodeRow(root, storage, None, "", "directory"))
        self.relations.append(
            _graph_relation("storage", storage, "workspace", "workspace", workspace)
        )
        if public:
            self.relations.append(
                _graph_relation(
                    "storage", storage, "public_workspace", "workspace", workspace
                )
            )
        if owner_type == "conversation":
            self.relations.append(
                _graph_relation("storage", storage, "conversation", owner_type, owner)
            )
        else:
            self.relations.append(
                _graph_relation(
                    "storage",
                    storage,
                    "owner",
                    owner_type,
                    owner,
                    "owner" if public else "",
                )
            )
            if owner_type == "agent":
                self.relations.append(
                    _graph_relation(
                        "storage", storage, "owner", "agent", owner, "owner"
                    )
                )

        paths: dict[Path, UUID] = {Path("."): root}
        if path := spec.storages.get(key):
            for entry in iter_seed_files(path):
                relative = entry.relative_to(path)
                parent = paths[relative.parent]
                node, blob_meta = self._plan_node(workspace, storage, parent, entry)
                paths[relative] = node
                if blob_meta is not None:
                    blob_id, media, size, checksum, object_key = blob_meta
                    if entry.suffix.lower() in cache.INDEXED:
                        self._plan_ingest(
                            workspace, blob_id, entry, size, media, checksum, object_key
                        )
                    else:
                        self.blobs.append(
                            _BlobRow(
                                blob_id,
                                workspace,
                                object_key,
                                size,
                                media,
                                checksum,
                                entry.name,
                                None,
                                "",
                                "",
                            )
                        )
        output[key] = SeededStorage(
            id=str(storage),
            root_node_id=str(root),
            nodes={
                p.as_posix(): str(nid) for p, nid in paths.items() if p != Path(".")
            },
        )
        return storage, root

    def _plan_node(
        self, workspace: UUID, storage: UUID, parent: UUID, path: Path
    ) -> tuple[UUID, tuple[UUID, str, int, str, str] | None]:
        letfs_cfg = self.services.config["services"]["letfs"]
        if len(path.name.encode("utf-8")) > 255:
            raise ValueError(f"file name exceeds 255 bytes: {path}")
        node = uuid4()
        is_dir = path.is_dir()
        self.nodes.append(
            _NodeRow(
                node, storage, parent, path.name, "directory" if is_dir else "file"
            )
        )
        if is_dir:
            return node, None
        kind, media = classify_file(path.name)
        size = path.stat().st_size
        if kind == "unsupported":
            raise ValueError(f"unsupported file: {path}")
        limit = (
            letfs_cfg["max_text_bytes"]
            if kind == "text"
            else letfs_cfg["max_blob_bytes"]
        )
        if size > limit:
            raise ValueError(f"file exceeds configured size limit: {path}")
        if kind == "text":
            body = path.read_bytes().decode("utf-8")
            if "\0" in body:
                raise ValueError(f"text contains NUL: {path}")
            self.file_rows.append(_FileRow(node, 1, None, body, size, media))
            return node, None
        blob_id = uuid4()
        object_key = f"workspaces/{workspace}/blobs/{blob_id}/source"
        self.objects[object_key] = path
        checksum = crc32c_base64(path.read_bytes())
        self.file_rows.append(_FileRow(node, 1, blob_id, None, size, media))
        return node, (blob_id, media, size, checksum, object_key)

    def _plan_ingest(
        self,
        workspace: UUID,
        blob_id: UUID,
        path: Path,
        size: int,
        media: str,
        checksum: str,
        object_key: str,
    ) -> None:
        saved = cache.read_cache(path, self.services.config)
        if saved is None:
            raise ValueError(
                f"missing or stale ingest cache for {path}. Run `openlet-env prepare-cache`."
            )

        file_meta = saved.metadata.files
        root_meta = file_meta.get(".", ["", ""])
        self.blobs.append(
            _BlobRow(
                blob_id,
                workspace,
                object_key,
                size,
                media,
                checksum,
                path.name,
                "ready",
                root_meta[0] if len(root_meta) > 0 else "",
                root_meta[1] if len(root_meta) > 1 else "",
            )
        )
        artifact_root = saved.folder / "artifacts"
        all_entries = list(iter_seed_files(artifact_root))
        has_parts = any(
            e.is_file()
            and e.suffix == ".md"
            and e.relative_to(artifact_root).as_posix() != "README.md"
            for e in all_entries
        )
        for entry in all_entries:
            rel = entry.relative_to(artifact_root)
            rel_posix = rel.as_posix()
            parent_posix = "" if rel.parent == Path(".") else rel.parent.as_posix()
            art_id = uuid4()
            if entry.is_dir():
                self.artifacts.append(
                    _ArtifactRow(
                        art_id,
                        blob_id,
                        rel_posix,
                        parent_posix,
                        "directory",
                        "",
                        0,
                        "",
                        None,
                        None,
                        "",
                        "",
                        False,
                    )
                )
                continue
            kind, art_media = classify_file(entry.name)
            art_size = entry.stat().st_size
            art_meta = file_meta.get(rel_posix, ["", ""])
            title = art_meta[0] if len(art_meta) > 0 else ""
            desc = art_meta[1] if len(art_meta) > 1 else ""
            if kind == "text":
                text_body = entry.read_bytes().decode("utf-8")
                indexable = (rel_posix != "README.md") if has_parts else True
                self.artifacts.append(
                    _ArtifactRow(
                        art_id,
                        blob_id,
                        rel_posix,
                        parent_posix,
                        "file",
                        art_media,
                        art_size,
                        "",
                        None,
                        text_body,
                        title,
                        desc,
                        indexable,
                    )
                )
            else:
                art_key = f"workspaces/{workspace}/blobs/{blob_id}/artifacts/{art_id}"
                self.objects[art_key] = entry
                art_crc = crc32c_base64(entry.read_bytes())
                self.artifacts.append(
                    _ArtifactRow(
                        art_id,
                        blob_id,
                        rel_posix,
                        parent_posix,
                        "file",
                        art_media,
                        art_size,
                        art_crc,
                        art_key,
                        None,
                        title,
                        desc,
                        True,
                    )
                )

        for point in saved.metadata.points:
            self.points.append(
                models.PointStruct(
                    id=str(
                        uuid5(
                            NAMESPACE_DNS,
                            f"{blob_id}:{point.path}:{point.kind}:{point.chunk_index}",
                        )
                    ),
                    vector=saved.vectors[cache.text_key(point.text)],
                    payload={
                        "workspace_id": str(workspace),
                        "blob_id": str(blob_id),
                        "artifact_path": point.path,
                        "kind": point.kind,
                        "title": point.title,
                        "chunk_index": point.chunk_index,
                        "text": point.text,
                    },
                )
            )

    def write(self) -> str:
        s = self.services
        _put_objects(s, self.objects)

        with s.letfs.transaction():
            node_storage = {row.id: row.storage_id for row in self.nodes}
            storage_workspace = {row.id: row.workspace_id for row in self.storages}
            used: dict[UUID, int] = dict.fromkeys(
                (row.id for row in self.workspaces), 0
            )
            for file_row in self.file_rows:
                used[storage_workspace[node_storage[file_row.node_id]]] += (
                    file_row.size_bytes
                )
            quota = s.config["services"]["platform"]["default_quota_bytes"]
            self.quotas = [_QuotaRow(wid, quota, size) for wid, size in used.items()]
            _copy_rows(
                s.letfs,
                "workspace_storage",
                "workspace_id quota_bytes used_bytes",
                self.quotas,
            )
            _copy_rows(
                s.letfs,
                "storages",
                "id workspace_id name visibility root_node_id allow_blob_files allow_indexing",
                self.storages,
            )
            _copy_rows(
                s.letfs, "nodes", "id storage_id parent_id name kind", self.nodes
            )
            _copy_rows(
                s.letfs,
                "blobs",
                "id workspace_id object_key size_bytes media_type checksum source_name processing_stage title description",
                self.blobs,
            )
            _copy_rows(
                s.letfs,
                "files",
                "node_id version blob_id text_content size_bytes media_type",
                self.file_rows,
            )
            _copy_rows(
                s.letfs,
                "blob_artifacts",
                "id blob_id path parent_path kind media_type size_bytes checksum object_key text_content title description indexable",
                self.artifacts,
            )

        if s.leta is not None:
            with s.leta.transaction():
                _copy_rows(
                    s.leta, "letas", "id workspace_id storage_id state", self.letas
                )
                if self.agents:
                    with s.leta.cursor() as cursor:
                        cursor.executemany(
                            "INSERT INTO agents(id,leta_id,parent_agent_id,depth,name,title,description,custom_instructions,model_id,reasoning_effort,handle,appearance,state) "
                            "VALUES (%s,%s,NULL,0,%s,%s,%s,%s,%s,%s,%s,%s,'active')",
                            self.agents,
                        )
        if s.chat is not None and self.conversations:
            with s.chat.transaction():
                _copy_rows(
                    s.chat,
                    "conversations",
                    "id workspace_id type dm_key storage_id storage_ready created_by",
                    self.conversations,
                )
                _copy_rows(
                    s.chat,
                    "conversation_members",
                    "conversation_id workspace_id actor_type actor_id role",
                    self.conversation_members,
                )

        for chunk in _batches(self.points, 128):
            s.qdrant.upsert(s.collection, list(chunk), wait=True)

        token = self._write_graph(RelationshipUpdate.Operation.OPERATION_TOUCH)
        _copy_rows(s.platform, "workspaces", "id name state", self.workspaces)
        return token

    def _write_graph(self, operation: RelationshipUpdate.Operation.ValueType) -> str:
        token = ""
        for rows in _batches(self.relations):
            updates = [
                RelationshipUpdate(operation=operation, relationship=row)
                for row in rows
            ]
            response = self.services.graph.WriteRelationships(
                WriteRelationshipsRequest(updates=updates),
                metadata=self.services.graph_headers,
                timeout=30,
            )
            token = response.written_at.token
        return token

    def cleanup(self) -> None:
        workspace_ids = [row.id for row in self.workspaces]
        self._write_graph(RelationshipUpdate.Operation.OPERATION_DELETE)
        for wid in workspace_ids:
            unseed_workspace(self.services, wid, delete_graph=False)


async def _process_cold_blobs(
    services: ServiceConnections, cold: Sequence[_ColdBlob]
) -> None:
    if not cold:
        return
    config = services.config
    temporal = config["dependencies"]["temporal"]
    settings = config["services"]["letfs"]["processing"]
    client = await Client.connect(
        services.endpoints.temporal_address,
        namespace=temporal["namespace"],
        tls=temporal["tls"],
    )

    async def process(blob: _ColdBlob) -> None:
        queues = temporal["queues"]
        wf_id = f"blob/{blob.blob_id}/0"
        try:
            handle = await client.start_workflow(
                "ProcessBlob",
                {
                    "blob_id": str(blob.blob_id),
                    "parse_required": blob.parse,
                    "attempt": 0,
                    "cpu_queue": queues["ingest_cpu"],
                    "io_queue": queues["ingest_io"],
                    "parse_timeout_seconds": settings["parse_timeout_seconds"],
                    "enrich_timeout_seconds": settings["enrich_index_timeout_seconds"],
                },
                id=wf_id,
                task_queue=queues["letfs"],
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            handle = client.get_workflow_handle(wf_id)
        try:
            await handle.result()
        except asyncio.CancelledError:
            await handle.cancel()
            raise

    for group in _batches(cold, 16):
        results = await asyncio.gather(
            *(process(blob) for blob in group), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                raise RuntimeError(f"LetFS ingest failed: {result}") from result


def _as_float_vector(raw: object) -> list[float]:
    if not is_object_list(raw):
        raise ValueError(f"expected dense float vector from Qdrant, got {type(raw)}")
    out: list[float] = []
    for item in raw:
        if not isinstance(item, int | float):
            raise ValueError(f"expected numeric vector component, got {type(item)}")
        out.append(float(item))
    return out


def _capture_blob(services: ServiceConnections, blob: _ColdBlob) -> None:
    if cache.fingerprint(blob.path, services.config) != blob.settings:
        raise ValueError(f"source changed during cache preparation: {blob.path}")
    blob_row = services.letfs.execute(
        "SELECT title, description FROM blobs WHERE id = %s", (blob.blob_id,)
    ).fetchone()
    rows = services.letfs.execute(
        "SELECT path, kind, text_content, object_key, title, description "
        "FROM blob_artifacts WHERE blob_id = %s ORDER BY path",
        (blob.blob_id,),
    ).fetchall()
    artifacts: dict[str, bytes | None] = {}
    file_meta: dict[str, list[str]] = {}
    if blob_row and (blob_row[0] or blob_row[1]):
        file_meta["."] = [str(blob_row[0]), str(blob_row[1])]
    for path, kind, text, key, title, desc in rows:
        if title or desc:
            file_meta[str(path)] = [str(title), str(desc)]
        if kind == "directory":
            artifacts[str(path)] = None
        elif text is not None:
            artifacts[str(path)] = str(text).encode("utf-8")
        else:
            stream = services.s3.get_object(Bucket=services.bucket, Key=str(key))[
                "Body"
            ]
            try:
                artifacts[str(path)] = stream.read()
            finally:
                stream.close()

    points: list[CachePointMeta] = []
    vectors: dict[bytes, list[float]] = {}
    offset: PointId | None = None
    while True:
        group, offset = services.qdrant.scroll(
            services.collection,
            scroll_filter=_point_filter("blob_id", str(blob.blob_id)),
            offset=offset,
            limit=256,
            with_payload=True,
            with_vectors=True,
        )
        for point in group:
            payload = point.payload or {}
            text = str(payload["text"])
            raw_chunk_idx = payload.get("chunk_index", 0)
            chunk_index = raw_chunk_idx if isinstance(raw_chunk_idx, int) else 0
            points.append(
                CachePointMeta(
                    path=str(payload.get("artifact_path", "")),
                    text=text,
                    kind=str(payload["kind"]),
                    title=str(payload.get("title", "")),
                    chunk_index=chunk_index,
                )
            )
            vectors.setdefault(cache.text_key(text), _as_float_vector(point.vector))
        if offset is None:
            break
    cache.save_cache(
        blob.path,
        blob.settings,
        file_meta,
        points,
        vectors,
        artifacts,
        dimensions=services.config["models"]["embedding"]["dimensions"],
    )


def seed_workspaces(
    services: ServiceConnections,
    *,
    auth: LocalAuth,
    wiremock: WireMockClient,
    namespace: str,
    profiles: Mapping[str, UserProfile],
    specs: Sequence[WorkspaceSpec],
    token_ttl_seconds: int = 86400,
) -> SeedResult:
    """Seed selected workspaces from cached `.letfs-cache` artifacts."""
    needed = sorted(referenced_users(specs))
    subjects = {handle: f"user_{namespace[:12]}_{handle}" for handle in needed}

    with services.platform.transaction(), services.platform.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO users(id, clerk_subject, display_name) VALUES (%s, %s, %s) "
            "ON CONFLICT(clerk_subject) DO NOTHING",
            [
                (
                    uuid4(),
                    subjects[handle],
                    f"{profiles[handle].first_name} {profiles[handle].last_name}".strip()
                    or handle,
                )
                for handle in needed
            ],
        )
        id_rows = services.platform.execute(
            "SELECT clerk_subject, id FROM users WHERE clerk_subject = ANY(%s)",
            (list(subjects.values()),),
        ).fetchall()
    subject_to_id: dict[str, UUID] = {str(sub): _as_uuid(uid) for sub, uid in id_rows}
    users = {handle: subject_to_id[subjects[handle]] for handle in needed}

    claim_key = services.config["auth"]["clerk"].get(
        "user_id_metadata_key", "openlet_user_id"
    )
    accounts: dict[str, Account] = {}
    for handle in needed:
        prof = profiles[handle]
        subject = subjects[handle]
        uid = str(users[handle])
        email = prof.email or f"{handle}@openlet.local"
        wiremock.register_clerk_user(
            subject=subject,
            email=email,
            first_name=prof.first_name,
            last_name=prof.last_name,
            user_id=uid,
            user_id_claim=claim_key,
        )
        accounts[handle] = Account(
            handle=handle,
            user_id=uid,
            clerk_user_id=subject,
            email=email,
            first_name=prof.first_name,
            last_name=prof.last_name,
            token=auth.sign(subject, uid, ttl_seconds=token_ttl_seconds),
        )

    batch = _SeedBatch(services=services, specs=specs, users=users)
    batch.plan()
    try:
        zed_token = batch.write()
    except BaseException:
        try:
            batch.cleanup()
        except Exception as exc:
            print(f"seed cleanup failed: {exc}", file=sys.stderr)
        raise

    return SeedResult(
        api_url=services.endpoints.api_url,
        object_store_url=services.endpoints.object_store_url,
        zed_token=zed_token,
        users=accounts,
        workspaces=batch.output,
    )


def prepare_workspace_cache(
    services: ServiceConnections,
    *,
    specs: Sequence[WorkspaceSpec],
) -> PrepareCacheReport:
    """Run LetFS ingestion only for uncached files in `specs` and write `.letfs-cache/`."""
    config = services.config
    max_blob_bytes = config["services"]["letfs"]["max_blob_bytes"]
    workspace = uuid4()

    seen: set[Path] = set()
    cold: list[_ColdBlob] = []
    blob_rows: list[_BlobRow] = []
    objects: dict[str, Path] = {}
    total_size = 0

    for spec in specs:
        for storage_root in spec.storages.values():
            for entry in iter_seed_files(storage_root):
                if not entry.is_file() or entry.suffix.lower() not in cache.INDEXED:
                    continue
                resolved = entry.resolve()
                if resolved in seen or cache.read_cache(entry, config) is not None:
                    continue
                seen.add(resolved)
                if len(entry.name.encode("utf-8")) > 255:
                    raise ValueError(f"file name exceeds 255 bytes: {entry}")
                kind, media = classify_file(entry.name)
                if kind == "unsupported":
                    raise ValueError(f"unsupported file: {entry}")
                size = entry.stat().st_size
                if size > max_blob_bytes:
                    raise ValueError(f"file exceeds configured size limit: {entry}")

                blob_id = uuid4()
                object_key = f"workspaces/{workspace}/blobs/{blob_id}/source"
                parse = entry.suffix.lower() in cache.PARSED
                objects[object_key] = entry
                total_size += size
                blob_rows.append(
                    _BlobRow(
                        blob_id,
                        workspace,
                        object_key,
                        size,
                        media,
                        crc32c_base64(entry.read_bytes()),
                        entry.name,
                        "queued" if parse else "parsed",
                        "",
                        "",
                    )
                )
                cold.append(
                    _ColdBlob(blob_id, entry, cache.fingerprint(entry, config), parse)
                )

    if not cold:
        return {"prepared": [], "count": 0}

    quota = max(config["services"]["platform"]["default_quota_bytes"], total_size)
    try:
        _put_objects(services, objects)
        with services.letfs.transaction():
            _copy_rows(
                services.letfs,
                "workspace_storage",
                "workspace_id quota_bytes used_bytes",
                [_QuotaRow(workspace, quota, total_size)],
            )
            _copy_rows(
                services.letfs,
                "blobs",
                "id workspace_id object_key size_bytes media_type checksum source_name processing_stage title description",
                blob_rows,
            )
        asyncio.run(_process_cold_blobs(services, cold))
        for blob in cold:
            _capture_blob(services, blob)
    finally:
        try:
            unseed_workspace(services, workspace, delete_graph=False)
        except Exception as exc:
            print(f"prepare-cache cleanup failed: {exc}", file=sys.stderr)

    return {"prepared": [str(blob.path) for blob in cold], "count": len(cold)}


def unseed_workspace(
    services: ServiceConnections,
    workspace_id: UUID | str,
    *,
    delete_graph: bool = True,
) -> None:
    """Remove a single workspace and all associated DB, SpiceDB, Qdrant, and S3 data."""
    wid = workspace_id if isinstance(workspace_id, UUID) else UUID(workspace_id)
    storage_ids = [
        _as_uuid(row[0])
        for row in services.letfs.execute(
            "SELECT id FROM storages WHERE workspace_id = %s", (wid,)
        ).fetchall()
    ]
    agent_ids: list[UUID] = []
    conv_ids: list[UUID] = []
    if services.leta is not None:
        agent_ids = [
            _as_uuid(row[0])
            for row in services.leta.execute(
                "SELECT id FROM letas WHERE workspace_id = %s", (wid,)
            ).fetchall()
        ]
    if services.chat is not None:
        conv_ids = [
            _as_uuid(row[0])
            for row in services.chat.execute(
                "SELECT id FROM conversations WHERE workspace_id = %s", (wid,)
            ).fetchall()
        ]

    if delete_graph:
        filters = [
            RelationshipFilter(
                resource_type="workspace", optional_resource_id=str(wid)
            ),
            *[
                RelationshipFilter(
                    resource_type="storage", optional_resource_id=str(sid)
                )
                for sid in storage_ids
            ],
            *[
                RelationshipFilter(resource_type="agent", optional_resource_id=str(aid))
                for aid in agent_ids
            ],
            *[
                RelationshipFilter(
                    resource_type="conversation", optional_resource_id=str(cid)
                )
                for cid in conv_ids
            ],
        ]
        for rel_filter in filters:
            services.graph.DeleteRelationships(
                DeleteRelationshipsRequest(relationship_filter=rel_filter),
                metadata=services.graph_headers,
                timeout=30,
            )

    services.platform.execute("DELETE FROM workspaces WHERE id = %s", (wid,))
    if services.chat is not None:
        with services.chat.transaction():
            if conv_ids:
                services.chat.execute(
                    "DELETE FROM outbox_events WHERE conversation_id = ANY(%s)",
                    (conv_ids,),
                )
            services.chat.execute(
                "DELETE FROM conversations WHERE workspace_id = %s", (wid,)
            )
            services.chat.execute(
                "DELETE FROM sidebar_layouts WHERE workspace_id = %s", (wid,)
            )
    if services.leta is not None and agent_ids:
        with services.leta.transaction():
            services.leta.execute(
                "DELETE FROM agents WHERE leta_id = ANY(%s)", (agent_ids,)
            )
            services.leta.execute("DELETE FROM letas WHERE workspace_id = %s", (wid,))

    key_rows = services.letfs.execute(
        """
        SELECT object_key FROM blobs WHERE workspace_id = %s
        UNION ALL
        SELECT ba.object_key FROM blob_artifacts ba JOIN blobs b ON b.id = ba.blob_id
        WHERE b.workspace_id = %s AND ba.object_key IS NOT NULL
        """,
        (wid, wid),
    ).fetchall()
    with services.letfs.transaction():
        services.letfs.execute("DELETE FROM storages WHERE workspace_id = %s", (wid,))
        services.letfs.execute(
            "DELETE FROM workspace_storage WHERE workspace_id = %s", (wid,)
        )

    services.qdrant.delete(
        services.collection,
        _point_filter("workspace_id", str(wid)),
        wait=True,
    )

    keys = sorted({str(row[0]) for row in key_rows if row[0]})
    for chunk in _batches(keys, 1000):
        resp = services.s3.delete_objects(
            Bucket=services.bucket,
            Delete={"Objects": [{"Key": key} for key in chunk]},
        )
        if resp.get("Errors"):
            raise RuntimeError(f"RustFS rejected object cleanup: {resp['Errors']}")


def reset_all_data(services: ServiceConnections) -> None:
    """Wipe all workspaces, users, SpiceDB tuples, Qdrant vectors, and RustFS objects."""
    for resource_type in ("workspace", "storage", "agent", "conversation"):
        services.graph.DeleteRelationships(
            DeleteRelationshipsRequest(
                relationship_filter=RelationshipFilter(resource_type=resource_type)
            ),
            metadata=services.graph_headers,
            timeout=30,
        )

    with services.platform.transaction():
        services.platform.execute("DELETE FROM invitations")
        services.platform.execute("DELETE FROM workspaces")
        services.platform.execute("DELETE FROM users")

    if services.chat is not None:
        with services.chat.transaction():
            services.chat.execute("DELETE FROM outbox_events")
            services.chat.execute("DELETE FROM sidebar_layouts")
            services.chat.execute("DELETE FROM conversations")

    if services.leta is not None:
        with services.leta.transaction():
            services.leta.execute("DELETE FROM agents")
            services.leta.execute("DELETE FROM letas")

    with services.letfs.transaction():
        services.letfs.execute("DELETE FROM storages")
        services.letfs.execute("DELETE FROM workspace_storage")

    services.qdrant.delete(
        services.collection,
        models.FilterSelector(filter=models.Filter()),
        wait=True,
    )

    paginator = services.s3.get_paginator("list_objects_v2")
    keys: list[str] = []
    for page in paginator.paginate(Bucket=services.bucket, Prefix="workspaces/"):
        for item in page.get("Contents", []):
            key = item.get("Key")
            if key:
                keys.append(key)
    for chunk in _batches(keys, 1000):
        resp = services.s3.delete_objects(
            Bucket=services.bucket,
            Delete={"Objects": [{"Key": key} for key in chunk]},
        )
        if resp.get("Errors"):
            raise RuntimeError(f"RustFS rejected object cleanup: {resp['Errors']}")
