"""Batch provision seed workspaces in the isolated Compose databases."""

import asyncio
import base64
import re
import struct
import sys
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

from authzed.api.v1 import (
    ObjectReference,
    Relationship,
    RelationshipUpdate,
    SubjectReference,
    WriteRelationshipsRequest,
)
from openlet_sdk.file_types import classify_file
from psycopg.types.json import Jsonb
from qdrant_client import models
from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from . import cache
from .api import JSON, Clerk
from .compose import Stack
from .seed import Workspace, external_id, files
from .storage import Row, Services, copy


def batches[T](rows: Sequence[T], size: int = 500) -> Iterator[Sequence[T]]:
    for offset in range(0, len(rows), size):
        yield rows[offset : offset + size]


def graph_relation(
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


def upload_objects(services: Services, objects: dict[str, Path]) -> None:
    def put(item: tuple[str, Path]) -> None:
        key, path = item
        _, media = classify_file(path.name)
        with path.open("rb") as stream:
            services.s3.put_object(
                Bucket=services.bucket, Key=key, Body=stream, ContentType=media
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        for _ in pool.map(put, objects.items()):
            pass


def crc32c_base64(data: bytes) -> str:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x82F63B78 if (crc & 1) else (crc >> 1)
    return base64.b64encode(struct.pack(">I", crc ^ 0xFFFFFFFF)).decode("ascii")


def point_filter(key: str, value: str) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key=key, match=models.MatchValue(value=value))]
    )


@dataclass
class Blob:
    id: UUID
    blob_id: UUID
    path: Path
    settings: JSON
    parse: bool


