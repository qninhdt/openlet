"""Workspace mount discovery, Mirage session lifecycle, and sandboxed shell runner."""

from __future__ import annotations

import asyncio
import logging
import posixpath
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING, cast
from uuid import UUID

import grpc.aio
from mirage import (
    FileStat,
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

from leta.auth import Actor
from leta.filesystem.letfs import LetFS, LetFSByID
from leta.filesystem.types import (
    FileRef,
    GlobResult,
    GrepResult,
    SemanticHit,
    VersionedText,
    parse_stat_extra,
)
from leta.truncation import (
    format_tail_truncated,
    spill_filename,
    truncate_tail,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Mapping, Sequence

    from leta.config import Services
    from leta.inbox import InboxSender
    from leta.runs import AgentRuntimeRecord

logger = logging.getLogger(__name__)

PUBLIC_ONLY_DENIED_DOMAINS: tuple[str, ...] = (
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
)


def canonical_path(value: str = "~") -> str:
    """Normalize a workspace-relative or tilde path into an absolute virtual path."""
    return norm(posixpath.join("/home", expand_tilde(value.strip() or "~", "/home")))


def path_spec(value: str) -> PathSpec:
    """Build a Mirage PathSpec from a virtual workspace path."""
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
        """Acquire locks for all normalized paths in deterministic sorted order."""
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
    """Resolved LetFS storage binding and writability for a virtual mount point."""

    root: UUID
    writable: bool
    storage: UUID


@dataclass(frozen=True, slots=True)
class ShellOutcome:
    """Structured output, exit status, and spill path from a sandboxed shell run."""

    output: str
    exit_code: int
    wall_time_ms: int
    truncated: bool
    output_path: str | None


class Filesystem:
    """Per-agent Mirage workspace facade managing dynamic mounts, files, and shell."""

    def __init__(self, services: Services, agent: AgentRuntimeRecord) -> None:
        self.s = services
        self.agent = agent
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

    async def _fetch_storages(
        self, actor: Actor, workspace_id: str
    ) -> list[fs.Storage]:
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
                return storages

    async def _fetch_conversations(
        self, actor: Actor, workspace_id: str
    ) -> list[chat_pb.Conversation]:
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
            except grpc.aio.AioRpcError:
                logger.debug(
                    "ListConversations failed during mount discovery", exc_info=True
                )
                return convs
            convs.extend(c_resp.conversations)
            c_token = c_resp.next_page_token
            if not c_token:
                return convs

    async def _resolve_directory_handles(
        self,
        actor: Actor,
        storages: list[fs.Storage],
        convs: list[chat_pb.Conversation],
    ) -> tuple[dict[str, str], dict[str, tuple[str, str]], dict[str, str]]:
        user_ids: set[str] = {
            st.ownership.user_id for st in storages if st.ownership.user_id
        }
        peer_agent_ids: set[str] = set()
        for c in convs:
            if c.type != "dm":
                continue
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
        return user_handles, user_info, agent_handles

    @staticmethod
    def _build_conv_handles(
        actor: Actor,
        convs: list[chat_pb.Conversation],
        user_handles: dict[str, str],
        agent_handles: dict[str, str],
    ) -> dict[str, str]:
        dm_conv_handles: dict[str, str] = {}
        group_conv_handles: dict[str, str] = {}
        used_chat_handles: set[str] = set()
        for c in convs:
            if c.type != "dm":
                continue
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

        return {**dm_conv_handles, **group_conv_handles}

    async def _ensure_active_conv_bindings(
        self,
        *,
        actor: Actor,
        workspace_id: str,
        convs: list[chat_pb.Conversation],
        conv_handles: dict[str, str],
        bound_conv_ids: set[str],
        bindings: dict[str, StorageMount],
    ) -> None:
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
            except grpc.aio.AioRpcError:
                logger.debug(
                    "EnsureConversationStorage failed for %s", c.id, exc_info=True
                )
                continue
            if ensured.storage_id and ensured.root_node_id:
                bindings[f"/chat/{ch}"] = StorageMount(
                    root=UUID(ensured.root_node_id),
                    writable=True,
                    storage=UUID(ensured.storage_id),
                )

    async def discover(self, *, force: bool = False) -> None:
        """Discover workspace, user, and conversation storages and refresh mount bindings."""
        if not force and monotonic() - self.discovered < 30.0:
            return
        actor = Actor("agent", self.agent.leta_id)
        workspace_id = str(self.agent.workspace_id)

        storages = await self._fetch_storages(actor, workspace_id)
        convs = await self._fetch_conversations(actor, workspace_id)
        user_handles, user_info, agent_handles = await self._resolve_directory_handles(
            actor, storages, convs
        )
        conv_handles = self._build_conv_handles(
            actor, convs, user_handles, agent_handles
        )

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
        await self._ensure_active_conv_bindings(
            actor=actor,
            workspace_id=workspace_id,
            convs=convs,
            conv_handles=conv_handles,
            bound_conv_ids=bound_conv_ids,
            bindings=bindings,
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
        """Return the virtual /chat/<handle> mount path for a chat reply address."""
        addr = reply_address.strip()
        if addr.startswith("chat:"):
            conv_id = addr.removeprefix("chat:").strip()
            return self.conv_mounts.get(conv_id)
        return self.conv_mounts.get(addr)

    def enrich_sender(self, sender: InboxSender) -> InboxSender:
        """Populate missing handle/name fields on an InboxSender using discovered directories."""
        if sender.handle:
            return sender
        if sender.type == "user" and sender.id in self.user_info:
            name, handle = self.user_info[sender.id]
            return sender.model_copy(
                update={
                    "handle": handle or sender.handle,
                    "name": sender.name or name,
                }
            )
        if sender.type == "agent" and sender.id in self.agent_handles:
            return sender.model_copy(update={"handle": self.agent_handles[sender.id]})
        return sender

    def writable_mounts(self) -> list[str]:
        """Return sorted virtual mount paths that allow write operations."""
        mounts = ["/home"]
        mounts.extend(sorted(m for m, b in self.bindings.items() if b.writable))
        return mounts

    def all_mounts(self) -> list[str]:
        """Return all sorted virtual mount paths visible in this workspace."""
        mounts = ["/home"]
        mounts.extend(sorted(self.bindings.keys()))
        return mounts

    async def open(self) -> Session:
        """Open or refresh the Mirage workspace session under a concurrency lock."""
        async with self._lock:
            return await self._open_locked()

    async def _open_locked(self) -> Session:
        previous = self.mounted
        await self.discover()
        actor = Actor("agent", self.agent.leta_id)
        workspace_id = self.agent.workspace_id
        storage_id = self.agent.storage_id
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
        """Notify the Mirage workspace cache that target_path was modified."""
        await self.open()
        if self.workspace is None:
            raise RuntimeError("workspace not initialized after open()")
        await self.workspace.notify(
            FileEvent(
                path=path_spec(target_path),
                kind=FileChangeKind.UNKNOWN,
                timestamp=datetime.now(UTC),
            )
        )

    async def write_spill(self, prefix: str, full_text: str) -> str | None:
        """Best-effort spill of truncated output to /home/.tool-output."""
        try:
            target = spill_filename(prefix, self.s.settings.tool_output)
            await self.write_text_optimistic(target, content=full_text)
            await self.notify_changed(target)
        except OSError, grpc.aio.AioRpcError:
            logger.warning("failed to write tool output spill file", exc_info=True)
            return None
        else:
            return target

    async def sweep_spill_dir(self) -> None:
        """Best-effort cleanup of expired tool-output spill files."""
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
                except OSError, grpc.aio.AioRpcError:
                    logger.debug(
                        "sweep_spill_dir stat failed for %s", full, exc_info=True
                    )
                    continue
                mod = st.modified
                if not mod:
                    continue
                try:
                    mod_ts = datetime.fromisoformat(mod).timestamp()
                except ValueError:
                    continue
                if mod_ts < cutoff:
                    await session.vfs.unlink(full)
        except OSError, grpc.aio.AioRpcError:
            logger.debug("sweep_spill_dir failed", exc_info=True)

    async def read_text_with_version(self, path: str) -> VersionedText:
        """Read a virtual file's text and optimistic-concurrency version."""
        session = await self.open()
        # mirage's vfs.dispatch returns untyped object; LetFS returns VersionedText.
        val, _ = await session.vfs.dispatch("read_text_with_version", path_spec(path))
        return cast("VersionedText", val)

    async def read_raw_bytes(self, path: str, *, max_bytes: int) -> bytes:
        """Read raw bytes from a virtual file up to max_bytes."""
        session = await self.open()
        val, _ = await session.vfs.dispatch(
            "read_raw_bytes", path_spec(path), max_bytes=max_bytes
        )
        return cast("bytes", val)

    async def write_text_optimistic(
        self,
        path: str,
        *,
        content: str,
        expected_version: int | None = None,
    ) -> FileStat:
        """Write text to path with an optional expected_version check."""
        session = await self.open()
        val, _ = await session.vfs.dispatch(
            "write_text_optimistic",
            path_spec(path),
            content=content,
            expected_version=expected_version,
        )
        return cast("FileStat", val)

    async def glob_files(
        self,
        root: str,
        *,
        pattern: str,
        include_hidden: bool = False,
        limit: int = 100,
    ) -> GlobResult:
        """Run glob search under root via the Mirage VFS dispatcher."""
        session = await self.open()
        val, _ = await session.vfs.dispatch(
            "glob_files",
            path_spec(root),
            pattern=pattern,
            include_hidden=include_hidden,
            limit=limit,
        )
        return cast("GlobResult", val)

    async def grep_files(
        self,
        root: str,
        *,
        pattern: str,
        include_glob: str = "",
        literal: bool = False,
        case_sensitive: bool = True,
        limit: int = 100,
    ) -> GrepResult:
        """Run grep search under root via the Mirage VFS dispatcher."""
        session = await self.open()
        val, _ = await session.vfs.dispatch(
            "grep_files",
            path_spec(root),
            pattern=pattern,
            include_glob=include_glob,
            literal=literal,
            case_sensitive=case_sensitive,
            limit=limit,
        )
        return cast("GrepResult", val)

    async def semantic_search(
        self,
        root: str,
        *,
        query: str,
        limit: int = 10,
        baggage: str | None = None,
    ) -> list[SemanticHit]:
        """Run semantic search under root via the Mirage VFS dispatcher."""
        session = await self.open()
        val, _ = await session.vfs.dispatch(
            "semantic_search",
            path_spec(root),
            query=query,
            limit=limit,
            baggage=baggage,
        )
        return cast("list[SemanticHit]", val)

    async def resolve_ref(self, virtual_path: str) -> FileRef:
        """Resolve a virtual path into its storage ID, node ID, and file metadata."""
        session = await self.open()
        abs_path = canonical_path(virtual_path)
        st = await session.vfs.stat(abs_path)
        extra = parse_stat_extra(st.extra)
        return FileRef(
            path=abs_path,
            storage_id=extra.storage_id,
            node_id=extra.node_id,
            name=st.name or posixpath.basename(abs_path),
            kind="folder" if st.type.value == "directory" else "file",
            media_type=extra.media_type,
            size_bytes=int(st.size or 0),
        )

    async def run_shell(
        self,
        command: str,
        *,
        workdir: str | None = None,
        timeout: int | None = None,  # noqa: ASYNC109  # Kept for leta.runtime callers; enforced via wait_for
    ) -> ShellOutcome:
        """Execute a command in the Mirage sandboxed shell with timeout and truncation."""
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
                if isinstance(result.stdout, bytes | bytearray)
                else str(result.stdout or "")
            )
            stderr = (
                (result.stderr or b"").decode("utf-8", errors="replace")
                if isinstance(result.stderr, bytes | bytearray)
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
        """Close the Mirage workspace and release any active session."""
        if self.workspace is not None:
            await self.workspace.close()
            self.workspace = None
            self.session = None
