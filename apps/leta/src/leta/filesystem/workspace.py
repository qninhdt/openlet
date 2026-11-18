import asyncio
import posixpath
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import cast
from uuid import UUID

from mirage import (
    Mount,
    MountMode,
    PathSpec,
    ReadSpec,
    Session,
    Workspace,
)
from mirage.cache.file.config import RedisCacheConfig
from mirage.cache.index.config import RedisIndexConfig
from mirage.runtime.python.monty import MontyRuntime  # pyright: ignore[reportMissingTypeStubs]  # Upstream package does not publish type stubs.
from mirage.runtime.python.monty.config import MontyConfig  # pyright: ignore[reportMissingTypeStubs]  # Upstream package does not publish type stubs.
from mirage.types import FileChangeKind, FileEvent
from mirage.utils.path import expand_tilde, norm
from openlet_api.letfs.v1 import letfs_pb2 as fs

from ..auth import Actor
from ..config import Services, redis_url
from ..db import Row
from ..output import BYTE_BUDGET, preview
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
    "curl",
    "wget",
)


@dataclass(frozen=True)
class StorageMount:
    root: UUID
    writable: bool
    name: str


class Filesystem:
    def __init__(self, s: Services, agent: Row) -> None:
        self.s, self.agent = s, agent
        self.bindings: dict[str, StorageMount] = {}
        self.discovered = 0.0
        self.workspace: Workspace | None = None
        self.session: Session | None = None
        self.lock = asyncio.Lock()

    async def discover(self) -> None:
        if monotonic() - self.discovered < 30:
            return
        token = ""
        bindings: dict[str, StorageMount] = {}
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
                    bindings[storage.id] = StorageMount(
                        UUID(storage.root_node_id),
                        storage.capabilities.write,
                        storage.name,
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
            home_storage: fs.Storage = await self.s.files.GetStorage(
                fs.StorageRequest(workspace_id=str(workspace), storage_id=str(storage)),
                metadata=actor.metadata,
                timeout=15,
            )
            home = UUID(home_storage.root_node_id)
            driver = LetFS(self.s.files, actor, workspace, storage, home)
            # Old indexes classified blobs as directories.
            cache_id = f"leta:vfs:2:{self.agent['leta_id']}:{storage}:{home}"
            self.workspace = Workspace(
                {"/home": Mount(vfs=driver, mode=MountMode.EXEC, read=ReadSpec())},
                network=True,
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
            for id, binding in previous.items():
                if id not in self.bindings or self.bindings[id].root != binding.root:
                    await ws.unmount(f"/mnt/{id}")
            for id, binding in self.bindings.items():
                mode = MountMode.EXEC if binding.writable else MountMode.READ
                old = previous.get(id)
                if old is None or old.root != binding.root:
                    ws.add_mount(
                        f"/mnt/{id}",
                        LetFS(self.s.files, actor, workspace, UUID(id), binding.root),
                        mode=mode,
                        read=ReadSpec(),
                    )
                elif old.writable != binding.writable:
                    ws.set_mount_mode(f"/mnt/{id}", mode)
        if self.session is None:
            self.session = await ws.session("tools")
        return self.session

    async def changed(self, value: str) -> None:
        await self.open()
        assert self.workspace is not None
        await self.workspace.notify(
            FileEvent(
                path=scope(value),
                kind=FileChangeKind.UNKNOWN,
                timestamp=datetime.now(timezone.utc),
            )
        )

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
    session: Session, command: str, *, output_path: str, cwd: str = "/home"
) -> tuple[str, int]:
    buffer = bytearray()
    captured = bytearray()
    capture_limit = 1024 * 1024
    complete = True
    async with asyncio.timeout(30):
        execution = await session.shell(command, cwd=cwd, record=False, stream=True)
        async with execution:
            async for event in execution.events:
                buffer.extend(event.data)
                # Drain all events, retaining a bounded head and rolling tail in received order.
                if len(buffer) > BYTE_BUDGET + 1:
                    del buffer[BYTE_BUDGET // 2 : -(BYTE_BUDGET // 2 + 1)]
                remaining = capture_limit - len(captured)
                captured.extend(event.data[:remaining])
                complete &= len(event.data) <= remaining
            result = await execution.wait()
    output = preview(bytes(buffer), BYTE_BUDGET) or "(no output)"
    if result.exit_code:
        output += f"\n\nCommand exited with code {result.exit_code}."
    if result.exit_code == 126 and "Permission denied" in output:
        output += (
            "\nThe shell may have rejected an unsupported command. Check the supported command list; "
            "this message alone does not establish a storage permission problem."
        )
    if len(buffer) > BYTE_BUDGET:
        try:
            await session.vfs.write(output_path, bytes(captured))
            output += f"\nSaved output: {output_path}"
            if not complete:
                output += " (first 1 MiB only; the preview includes the final output)"
        except (ValueError, LookupError, OSError) as error:
            output += f"\nCommand finished, but output could not be saved: {error}"
    return output, result.exit_code