@dataclass
class Batch:
    services: Services
    prepare: bool
    specs: list[Workspace]
    users: dict[str, UUID]
    output: JSON = field(default_factory=dict[str, object])
    workspaces: list[Row] = field(default_factory=list[Row])
    quotas: list[Row] = field(default_factory=list[Row])
    storages: list[Row] = field(default_factory=list[Row])
    nodes: list[Row] = field(default_factory=list[Row])
    blobs: list[Row] = field(default_factory=list[Row])
    file_rows: list[Row] = field(default_factory=list[Row])
    artifacts: list[Row] = field(default_factory=list[Row])
    letas: list[Row] = field(default_factory=list[Row])
    agents: list[Row] = field(default_factory=list[Row])
    conversations: list[Row] = field(default_factory=list[Row])
    relations: list[Relationship] = field(default_factory=list[Relationship])
    objects: dict[str, Path] = field(default_factory=dict[str, Path])
    points: list[models.PointStruct] = field(default_factory=list[models.PointStruct])
    cold: list[Blob] = field(default_factory=list[Blob])

    def plan(self) -> None:
        for spec in self.specs:
            self.plan_workspace(spec)

    def plan_workspace(self, spec: Workspace) -> None:
        workspace = uuid4()
        data = spec.manifest
        name = cast(str, data["name"])
        if not name.strip() or len(name) > 200:
            raise ValueError(f"invalid workspace name for {spec.handle}")
        self.workspaces.append((workspace, name, "active"))
        owner = self.users[data["owner"]]
        members = {self.users[member] for member in data.get("members", [])} - {owner}
        platform = self.services.config["services"]["platform"]
        if len(members) + 1 > platform["max_members"]:
            raise ValueError(f"{spec.handle} exceeds the workspace member limit")
        self.relations.append(
            graph_relation("workspace", workspace, "owner", "user", owner)
        )
        for member in sorted(members):
            self.relations.append(
                graph_relation("workspace", workspace, "member", "user", member)
            )

        storages: JSON = {}
        self.plan_storage(
            workspace, spec, storages, "shared", "Shared", "workspace", workspace
        )
        for handle in dict.fromkeys([data["owner"], *data.get("members", [])]):
            self.plan_storage(
                workspace,
                spec,
                storages,
                f"personal/{handle}",
                "Personal",
                "user",
                self.users[handle],
            )

        agents: dict[str, UUID] = {}
        for handle, agent in cast(JSON, data.get("agents", {})).items():
            agent_id = agents[handle] = uuid4()
            agent_owner = self.users[agent.get("owner", data["owner"])]
            operators = {self.users[user] for user in agent.get("operators", [])}
            agent_name = cast(str, agent["name"])
            title = cast(str, agent["title"])
            if (
                not agent_name.strip()
                or not title.strip()
                or max(len(agent_name), len(title)) > 255
            ):
                raise ValueError(f"invalid Leta name or title for {handle}")
            storage, _ = self.plan_storage(
                workspace,
                spec,
                storages,
                f"personal/{handle}",
                agent_name,
                "agent",
                agent_id,
            )
            self.letas.append((agent_id, workspace, storage, "active"))
            agent_handle = "-the-".join(
                re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
                for text in (agent_name, title)
            )
            self.agents.append(
                (
                    agent_id,
                    agent_id,
                    agent_name,
                    title,
                    agent.get("description", ""),
                    agent.get("system_prompt", ""),
                    agent.get("model_id"),
                    agent.get("reasoning_effort"),
                    agent_handle,
                    Jsonb(
                        agent.get("appearance")
                        or {"shape": "squircle", "color": "vert"}
                    ),
                )
            )
            self.relations.extend(
                (
                    graph_relation("workspace", workspace, "agent", "agent", agent_id),
                    graph_relation(
                        "agent", agent_id, "workspace", "workspace", workspace
                    ),
                    graph_relation("agent", agent_id, "owner", "user", agent_owner),
                )
            )
            for operator in sorted(operators):
                self.relations.append(
                    graph_relation("agent", agent_id, "operator", "user", operator)
                )

        conversations: JSON = {}
        for handle, pair in cast(JSON, data.get("conversations", {})).items():
            agent_handle = pair["agent"]
            agent = agents[agent_handle]
            user = self.users[pair["user"]]
            spec_agent = data["agents"][agent_handle]
            if pair["user"] not in {
                spec_agent.get("owner", data["owner"]),
                *spec_agent.get("operators", []),
            }:
                raise ValueError(f"actor cannot use Leta in conversation {handle}")
            conversation = uuid5(agent, f"user/{user}")
            storage, _ = self.plan_storage(
                workspace,
                spec,
                storages,
                f"conversation/{handle}",
                f"Conversation · {spec_agent['name']} · user {user} · {conversation}",
                "conversation",
                conversation,
            )
            conversations[handle] = {"id": str(conversation)}
            self.conversations.append((conversation, agent, user, storage, True))
            self.relations.extend(
                (
                    graph_relation(
                        "conversation", conversation, "agent", "agent", agent
                    ),
                    graph_relation(
                        "conversation", conversation, "member", "agent", agent
                    ),
                    graph_relation(
                        "conversation", conversation, "member", "user", user
                    ),
                )
            )
        for grant in data.get("grants", []):
            actor = grant["actor"]
            scope = UUID(storages[grant["storage"]]["id"])
            if actor in agents:
                self.relations.append(
                    graph_relation(
                        "storage", scope, grant["role"], "agent", agents[actor]
                    )
                )
            else:
                self.relations.append(
                    graph_relation(
                        "storage", scope, grant["role"], "user", self.users[actor]
                    )
                )

        self.output[spec.handle] = {
            "id": str(workspace),
            "agents": {handle: {"id": str(id)} for handle, id in agents.items()},
            "conversations": conversations,
            "storages": storages,
        }

    def plan_storage(
        self,
        workspace: UUID,
        spec: Workspace,
        output: JSON,
        key: str,
        name: str,
        owner_type: str,
        owner: UUID,
    ) -> tuple[UUID, UUID]:
        storage = uuid5(owner, "storage") if owner_type == "conversation" else uuid4()
        root = uuid5(owner, "root") if owner_type == "conversation" else uuid4()
        public = owner_type == "workspace"
        self.storages.append(
            (
                storage,
                workspace,
                name,
                "public" if public else "private",
                root,
                True,
                True,
            )
        )
        self.nodes.append((root, storage, None, "", "directory"))
        self.relations.append(
            graph_relation("storage", storage, "workspace", "workspace", workspace)
        )
        if public:
            self.relations.append(
                graph_relation(
                    "storage", storage, "public_workspace", "workspace", workspace
                )
            )
        if owner_type == "conversation":
            self.relations.append(
                graph_relation("storage", storage, "conversation", owner_type, owner)
            )
        else:
            self.relations.append(
                graph_relation(
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
                    graph_relation("storage", storage, "owner", "agent", owner, "owner")
                )
        paths: dict[Path, UUID] = {Path("."): root}
        if path := spec.storages.get(key):
            for entry in files(path):
                relative = entry.relative_to(path)
                parent = paths[relative.parent]
                node, blob_meta = self.plan_node(workspace, storage, parent, entry)
                paths[relative] = node
                if blob_meta is not None:
                    blob_id, media, size, checksum, object_key = blob_meta
                    if entry.suffix.lower() in cache.INDEXED:
                        self.plan_ingest(
                            workspace, blob_id, entry, size, media, checksum, object_key
                        )
                    else:
                        self.blobs.append(
                            (
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
        output[key] = {
            "id": str(storage),
            "root_node_id": str(root),
            "nodes": {
                p.as_posix(): str(id) for p, id in paths.items() if p != Path(".")
            },
        }
        return storage, root

    def plan_node(
        self, workspace: UUID, storage: UUID, parent: UUID, path: Path
    ) -> tuple[UUID, tuple[UUID, str, int, str, str] | None]:
        config = self.services.config["services"]["letfs"]
        if len(path.name.encode("utf-8")) > 255:
            raise ValueError(f"file name exceeds 255 bytes: {path}")
        node = uuid4()
        directory = path.is_dir()
        self.nodes.append(
            (node, storage, parent, path.name, "directory" if directory else "file")
        )
        if directory:
            return node, None
        kind, media = classify_file(path.name)
        size = path.stat().st_size
        if kind == "unsupported":
            raise ValueError(f"unsupported file: {path}")
        limit = config["max_text_bytes"] if kind == "text" else config["max_blob_bytes"]
        if size > limit:
            raise ValueError(f"file exceeds configured size limit: {path}")
        if kind == "text":
            body = path.read_bytes().decode("utf-8")
            if "\0" in body:
                raise ValueError(f"text contains NUL: {path}")
            self.file_rows.append((node, 1, None, body, size, media))
            return node, None
        blob_id = uuid4()
        object_key = f"workspaces/{workspace}/blobs/{blob_id}/source"
        self.objects[object_key] = path
        checksum = crc32c_base64(path.read_bytes())
        self.file_rows.append((node, 1, blob_id, None, size, media))
        return node, (blob_id, media, size, checksum, object_key)

    def plan_ingest(
        self,
        workspace: UUID,
        blob_id: UUID,
        path: Path,
        size: int,
        media: str,
        checksum: str,
        object_key: str,
    ) -> None:
        config = self.services.config
        saved = cache.read(path, config)
        if saved is None:
            if not self.prepare:
                raise ValueError(
                    f"missing or stale ingest cache for {path}. Run prepare-cache."
                )
            parse = path.suffix.lower() in cache.PARSED
            self.blobs.append(
                (
                    blob_id,
                    workspace,
                    object_key,
                    size,
                    media,
                    checksum,
                    path.name,
                    "queued" if parse else "parsed",
                    "",
                    "",
                )
            )
            self.cold.append(
                Blob(blob_id, blob_id, path, cache.fingerprint(path, config), parse)
            )
            return
        if self.prepare:
            return

        file_meta = cast(JSON, saved.metadata["files"])
        root_meta = cast(list[str], file_meta.get(".", ["", ""]))
        self.blobs.append(
            (
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
        all_entries = list(files(artifact_root))
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
                    (
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
            art_meta = cast(list[str], file_meta.get(rel_posix, ["", ""]))
            title = art_meta[0] if len(art_meta) > 0 else ""
            desc = art_meta[1] if len(art_meta) > 1 else ""
            if kind == "text":
                text_body = entry.read_bytes().decode("utf-8")
                indexable = (rel_posix != "README.md") if has_parts else True
                self.artifacts.append(
                    (
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
                    (
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

        for point in saved.metadata["points"]:
            art_path: str = point["path"]
            text: str = point["text"]
            kind: str = point["kind"]
            chunk_index = int(point.get("chunk_index", 0))
            title = str(point.get("title", ""))
            self.points.append(
                models.PointStruct(
                    id=str(
                        uuid5(
                            NAMESPACE_DNS, f"{blob_id}:{art_path}:{kind}:{chunk_index}"
                        )
                    ),
                    vector=saved.vectors[cache.text_key(text)],
                    payload={
                        "workspace_id": str(workspace),
                        "blob_id": str(blob_id),
                        "artifact_path": art_path,
                        "kind": kind,
                        "title": title,
                        "chunk_index": chunk_index,
                        "text": text,
                    },
                )
            )

    def write(self) -> str:
        s = self.services
        upload_objects(s, self.objects)
        with s.letfs.transaction():
            node_storage = {row[0]: row[1] for row in self.nodes}
            storage_workspace = {row[0]: row[1] for row in self.storages}
            used = dict.fromkeys((row[0] for row in self.workspaces), 0)
            for node_id, _, _, _, size, _ in self.file_rows:
                used[storage_workspace[node_storage[node_id]]] += size
            quota = s.config["services"]["platform"]["default_quota_bytes"]
            self.quotas = [(id, quota, size) for id, size in used.items()]
            copy(
                s.letfs,
                "workspace_storage",
                "workspace_id quota_bytes used_bytes",
                self.quotas,
            )
            copy(
                s.letfs,
                "storages",
                "id workspace_id name visibility root_node_id allow_blob_files allow_indexing",
                self.storages,
            )
            copy(s.letfs, "nodes", "id storage_id parent_id name kind", self.nodes)
            copy(
                s.letfs,
                "blobs",
                "id workspace_id object_key size_bytes media_type checksum source_name processing_stage title description",
                self.blobs,
            )
            copy(
                s.letfs,
                "files",
                "node_id version blob_id text_content size_bytes media_type",
                self.file_rows,
            )
            copy(
                s.letfs,
                "blob_artifacts",
                "id blob_id path parent_path kind media_type size_bytes checksum object_key text_content title description indexable",
                self.artifacts,
            )
        if s.leta is not None:
            with s.leta.transaction():
                copy(s.leta, "letas", "id workspace_id storage_id state", self.letas)
                if self.agents:
                    # Use INSERT so psycopg can adapt the JSONB appearance value.
                    with s.leta.cursor() as cursor:
                        cursor.executemany(
                            "INSERT INTO agents(id,leta_id,name,title,description,system_prompt,model_id,reasoning_effort,handle,appearance) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            self.agents,
                        )
                copy(
                    s.leta,
                    "conversations",
                    "id leta_id user_id storage_id ready",
                    self.conversations,
                )
        for points in batches(self.points, 128):
            s.qdrant.upsert(s.collection, points, wait=True)
        if not self.prepare:
            token = self.write_graph(RelationshipUpdate.Operation.OPERATION_TOUCH)
            copy(s.platform, "workspaces", "id name state", self.workspaces)
            return token
        return ""

    def write_graph(self, operation: RelationshipUpdate.Operation.ValueType) -> str:
        token = ""
        for rows in batches(self.relations):
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
        s = self.services
        workspace_ids = [row[0] for row in self.workspaces]
        s.platform.execute(
            "DELETE FROM workspaces WHERE id = ANY(%s)", (workspace_ids,)
        )
        if not self.prepare:
            self.write_graph(RelationshipUpdate.Operation.OPERATION_DELETE)
        if s.leta is not None:
            with s.leta.transaction():
                s.leta.execute(
                    "DELETE FROM agents WHERE leta_id = ANY(%s)",
                    ([row[0] for row in self.letas],),
                )
                s.leta.execute(
                    "DELETE FROM letas WHERE workspace_id = ANY(%s)", (workspace_ids,)
                )
        keys = s.letfs.execute(
            """
            SELECT object_key FROM blobs WHERE workspace_id = ANY(%s)
            UNION ALL
            SELECT ba.object_key FROM blob_artifacts ba JOIN blobs b ON b.id=ba.blob_id
            WHERE b.workspace_id = ANY(%s) AND ba.object_key IS NOT NULL
            """,
            (workspace_ids, workspace_ids),
        ).fetchall()
        with s.letfs.transaction():
            s.letfs.execute(
                "DELETE FROM storages WHERE workspace_id = ANY(%s)",
                (workspace_ids,),
            )
            s.letfs.execute(
                "DELETE FROM workspace_storage WHERE workspace_id = ANY(%s)",
                (workspace_ids,),
            )
        if self.points or self.cold:
            s.qdrant.delete(
                s.collection,
                models.Filter(
                    must=[
                        models.FieldCondition(
                            key="workspace_id",
                            match=models.MatchAny(
                                any=[str(id) for id in workspace_ids]
                            ),
                        )
                    ]
                ),
                wait=True,
            )
        for entries in batches(
            sorted(set(self.objects) | {row[0] for row in keys}), 1000
        ):
            response = s.s3.delete_objects(
                Bucket=s.bucket, Delete={"Objects": [{"Key": key} for key in entries]}
            )
            if response.get("Errors"):
                raise RuntimeError("RustFS rejected seed object cleanup")


async def process_blobs(batch: Batch, stack: Stack) -> None:
    config = batch.services.config
    temporal = config["dependencies"]["temporal"]
    settings = config["services"]["letfs"]["processing"]
    if not batch.cold:
        return
    client = await Client.connect(
        stack.port("temporal", temporal["address"].rsplit(":", 1)[1]),
        namespace=temporal["namespace"],
        tls=temporal["tls"],
    )

    async def process(blob: Blob) -> None:
        queues = temporal["queues"]
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
                id=f"blob/{blob.blob_id}/0",
                task_queue=queues["letfs"],
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
        except WorkflowAlreadyStartedError:
            handle = client.get_workflow_handle(f"blob/{blob.blob_id}/0")
        try:
            await handle.result()
        except asyncio.CancelledError:
            await handle.cancel()
            raise

    for group in batches(batch.cold, 16):
        results = await asyncio.gather(
            *(process(blob) for blob in group), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                raise RuntimeError(f"LetFS ingest failed: {result}") from result


def capture(services: Services, blob: Blob) -> None:
    if cache.fingerprint(blob.path, services.config) != blob.settings:
        raise ValueError(f"source changed during cache preparation: {blob.path}")
    blob_row = services.letfs.execute(
        "SELECT title,description FROM blobs WHERE id=%s", (blob.blob_id,)
    ).fetchone()
    rows = services.letfs.execute(
        "SELECT path,kind,text_content,object_key,title,description FROM blob_artifacts WHERE blob_id=%s ORDER BY path",
        (blob.blob_id,),
    ).fetchall()
    artifacts: dict[str, bytes | None] = {}
    metadata: JSON = {}
    if blob_row and (blob_row[0] or blob_row[1]):
        metadata["."] = [blob_row[0], blob_row[1]]
    for path, kind, text, key, title, desc in rows:
        if title or desc:
            metadata[path] = [title, desc]
        if kind == "directory":
            artifacts[path] = None
        elif text is not None:
            artifacts[path] = text.encode("utf-8")
        else:
            stream = services.s3.get_object(Bucket=services.bucket, Key=key)["Body"]
            try:
                artifacts[path] = stream.read()
            finally:
                stream.close()

    points: list[JSON] = []
    vectors: dict[bytes, list[float]] = {}
    offset = None
    while True:
        group, offset = services.qdrant.scroll(
            services.collection,
            scroll_filter=point_filter("blob_id", str(blob.blob_id)),
            offset=offset,
            limit=256,
            with_payload=True,
            with_vectors=True,
        )
        for point in group:
            payload = point.payload or {}
            text = cast(str, payload["text"])
            kind = payload["kind"]
            vector = cast(list[float], point.vector)
            points.append(
                {
                    "path": payload.get("artifact_path", ""),
                    "text": text,
                    "kind": kind,
                    "title": payload.get("title", ""),
                    "chunk_index": payload.get("chunk_index", 0),
                }
            )
            vectors.setdefault(cache.text_key(text), vector)
        if offset is None:
            break
    cache.save(
        blob.path,
        blob.settings,
        {"files": metadata, "points": points},
        vectors,
        artifacts,
    )


def seed(
    services: Services,
    stack: Stack,
    api: str,
    endpoint: str,
    clerk: Clerk,
    namespace: str,
    profiles: JSON,
    specs: list[Workspace],
    *,
    prepare: bool,
) -> JSON:
    accounts = {
        handle: clerk.account(external_id(namespace, handle), profile)
        for handle, profile in profiles.items()
    }
    with services.platform.transaction(), services.platform.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO users(id,clerk_subject,display_name) VALUES (%s,%s,%s) ON CONFLICT(clerk_subject) DO NOTHING",
            [
                (
                    uuid4(),
                    account["id"],
                    f"{profiles[handle]['first_name']} {profiles[handle]['last_name']}".strip()
                    or handle,
                )
                for handle, account in accounts.items()
            ],
        )
        ids = dict(
            services.platform.execute(
                "SELECT clerk_subject,id FROM users WHERE clerk_subject = ANY(%s)",
                ([account["id"] for account in accounts.values()],),
            ).fetchall()
        )
    key = services.config["auth"]["clerk"].get(
        "user_id_metadata_key", "openlet_user_id"
    )
    for account in accounts.values():
        clerk.sync_metadata(account, key, str(ids[account["id"]]))
    users = {handle: ids[account["id"]] for handle, account in accounts.items()}
    batch = Batch(services, prepare, specs, users)
    batch.plan()
    if prepare and not batch.cold:
        return {"prepared": [], "count": 0}
    try:
        token = batch.write()
        if prepare:
            asyncio.run(process_blobs(batch, stack))
            for blob in batch.cold:
                capture(services, blob)
    except BaseException:
        try:
            batch.cleanup()
        except Exception as error:
            print(f"seed cleanup failed: {error}", file=sys.stderr)
        raise
    if prepare:
        batch.cleanup()
        return {
            "prepared": [str(blob.path) for blob in batch.cold],
            "count": len(batch.cold),
        }
    return {
        "api_url": api,
        "object_store_url": f"http://{endpoint}",
        "zed_token": token,
        "users": {
            handle: {"id": str(users[handle]), "clerk_user_id": account["id"]}
            for handle, account in accounts.items()
        },
        "workspaces": batch.output,
    }
