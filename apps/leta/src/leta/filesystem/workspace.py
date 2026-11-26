from __future__ import annotations

import asyncio
import posixpath
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID

from mirage import (
    Mount,
    MountMode,
    PathSpec,
    ReadPolicy,
    ReadSpec,
    Session,
    Workspace,
)
from mirage.runtime.python.monty import (  # pyright: ignore[reportMissingTypeStubs]
    MontyRuntime,
)
from mirage.runtime.python.monty.config import (  # pyright: ignore[reportMissingTypeStubs]
    MontyConfig,
)
from mirage.types import FileChangeKind, FileEvent
from mirage.utils.path import expand_tilde, norm
from openlet_api.chat.v1 import chat_pb2 as chat_pb
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_api.platform.v1 import internal_pb2 as plat_pb

from ..auth import Actor
from ..config import Services
from ..runtime.truncation import (
    format_tail_truncated,
    spill_filename,
    truncate_tail,
)
from .letfs import LetFS, LetFSByID

PUBLIC_ONLY_DENIED_DOMAINS: list[str] = [
    "127.0.0.0/8",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
    "0.0.0.0/8",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
    "localhost",
    "*.local",
    "*.internal",
]


def canonical_path(value: str = "~") -> str:
    return norm(posixpath.join("/home", expand_tilde(value.strip() or "~", "/home")))


def path_spec(value: str) -> PathSpec:
    absolute = canonical_path(value)
    return PathSpec(
        virtual=absolute, directory=posixpath.dirname(absolute), vfs_path=""
    )


