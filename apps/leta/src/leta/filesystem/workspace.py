"""Invocation-owned Mirage state backed by current Workspace scope discovery."""

import hashlib
import json
from contextlib import asynccontextmanager
from uuid import UUID

from mirage import Workspace
from mirage.cache.file.config import RedisCacheConfig
from mirage.runtime.python.monty import MontyRuntime
from mirage.types import MountMode, ReadPolicy, ReadSpec
from openlet.clients.letfs import FilesystemClient, Locator
from openlet.clients.workspace import WorkspaceClient
from openlet.rpc import Actor
from redis.asyncio import Redis

from leta.domain import Lifecycle
from leta.filesystem.access_policy import AccessPolicy, cache_network
from leta.filesystem.letfs_vfs import MAX_READ_BYTES, LetFSVFS, Mount
from leta.store import Store, fault

AGENT_PROFILE = {"commands": {"deny": ["curl", "wget", "git clone", "git fetch"]}}


async def discover_mounts(
    client: WorkspaceClient,
    workspace_id: UUID,
    actor: Actor,
    home_scope_id: UUID,
    box_root_id: UUID | None = None,
) -> list[Mount]:
    mounts, cursor, filesystem_id, seen = [], None, None, set()
    while True:
        page = await client.list_accessible_scopes(
            str(workspace_id), actor=actor, limit=100, cursor=cursor
        )
        if filesystem_id is not None and filesystem_id != page.filesystem_id:
            raise ValueError("filesystem changed during scope discovery")
        filesystem_id = page.filesystem_id
        for scope in page.items:
            root_id = scope.root_id
            if scope.kind == "home" and scope.id == str(home_scope_id):
                prefix = "/home"
                root_id = str(box_root_id) if box_root_id else root_id
            elif scope.kind == "shared":
                prefix = "/shared"
            elif scope.kind == "personal":
                prefix = "/users/" + scope.owner.id
            else:
                raise ValueError("unsupported scope in agent mount discovery")
            if prefix in seen:
                raise ValueError("duplicate mount in scope discovery")
            seen.add(prefix)
            mounts.append(
                Mount(filesystem_id, scope.id, root_id, prefix, scope.rights.write)
            )
        if not page.HasField("next_cursor"):
            break
        if page.next_cursor in seen:
            raise ValueError("scope discovery cursor cycle")
        cursor = page.next_cursor
        seen.add(cursor)
    if "/home" not in seen:
        raise PermissionError("agent home is not accessible")
    return sorted(mounts, key=lambda mount: mount.prefix)


class AgentWorkspace:
    def __init__(self, workspace, session, policy, discover, native, actor):
        self.workspace, self.session, self.policy = workspace, session, policy
        self._discover, self.native, self.actor = discover, native, actor

    async def refresh(self):
        """Caller waits for its tools to finish before this safe-boundary refresh."""
        mounts = {mount.prefix: mount for mount in await self._discover()}
        for prefix, backend in list(self.policy.backends.items()):
            if mounts.get(prefix) != backend.mount:
                await self.workspace.unmount(prefix)
                del self.policy.backends[prefix]
        for prefix, mount in mounts.items():
            if prefix not in self.policy.backends:
                backend = LetFSVFS(self.native, self.actor, mount)
                self.workspace.add_mount(prefix, backend, mount_mode(mount))
                self.policy.backends[prefix] = backend

    def guidance(self) -> str:
        paths = "\n".join(
            f"- {prefix}: {'read/write' if vfs.mount.writable else 'read only'}"
            for prefix, vfs in sorted(self.policy.backends.items())
        )
        return (
            "# VFS.md\nHOME is /home; ~ resolves there.\n"
            f"{paths}\n"
            "Files are small UTF-8 text (maximum 1 MiB). Blob reads return "
            "metadata and the real artifact tree, never original blob bytes. "
            "Read artifact children by source/name or @source-file-id/name. "
            "Generated artifacts are read only. rm moves files to trash. "
            "Shell commands run in Mirage; Python runs in Monty, with these "
            "same mounts and no host files, environment or network. "
            "Literal text search and semantic_search are separate operations."
        )


def mount_mode(mount: Mount) -> MountMode:
    # EXEC enables Monty's inline code, without enabling host execution.
    return MountMode.EXEC if mount.writable else MountMode.READ


class WorkspaceFactory:
    def __init__(
        self,
        store: Store,
        scopes: WorkspaceClient,
        native: FilesystemClient,
        redis: Redis,
        redis_url: str,
        namespace: str,
    ):
        self.store, self.scopes, self.native = store, scopes, native
        self.redis, self.redis_url, self.namespace = redis, redis_url, namespace

    @asynccontextmanager
    async def open(self, leta_id: UUID, agent_id: UUID, invocation_id: str):
        await self.redis.ping()
        root = await self.store.get_agent(leta_id, leta_id)
        agent = (
            root
            if agent_id == leta_id
            else await self.store.get_agent(leta_id, agent_id)
        )
        if root["status"] != Lifecycle.ACTIVE or agent["status"] != Lifecycle.ACTIVE:
            raise fault("RESOURCE_INACTIVE", "agent is not active")
        box_root = None
        if agent_id != leta_id:
            box = await self.store.get_box(leta_id, agent["box_id"])
            if box["status"] != Lifecycle.ACTIVE:
                raise fault("RESOURCE_INACTIVE", "box is not active")
            box_root = box["home_node_id"]
        actor = Actor("leta", leta_id)

        async def discover():
            mounts = await discover_mounts(
                self.scopes,
                root["workspace_id"],
                actor,
                root["home_scope_id"],
                box_root,
            )
            if box_root is not None:
                home = next(mount for mount in mounts if mount.prefix == "/home")
                # Resolve from the scope root, then bind every tool to the box root.
                value = await self.native.stat(
                    home.filesystem_id,
                    home.scope_id,
                    Locator(node_id=str(box_root)),
                    actor=actor,
                )
                if value.node.kind != "directory":
                    raise ValueError("box home must be a live directory")
            return mounts

        mounts = await discover()
        identity = json.dumps(
            [(m.filesystem_id, m.scope_id, m.root_id, m.prefix) for m in mounts],
            separators=(",", ":"),
        )
        digest = hashlib.sha256(identity.encode()).hexdigest()
        backends = {m.prefix: LetFSVFS(self.native, actor, m) for m in mounts}
        policy = AccessPolicy(backends)
        workspace = Workspace(
            {prefix: (vfs, mount_mode(vfs.mount)) for prefix, vfs in backends.items()},
            workspace_id=str(agent_id),
            cache=RedisCacheConfig(
                url=self.redis_url,
                key_prefix=f"openlet:{self.namespace}:{root['workspace_id']}:"
                f"{leta_id}:{agent_id}:{digest}:files:",
                limit="32MB",
                max_drain_bytes=MAX_READ_BYTES,
            ),
            read=ReadSpec(policy=ReadPolicy.FRESH),
            network=cache_network(self.redis_url),
            env={"HOME": "/home"},
            runtimes=[MontyRuntime(config={"max_memory": "16MB"})],
            policies=[policy],
            profiles={"agent": AGENT_PROFILE},
            profile="agent",
        )
        policy.cache = workspace.cache
        try:
            session = await workspace.session(invocation_id)
            await session.shell("cd /home")
            yield AgentWorkspace(
                workspace, session, policy, discover, self.native, actor
            )
        finally:
            await workspace.close()
