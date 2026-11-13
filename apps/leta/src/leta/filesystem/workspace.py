import asyncio
import posixpath
from time import monotonic
from typing import cast
from uuid import UUID

from mirage import Mount, MountMode, PathSpec, ReadSpec, Session, Workspace
from mirage.cache.file.config import RedisCacheConfig
from mirage.cache.index.config import RedisIndexConfig
from mirage.runtime.python.monty import MontyRuntime  # pyright: ignore[reportMissingTypeStubs]  # Upstream package does not publish type stubs.
from mirage.runtime.python.monty.config import MontyConfig  # pyright: ignore[reportMissingTypeStubs]  # Upstream package does not publish type stubs.
from mirage.utils.path import expand_tilde, norm
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
        self.workspace: Workspace | None = None
        self.session: Session | None = None
        self.lock = asyncio.Lock()

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

    async def open(self) -> Session:
        async with self.lock:
            return await self._open()

    async def _open(self) -> Session:
        previous = self.bindings if self.workspace is not None else {}
        await self.discover()
        actor = Actor("agent", cast(UUID, self.agent["leta_id"]))
        workspace = cast(UUID, self.agent["workspace_id"])
        storage = cast(UUID, self.agent["storage_id"])
        if self.workspace is None:
            home = cast(UUID | None, self.agent["home_node_id"])
            if home is None:
                home_storage: fs.Storage = await self.s.files.GetStorage(
                    fs.StorageRequest(
                        workspace_id=str(workspace), storage_id=str(storage)
                    ),
                    metadata=actor.metadata,
                    timeout=15,
                )
                home = UUID(home_storage.root_node_id)
            driver = LetFS(self.s.files, actor, workspace, storage, home)
            cache_id = f"leta:vfs:{self.agent['leta_id']}:{storage}:{home}"
            self.workspace = Workspace(
                {"/home": Mount(vfs=driver, mode=MountMode.WRITE, read=ReadSpec())},
                network={
                    "allowed_domains": [
                        self.s.config["dependencies"]["redis"]["address"]
                    ]
                },
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
        ws = self.workspace
        if previous != self.bindings:
            for id, (root, _) in previous.items():
                if id not in self.bindings or self.bindings[id][0] != root:
                    await ws.unmount(f"/mnt/{id}")
            for id, (root, write) in self.bindings.items():
                mode = MountMode.WRITE if write else MountMode.READ
                old = previous.get(id)
                if old is None or old[0] != root:
                    ws.add_mount(
                        f"/mnt/{id}",
                        LetFS(self.s.files, actor, workspace, UUID(id), root),
                        mode=mode,
                        read=ReadSpec(),
                    )
                elif old[1] != write:
                    ws.set_mount_mode(f"/mnt/{id}", mode)
        if self.session is None:
            self.session = await ws.session("tools")
        return self.session

    async def close(self) -> None:
        if self.workspace is not None:
            await self.workspace.close()


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
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    limits = {"stdout": 16000, "stderr": 4000}
    truncated = False
    async with asyncio.timeout(30):
        execution = await session.shell(
            command, cwd=cwd, runtime=runtime, record=False, stream=True
        )
        async with execution:
            async for event in execution.events:
                name = "stdout" if event.stream == "stdout" else "stderr"
                remaining = limits[name] - len(buffers[name])
                buffers[name].extend(event.data[:remaining])
                truncated |= len(event.data) > remaining
            result = await execution.wait()
    return {
        "stdout": buffers["stdout"].decode("utf-8", errors="replace"),
        "stderr": buffers["stderr"].decode("utf-8", errors="replace"),
        "exit_code": result.exit_code,
        "truncated": truncated,
    }