class KeyedMutex:
    """Sorted per-path async lock for safe concurrent file_edit / file_write operations."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def lock(self, *paths: str) -> AsyncGenerator[None]:
        keys = sorted({canonical_path(p) for p in paths})
        acquired: list[asyncio.Lock] = []
        try:
            for k in keys:
                lk = self._locks.setdefault(k, asyncio.Lock())
                await lk.acquire()
                acquired.append(lk)
            yield
        finally:
            for lk in reversed(acquired):
                lk.release()


@dataclass(frozen=True, slots=True)
class StorageMount:
    root: UUID
    writable: bool
    storage: UUID


@dataclass(frozen=True, slots=True)
class ShellOutcome:
    output: str
    exit_code: int
    wall_time_ms: int
    truncated: bool
    output_path: str | None


class Filesystem:
    def __init__(self, services: Services, agent_row: dict[str, object]) -> None:
        self.s = services
        self.agent = agent_row
        self.bindings: dict[str, StorageMount] = {}
        self.mounted: dict[str, StorageMount] = {}
        self.conv_mounts: dict[str, str] = {}
        self.user_info: dict[str, tuple[str, str]] = {}
        self.agent_handles: dict[str, str] = {}
        self.discovered: float = 0.0
        self.workspace: Workspace | None = None
        self.session: Session | None = None
        self._lock = asyncio.Lock()
        self.path_mutex = KeyedMutex()

    def _shared_read_spec(self) -> ReadSpec:
        policy = (
            ReadPolicy.FRESH
            if self.s.settings.bash.shared_mount_read_policy == "fresh"
            else ReadPolicy.BOUNDED
        )
        return ReadSpec(policy=policy)

    async def discover(self, *, force: bool = False) -> None:
        if not force and monotonic() - self.discovered < 30.0:
            return
        actor = Actor("agent", UUID(str(self.agent["leta_id"])))
        workspace_id = str(self.agent["workspace_id"])

        storages: list[fs.Storage] = []
        token = ""
        while True:
            resp = await self.s.letfs.ListStorages(
                fs.ListStoragesRequest(
                    workspace_id=workspace_id, page_size=100, page_token=token
                ),
                metadata=actor.metadata,
                timeout=15,
            )
            storages.extend(resp.storages)
            token = resp.next_page_token
            if not token:
                break

        # Query apps/chat for conversations to map conversation_id -> flat /chat/<handle>.
        convs: list[chat_pb.Conversation] = []
        c_token = ""
        while True:
            try:
                c_resp = await self.s.chat.ListConversations(
                    chat_pb.ListConversationsRequest(
                        workspace_id=workspace_id, page_size=100, page_token=c_token
                    ),
                    metadata=actor.metadata,
                    timeout=15,
                )
            except Exception:
                break
            convs.extend(c_resp.conversations)
            c_token = c_resp.next_page_token
            if not c_token:
                break

        user_ids: set[str] = {
            st.ownership.user_id for st in storages if st.ownership.user_id
        }
        peer_agent_ids: set[str] = set()
        for c in convs:
            if c.type == "dm":
                for m in c.members:
                    if m.actor_type == "user":
                        user_ids.add(m.actor_id)
                    elif m.actor_type == "agent" and m.actor_id != str(actor.id):
                        peer_agent_ids.add(m.actor_id)

        user_handles: dict[str, str] = {}
        user_info: dict[str, tuple[str, str]] = {}
        uid_list = list(user_ids)
        for i in range(0, len(uid_list), 100):
            u_resp = await self.s.platform_internal.BatchGetUsers(
                plat_pb.BatchGetUsersRequest(user_ids=uid_list[i : i + 100]),
                timeout=15,
            )
            for u in u_resp.users:
                user_handles[u.id] = u.handle
                user_info[u.id] = (u.display_name, u.handle)

        agent_handles: dict[str, str] = {}
        if peer_agent_ids:
            async with self.s.db.connection() as conn:
                rows = await (
                    await conn.execute(
                        "SELECT id, handle FROM agents WHERE id = ANY(%s)",
                        ([UUID(aid) for aid in peer_agent_ids],),
                    )
                ).fetchall()
            for r in rows:
                agent_handles[str(r["id"])] = str(r["handle"])

        # Build flat /chat/<handle> map: DM handles first, then group handles (disambiguating rare collisions with -group).
        dm_conv_handles: dict[str, str] = {}
        group_conv_handles: dict[str, str] = {}
        used_chat_handles: set[str] = set()
        for c in convs:
            if c.type == "dm":
                peer_handle: str | None = None
                for m in c.members:
                    if m.actor_type == "user" and m.actor_id in user_handles:
                        peer_handle = user_handles[m.actor_id]
                        break
                    if (
                        m.actor_type == "agent"
                        and m.actor_id != str(actor.id)
                        and m.actor_id in agent_handles
                    ):
                        peer_handle = agent_handles[m.actor_id]
                        break
                if peer_handle:
                    dm_conv_handles[c.id] = peer_handle
                    used_chat_handles.add(peer_handle)

        for c in convs:
            if c.type == "group" and c.HasField("handle") and c.handle:
                gh = c.handle
                if gh in used_chat_handles:
                    gh = f"{gh}-group"
                group_conv_handles[c.id] = gh
                used_chat_handles.add(gh)

        conv_handles = {**dm_conv_handles, **group_conv_handles}

        bindings: dict[str, StorageMount] = {}
        bound_conv_ids: set[str] = set()
        for st in storages:
            owner = st.ownership
            if owner.workspace_id:
                mount = "/shared"
            elif owner.user_id and (h := user_handles.get(owner.user_id)):
                mount = f"/user/{h}"
            elif owner.conversation_id and (
                ch := conv_handles.get(owner.conversation_id)
            ):
                mount = f"/chat/{ch}"
                bound_conv_ids.add(owner.conversation_id)
            else:
                continue
            bindings[mount] = StorageMount(
                root=UUID(st.root_node_id),
                writable=bool(st.capabilities.write),
                storage=UUID(st.id),
            )

        # Lazily provision conversation storages for active conversations so /chat/<handle>
        # is immediately writable for deliverables even on the very first turn.
        for c in convs:
            if c.id in bound_conv_ids or c.last_seq <= 0:
                continue
            ch = conv_handles.get(c.id)
            if not ch:
                continue
            try:
                ensured = await self.s.chat.EnsureConversationStorage(
                    chat_pb.ConversationRequest(
                        workspace_id=workspace_id, conversation_id=c.id
                    ),
                    metadata=actor.metadata,
                    timeout=15,
                )
            except Exception:
                continue
            if ensured.storage_id and ensured.root_node_id:
                bindings[f"/chat/{ch}"] = StorageMount(
                    root=UUID(ensured.root_node_id),
                    writable=True,
                    storage=UUID(ensured.storage_id),
                )
        self.bindings = bindings
        self.conv_mounts = {
            cid: f"/chat/{ch}"
            for cid, ch in conv_handles.items()
            if f"/chat/{ch}" in bindings
        }
        self.user_info = user_info
        self.agent_handles = agent_handles
        self.discovered = monotonic() if "/shared" in bindings else 0.0

    def chat_mount_for(self, reply_address: str) -> str | None:
        addr = reply_address.strip()
        if addr.startswith("chat:"):
            conv_id = addr.removeprefix("chat:").strip()
            return self.conv_mounts.get(conv_id)
        return self.conv_mounts.get(addr)

    def enrich_sender(self, sender: Mapping[str, object]) -> dict[str, object]:
        out = dict(sender)
        if out.get("handle"):
            return out
        stype = str(out.get("type") or "")
        sid = str(out.get("id") or "")
        if stype == "user" and sid in self.user_info:
            name, handle = self.user_info[sid]
            if handle:
                out["handle"] = handle
            if name and not out.get("name"):
                out["name"] = name
        elif stype == "agent" and sid in self.agent_handles:
            out["handle"] = self.agent_handles[sid]
        return out

    def writable_mounts(self) -> list[str]:
        mounts = ["/home"]
        mounts.extend(sorted(m for m, b in self.bindings.items() if b.writable))
        return mounts

    def all_mounts(self) -> list[str]:
        mounts = ["/home"]
        mounts.extend(sorted(self.bindings.keys()))
        return mounts

    async def open(self) -> Session:
        async with self._lock:
            return await self._open_locked()

    async def _open_locked(self) -> Session:
        previous = self.mounted
        await self.discover()
        actor = Actor("agent", UUID(str(self.agent["leta_id"])))
        workspace_id = UUID(str(self.agent["workspace_id"]))
        storage_id = UUID(str(self.agent["storage_id"]))
        letfs_cfg = self.s.config["services"]["letfs"]
        bash_cfg = self.s.settings.bash

        if self.workspace is None:
            home_st = await self.s.letfs.GetStorage(
                fs.StorageRequest(
                    workspace_id=str(workspace_id), storage_id=str(storage_id)
                ),
                metadata=actor.metadata,
                timeout=15,
            )
            home_root = UUID(home_st.root_node_id)
            home_driver = LetFS(
                self.s.letfs, actor, workspace_id, storage_id, home_root, letfs_cfg
            )
            by_id_driver = LetFSByID(self.s.letfs, actor, workspace_id, letfs_cfg)

            network: bool | Mapping[str, Sequence[str] | Mapping[str, str]] = False
            if bash_cfg.network == "public_only":
                network = {"denied_domains": PUBLIC_ONLY_DENIED_DOMAINS}

            self.workspace = Workspace(
                {
                    "/home": Mount(
                        vfs=home_driver,
                        mode=MountMode.EXEC,
                        read=ReadSpec(policy=ReadPolicy.BOUNDED),
                    ),
                    "/letfs": Mount(
                        vfs=by_id_driver,
                        mode=MountMode.EXEC,
                        read=ReadSpec(policy=ReadPolicy.FRESH),
                    ),
                },
                network=network,
                max_memory=bash_cfg.python_max_memory,
                runtimes=[
                    MontyRuntime(
                        config=MontyConfig(max_memory=bash_cfg.python_max_memory)
                    )
                ],
                env={"HOME": "/home", "PWD": "/home"},
            )

        ws = self.workspace
        if previous != self.bindings:
            for mount, old_b in previous.items():
                new_b = self.bindings.get(mount)
                if new_b is None or new_b.root != old_b.root:
                    await ws.unmount(mount)
            shared_spec = self._shared_read_spec()
            cache_shared = shared_spec.policy != ReadPolicy.FRESH
            for mount, binding in self.bindings.items():
                mode = MountMode.EXEC if binding.writable else MountMode.READ
                old_b = previous.get(mount)
                if old_b is None or old_b.root != binding.root:
                    ws.add_mount(
                        mount,
                        LetFS(
                            self.s.letfs,
                            actor,
                            workspace_id,
                            binding.storage,
                            binding.root,
                            letfs_cfg,
                            caches_reads=cache_shared,
                        ),
                        mode=mode,
                        read=shared_spec,
                    )
                elif old_b.writable != binding.writable:
                    ws.set_mount_mode(mount, mode)
            self.mounted = dict(self.bindings)

        if self.session is None:
            self.session = await ws.session("tools")
        return self.session

    async def notify_changed(self, target_path: str) -> None:
        await self.open()
        assert self.workspace is not None
        await self.workspace.notify(
            FileEvent(
                path=path_spec(target_path),
                kind=FileChangeKind.UNKNOWN,
                timestamp=datetime.now(UTC),
            )
        )

    async def write_spill(self, prefix: str, full_text: str) -> str | None:
        try:
            session = await self.open()
            target = spill_filename(prefix, self.s.settings.tool_output)
            await session.vfs.dispatch(
                "write_text_optimistic", path_spec(target), content=full_text
            )
            await self.notify_changed(target)
            return target
        except Exception:
            return None

    async def sweep_spill_dir(self) -> None:
        try:
            session = await self.open()
            spill_dir = self.s.settings.tool_output.spill_dir
            retention_secs = self.s.settings.tool_output.retention_days * 86400
            names = await session.vfs.readdir(spill_dir)
            cutoff = datetime.now(UTC).timestamp() - retention_secs
            for name in names:
                if not name:
                    continue
                full = posixpath.join(spill_dir, name)
                try:
                    st = await session.vfs.stat(full)
                except Exception:
                    continue
                mod = st.modified
                if not mod:
                    continue
                try:
                    mod_ts = datetime.fromisoformat(
                        mod.replace("Z", "+00:00")
                    ).timestamp()
                except ValueError:
                    continue
                if mod_ts < cutoff:
                    await session.vfs.unlink(full)
        except Exception:
            return

    async def resolve_ref(self, virtual_path: str) -> dict[str, object]:
        session = await self.open()
        abs_path = canonical_path(virtual_path)
        st = await session.vfs.stat(abs_path)
        extra = st.extra or {}
        return {
            "path": abs_path,
            "storage_id": str(extra.get("storage_id", "")),
            "node_id": str(extra.get("node_id", "")),
            "name": st.name or posixpath.basename(abs_path),
            "kind": "folder" if st.type.value == "directory" else "file",
            "media_type": str(extra.get("media_type", "")),
            "size_bytes": int(st.size or 0),
        }

    async def run_shell(
        self, command: str, *, workdir: str | None = None, timeout: int | None = None
    ) -> ShellOutcome:
        session = await self.open()
        bash_cfg = self.s.settings.bash
        eff_timeout = (
            bash_cfg.default_timeout_seconds
            if timeout is None
            else max(1, min(timeout, bash_cfg.max_timeout_seconds))
        )
        cwd = canonical_path(workdir) if workdir else "/home"
        start = monotonic()
        try:
            result = await asyncio.wait_for(
                session.shell(command, cwd=cwd), timeout=float(eff_timeout)
            )
            exit_code = int(result.exit_code)
            stdout = (
                (result.stdout or b"").decode("utf-8", errors="replace")
                if isinstance(result.stdout, (bytes, bytearray))
                else str(result.stdout or "")
            )
            stderr = (
                (result.stderr or b"").decode("utf-8", errors="replace")
                if isinstance(result.stderr, (bytes, bytearray))
                else str(result.stderr or "")
            )
        except TimeoutError:
            wall_ms = int((monotonic() - start) * 1000)
            return ShellOutcome(
                output=f"Command timed out after {eff_timeout}s.\nExit code: 124",
                exit_code=124,
                wall_time_ms=wall_ms,
                truncated=False,
                output_path=None,
            )

        wall_ms = int((monotonic() - start) * 1000)
        combined = stdout
        if stderr:
            combined = f"{stdout}\n{stderr}" if stdout else stderr

        to_cfg = self.s.settings.tool_output
        trunc = truncate_tail(
            combined,
            max_lines=to_cfg.max_lines,
            max_bytes=to_cfg.max_bytes,
            max_line_length=to_cfg.max_line_length,
        )
        spill_path: str | None = None
        if trunc.truncated:
            spill_path = await self.write_spill("bash", combined)
        rendered = format_tail_truncated(trunc, spill_path)
        if exit_code != 0:
            rendered = (
                f"{rendered}\nExit code: {exit_code}"
                if rendered
                else f"Exit code: {exit_code}"
            )
        return ShellOutcome(
            output=rendered,
            exit_code=exit_code,
            wall_time_ms=wall_ms,
            truncated=trunc.truncated,
            output_path=spill_path,
        )

    async def close(self) -> None:
        if self.workspace is not None:
            await self.workspace.close()
            self.workspace = None
            self.session = None
