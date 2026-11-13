import asyncio
import posixpath
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic
from typing import cast
from uuid import UUID

from mirage import Mount, MountMode, PathSpec, ReadSpec, Session, Workspace
from mirage.cache.file.config import RedisCacheConfig
from mirage.cache.index.config import RedisIndexConfig
from mirage.runtime.python.monty import MontyRuntime
from mirage.runtime.python.monty.config import MontyConfig
from mirage.utils.path import expand_tilde, norm
from mirage.workspace.workspace.types import VFSMount
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_sdk.config import JSON

from ..auth import Actor
from ..config import Services, redis_url
from ..db import Row
from .letfs import LetFS

COMMANDS = (
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    "rg",
    "find",
    "tree",
    "du",
    "stat",
    "file",
    "test",
    "[",
    "echo",
    "printf",
    "pwd",
    "cd",
    "export",
    "unset",
    "true",
    "false",
    ":",
    "set",
    "sort",
    "uniq",
    "cut",
    "paste",
    "tr",
    "sed",
    "awk",
    "jq",
    "mkdir",
    "rmdir",
    "rm",
    "cp",
    "mv",
    "touch",
    "tee",
    "diff",
    "python",
    "python3",
    "date",
    "seq",
    "basename",
    "dirname",
)


class Filesystem:
    def __init__(self, s: Services, agent: Row) -> None:
        self.s, self.agent = s, agent
        self.bindings: dict[str, tuple[UUID, bool]] = {}
        self.discovered = 0.0

    async def discover(self) -> None:
        if monotonic() - self.discovered < 30:
            return
        token = ""
        bindings: dict[str, tuple[UUID, bool]] = {}
        while True:
            response: fs.ListStoragesResponse = await self.s.files.ListStorages(
                fs.ListStoragesRequest(
                    workspace_id=str(self.agent["workspace_id"]),
                    page_size=100,
                    page_token=token,
                ),
                metadata=Actor("agent", cast(UUID, self.agent["leta_id"])).metadata,
                timeout=15,
            )
            for storage in response.storages:
                if storage.id != str(self.agent["storage_id"]):
                    bindings[storage.id] = (
                        UUID(storage.root_node_id),
                        storage.capabilities.write,
                    )
            token = response.next_page_token
            if not token:
                break
        self.bindings, self.discovered = bindings, monotonic()

    @asynccontextmanager
    async def batch(self) -> AsyncIterator[tuple[Workspace, Session, list[LetFS]]]:
        await self.discover()
        actor = Actor("agent", cast(UUID, self.agent["leta_id"]))
        workspace = cast(UUID, self.agent["workspace_id"])
        storage = cast(UUID, self.agent["storage_id"])
        home = cast(UUID | None, self.agent["home_node_id"])
        if home is None:
            home_storage: fs.Storage = await self.s.files.GetStorage(
                fs.StorageRequest(workspace_id=str(workspace), storage_id=str(storage)),
                metadata=actor.metadata,
                timeout=15,
            )
            home = UUID(home_storage.root_node_id)
        driver = LetFS(self.s.files, actor, workspace, storage, home)
        mounts: dict[str, VFSMount] = {
            "/home": Mount(vfs=driver, mode=MountMode.WRITE, read=ReadSpec())
        }
        drivers = [driver]
        for id, (root, write) in self.bindings.items():
            remote = LetFS(self.s.files, actor, workspace, UUID(id), root)
            mounts[f"/mnt/{id}"] = Mount(
                vfs=remote,
                mode=MountMode.WRITE if write else MountMode.READ,
                read=ReadSpec(),
            )
            drivers.append(remote)
        cache_id = f"leta:vfs:{self.agent['leta_id']}:{storage}:{home}"
        ws = Workspace(
            mounts,
            network=False,
            max_memory="32MB",
            cache=RedisCacheConfig(
                url=redis_url(self.s.config), key_prefix=cache_id + ":content:"
            ),
            index=RedisIndexConfig(
                url=redis_url(self.s.config), key_prefix=cache_id + ":index:"
            ),
            runtimes=[MontyRuntime(config=MontyConfig(max_memory="16MB"))],
            env={"HOME": "/home", "PWD": "/home"},
            profiles={"agent": {"commands": {"allow": list(COMMANDS)}}},
            profile="agent",
        )
        try:
            session = await ws.session("tools")
            yield ws, session, drivers
        finally:
            await ws.close()


def path(value: str = "~") -> str:
    return norm(posixpath.join("/home", expand_tilde(value, "/home")))


def scope(value: str) -> PathSpec:
    absolute = path(value)
    return PathSpec(
        virtual=absolute, directory=posixpath.dirname(absolute), vfs_path=""
    )


async def shell(
    session: Session, command: str, *, cwd: str = "/home", runtime: str | None = None
) -> dict[str, JSON]:
    async with asyncio.timeout(30):
        result = await session.shell(command, cwd=cwd, runtime=runtime, record=False)
    stdout, stderr = await result.stdout_str(), await result.stderr_str()
    return {
        "stdout": stdout[:16000],
        "stderr": stderr[:4000],
        "exit_code": result.exit_code,
        "truncated": len(stdout) > 16000 or len(stderr) > 4000,
    }
