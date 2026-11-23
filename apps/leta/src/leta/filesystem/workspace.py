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
from openlet_api.platform.v1 import internal_pb2 as platform

from ..auth import Actor
from ..config import Services, redis_url
from ..db import Row
from ..output import BYTE_BUDGET, preview
from .letfs import LetFS


@dataclass(frozen=True)
class StorageMount:
    root: UUID
    writable: bool
    storage: UUID


class Filesystem:
    def __init__(self, s: Services, agent: Row) -> None:
        self.s, self.agent = s, agent
        self.bindings: dict[str, StorageMount] = {}
        self.mounted: dict[str, StorageMount] = {}
        self.discovered = 0.0
        self.workspace: Workspace | None = None
        self.session: Session | None = None
        self.lock = asyncio.Lock()

    async def discover(self) -> None:
        if monotonic() - self.discovered < 30:
            return
        token = ""
        storages: list[fs.Storage] = []
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
            storages.extend(response.storages)
            token = response.next_page_token
            if not token:
                break
        async with self.s.db.connection() as conn:
            chats = await (
                await conn.execute(
                    "SELECT id,user_id FROM conversations WHERE leta_id=%s AND ready",
                    (self.agent["leta_id"],),
                )
            ).fetchall()
        chat_users = {str(row["id"]): str(row["user_id"]) for row in chats}
        ids = list(
            set(chat_users.values())
            | {
                storage.ownership.user_id
                for storage in storages
                if storage.ownership.user_id
            }
        )
        handles: dict[str, str] = {}
        for index in range(0, len(ids), 100):
            result = await self.s.internal.BatchGetUsers(
                platform.BatchGetUsersRequest(user_ids=ids[index : index + 100]),
                timeout=15,
            )
            handles.update({user.id: user.handle for user in result.users})

        bindings: dict[str, StorageMount] = {}
        for storage in storages:
            owner = storage.ownership
            if owner.workspace_id:
                mount = "/shared"
            elif owner.user_id and (handle := handles.get(owner.user_id)):
                mount = f"/user/{handle}"
            elif owner.conversation_id and (
                handle := handles.get(chat_users.get(owner.conversation_id, ""))
            ):
                mount = f"/chat/{handle}"
            else:
                continue
            bindings[mount] = StorageMount(
                UUID(storage.root_node_id),
                storage.capabilities.write,
                UUID(storage.id),
            )
        self.bindings, self.discovered = bindings, monotonic()

    async def open(self) -> Session:
        async with self.lock:
            return await self._open()

    async def _open(self) -> Session:
        previous = self.mounted
        await self.discover()
        actor = Actor("agent", cast(UUID, self.agent["leta_id"]))
        workspace = cast(UUID, self.agent["workspace_id"])
        storage = cast(UUID, self.agent["storage_id"])
        settings = self.s.config["services"]["letfs"]
        if self.workspace is None:
            home_storage: fs.Storage = await self.s.files.GetStorage(
                fs.StorageRequest(workspace_id=str(workspace), storage_id=str(storage)),
                metadata=actor.metadata,
                timeout=15,
            )
            home = UUID(home_storage.root_node_id)
            driver = LetFS(self.s.files, actor, workspace, storage, home, settings)
            # Old indexes classified blobs as directories.
            cache_id = f"leta:vfs:2:{self.agent['leta_id']}:{storage}:{home}"
            self.workspace = Workspace(
                {"/home": Mount(vfs=driver, mode=MountMode.EXEC, read=ReadSpec())},
                network=True,
                max_memory="64MB",
                cache=RedisCacheConfig(
                    url=redis_url(self.s.config), key_prefix=cache_id + ":content:"
                ),
                index=RedisIndexConfig(
                    url=redis_url(self.s.config), key_prefix=cache_id + ":index:"
                ),
                runtimes=[MontyRuntime(config=MontyConfig(max_memory="64MB"))],
                env={"HOME": "/home", "PWD": "/home"},
            )
        ws = self.workspace
        if previous != self.bindings:
            for mount, binding in previous.items():
                new = self.bindings.get(mount)
                if new is None or new.root != binding.root:
                    await ws.unmount(mount)
            for mount, binding in self.bindings.items():
                mode = MountMode.EXEC if binding.writable else MountMode.READ
                old = previous.get(mount)
                if old is None or old.root != binding.root:
                    ws.add_mount(
                        mount,
                        LetFS(
                            self.s.files,
                            actor,
                            workspace,
                            binding.storage,
                            binding.root,
                            settings,
                        ),
                        mode=mode,
                        read=ReadSpec(),
                    )
                elif old.writable != binding.writable:
                    ws.set_mount_mode(mount, mode)
            self.mounted = self.bindings
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
    timed_out = False
    try:
        async with asyncio.timeout(60):
            execution = await session.shell(command, cwd=cwd, record=False, stream=True)
            async with execution:
                async for event in execution.events:
                    buffer.extend(event.data)
                    # Retain a bounded head and rolling tail in received order.
                    if len(buffer) > BYTE_BUDGET + 1:
                        del buffer[BYTE_BUDGET // 2 : -(BYTE_BUDGET // 2 + 1)]
                    remaining = capture_limit - len(captured)
                    captured.extend(event.data[:remaining])
                    complete &= len(event.data) <= remaining
                result = await execution.wait()
        code = result.exit_code
    except TimeoutError:
        timed_out, code = True, 124
    output = preview(bytes(buffer), BYTE_BUDGET) or "(no output)"
    if timed_out:
        output = (
            "Command exceeded the 60-second execution limit. File changes may be incomplete. "
            "Inspect affected files before retrying.\n\nPartial output:\n" + output
        )
    elif code:
        output += f"\n\nCommand exited with code {code}."
    if code == 126 and "Permission denied" in output:
        output += (
            "\nThe shell may have rejected an unsupported command. Check the supported command list; "
            "this message alone does not establish a storage permission problem."
        )
    if len(buffer) > BYTE_BUDGET:
        try:
            await session.vfs.write(output_path, bytes(captured))
            output += f"\nSaved output: {output_path}"
            if timed_out:
                output += " (partial capture)"
            if not complete:
                output += " (first 1 MiB only; the preview includes the final output)"
        except (ValueError, LookupError, OSError) as error:
            output += f"\nOutput could not be saved: {error}"
    return output, code
