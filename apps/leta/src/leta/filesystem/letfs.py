"""Mirage BaseVFS drivers backed by LetFS gRPC services."""

from __future__ import annotations

import asyncio
import base64
import errno
import posixpath
from contextlib import suppress
from contextvars import ContextVar
from typing import TYPE_CHECKING, override
from uuid import UUID, uuid4, uuid5

import google_crc32c
import grpc
import httpx
from google.protobuf.empty_pb2 import Empty
from mirage import BaseVFS, ContentType, FileStat, FileType, PathSpec
from mirage.io.network import run_with_network
from mirage.io.stream import ensure_stream
from mirage.io.types import ByteSource, materialize
from mirage.types import DirListing
from mirage.utils.key_prefix import mounted_path
from mirage.vfs.call import vfs_call
from mirage.vfs.types import Effect, Target
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_sdk.file_types import classify_file

from leta.filesystem.types import (
    GlobHit,
    GlobResult,
    GrepHit,
    GrepResult,
    SemanticHit,
    VersionedText,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from openlet_api.letfs.v1.letfs_pb2_grpc import LetFSServiceAsyncStub
    from openlet_sdk.config import LetFSSettings

    from leta.auth import Actor

current_operation: ContextVar[UUID | None] = ContextVar("file_operation", default=None)


def node_to_stat(node: fs.Node) -> FileStat:
    """Convert a LetFS protobuf Node into a Mirage FileStat."""
    content = None
    if node.HasField("file"):
        if node.file.type == fs.FILE_TYPE_TEXT:
            content = ContentType.TEXT
        elif node.file.type == fs.FILE_TYPE_BLOB:
            with suppress(ValueError):
                content = ContentType(node.file.media_type)
    return FileStat(
        name=node.name,
        type=(
            FileType.DIRECTORY if node.kind == fs.NODE_KIND_DIRECTORY else FileType.FILE
        ),
        size=node.file.size_bytes if node.HasField("file") else None,
        modified=(
            node.updated_at.ToJsonString() if node.HasField("updated_at") else None
        ),
        revision=str(node.file.version) if node.HasField("file") else None,
        content=content,
        extra={
            "node_id": node.id,
            "storage_id": node.storage_id,
            "media_type": node.file.media_type,
            "readonly": node.readonly,
            "is_blob": node.HasField("file") and node.file.type == fs.FILE_TYPE_BLOB,
        },
    )


async def _grpc_call[T](result: Awaitable[T]) -> T:
    try:
        return await result
    except grpc.aio.AioRpcError as error:
        code = error.code()
        if code == grpc.StatusCode.NOT_FOUND:
            raise FileNotFoundError(errno.ENOENT, "file not found") from error
        if code == grpc.StatusCode.ALREADY_EXISTS:
            raise FileExistsError(errno.EEXIST, "file already exists") from error
        if code == grpc.StatusCode.PERMISSION_DENIED:
            raise PermissionError(errno.EACCES, "storage permission denied") from error
        if code in (
            grpc.StatusCode.INVALID_ARGUMENT,
            grpc.StatusCode.ABORTED,
            grpc.StatusCode.FAILED_PRECONDITION,
            grpc.StatusCode.RESOURCE_EXHAUSTED,
        ):
            raise OSError(errno.EINVAL, error.details()) from error
        raise


def _req_id(method: str, storage_id: str, root_id: str, vfs_path: str) -> str:
    op = current_operation.get()
    if op is None:
        return str(uuid4())
    return str(uuid5(op, f"{method}/{storage_id}/{root_id}/{vfs_path}"))


class LetFS(BaseVFS):
    """Mirage VFS driver mounted at a specific LetFS storage root node."""

    name = "letfs"
    caches_reads = True
    sizes_always_known = True

    def __init__(  # noqa: PLR0917  # Positional constructor signature shared across internal mount builders
        self,
        stub: LetFSServiceAsyncStub,
        actor: Actor,
        workspace: UUID,
        storage: UUID,
        root: UUID,
        settings: LetFSSettings,
        *,
        caches_reads: bool = True,
    ) -> None:
        super().__init__(caches_reads=caches_reads)
        self.stub = stub
        self.actor = actor
        self.workspace = workspace
        self.storage = storage
        self.root = root
        self.text_limit = settings["max_text_bytes"]
        self.blob_limit = min(
            settings["max_blob_bytes"], settings["multipart_threshold_bytes"] - 1
        )

    def locator(self, path: PathSpec) -> fs.NodeLocator:
        """Build a LetFS NodeLocator relative to this mount's root_node_id."""
        return fs.NodeLocator(path=path.vfs_path or ".", root_node_id=str(self.root))

    @override
    async def stat(self, path: PathSpec) -> FileStat:
        """Fetch file or directory metadata for path."""
        node = await _grpc_call(
            self.stub.Stat(
                fs.NodeRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    target=self.locator(path),
                ),
                metadata=self.actor.metadata,
                timeout=15,
            )
        )
        return node_to_stat(node)

    @override
    async def readdir(self, path: PathSpec) -> list[FileStat] | DirListing:
        """List directory entries beneath path."""
        rows: list[FileStat] = []
        token = ""
        while True:
            resp = await _grpc_call(
                self.stub.ListNodes(
                    fs.ListNodesRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        parent=self.locator(path),
                        page_size=100,
                        page_token=token,
                    ),
                    metadata=self.actor.metadata,
                    timeout=15,
                )
            )
            rows.extend(node_to_stat(node) for node in resp.nodes)
            token = resp.next_page_token
            if not token or len(rows) >= 2000:
                return DirListing(rows, partial=bool(token))

    @override
    async def read(self, path: PathSpec) -> bytes:
        """Read the full UTF-8 text bytes of a file."""
        resp = await _grpc_call(
            self.stub.ReadText(
                fs.ReadTextRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    target=self.locator(path),
                ),
                metadata=self.actor.metadata,
                timeout=15,
            )
        )
        return resp.content.encode("utf-8")

    @override
    async def first_lines(self, path: PathSpec, n: int) -> bytes:
        """Read the first n lines of a text file."""
        resp = await _grpc_call(
            self.stub.ReadText(
                fs.ReadTextRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    target=self.locator(path),
                    head_lines=n,
                ),
                metadata=self.actor.metadata,
                timeout=15,
            )
        )
        return resp.content.encode("utf-8")

    @override
    async def last_lines(self, path: PathSpec, n: int) -> bytes:
        """Read the last n lines of a text file."""
        resp = await _grpc_call(
            self.stub.ReadText(
                fs.ReadTextRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    target=self.locator(path),
                    tail_lines=n,
                ),
                metadata=self.actor.metadata,
                timeout=15,
            )
        )
        return resp.content.encode("utf-8")

    @override
    async def line_count(self, path: PathSpec) -> int:
        """Return the line count reported by LetFS for a text file."""
        resp = await _grpc_call(
            self.stub.ReadText(
                fs.ReadTextRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    target=self.locator(path),
                    head_lines=1,
                    include_metrics=True,
                ),
                metadata=self.actor.metadata,
                timeout=15,
            )
        )
        return int(resp.metrics.lines)

    @override
    async def files_containing(
        self, path: PathSpec, text: str, *, whole_word: bool, ignore_case: bool
    ) -> list[PathSpec] | None:
        """Find files beneath path containing literal text via server-side grep."""
        if whole_word:
            return None
        resp = await _grpc_call(
            self.stub.Grep(
                fs.GrepRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    root=self.locator(path),
                    pattern=text,
                    literal=True,
                    case_sensitive=not ignore_case,
                    limit=100,
                ),
                metadata=self.actor.metadata,
                timeout=30,
            )
        )
        if resp.truncated:
            return None
        seen: set[str] = set()
        found: list[PathSpec] = []
        for hit in resp.hits:
            rel = (
                posixpath.join("/", path.vfs_path, hit.path)
                if hit.path != "."
                else posixpath.join("/", path.vfs_path)
            )
            if rel in seen:
                continue
            seen.add(rel)
            found.append(mounted_path(path, rel))
        return found

    @override
    async def lines_containing(
        self, path: PathSpec, text: str, *, ignore_case: bool
    ) -> bytes | None:
        """Return matching lines beneath path via server-side grep."""
        resp = await _grpc_call(
            self.stub.Grep(
                fs.GrepRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    root=self.locator(path),
                    pattern=text,
                    literal=True,
                    case_sensitive=not ignore_case,
                    limit=100,
                ),
                metadata=self.actor.metadata,
                timeout=30,
            )
        )
        if resp.truncated:
            return None
        return "".join(f"{hit.line_text}\n" for hit in resp.hits).encode("utf-8")

    @override
    async def read_tree(self, path: PathSpec) -> dict[str, FileStat] | None:
        """Fetch a bounded recursive subtree snapshot beneath path."""
        resp = await _grpc_call(
            self.stub.ReadTree(
                fs.ReadTreeRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    root=self.locator(path),
                    max_depth=32,
                    max_nodes=1000,
                ),
                metadata=self.actor.metadata,
                timeout=15,
            )
        )
        if resp.truncated:
            return None
        return {
            entry.path: node_to_stat(entry.node)
            for entry in resp.entries
            if entry.path not in ("", ".")
        }

    @vfs_call(effect=Effect.READ, target=Target.ANY)
    async def glob_files(
        self,
        path: PathSpec,
        pattern: str,
        *,
        include_hidden: bool = False,
        limit: int = 100,
    ) -> GlobResult:
        """Search paths beneath path matching a glob pattern."""
        resp = await _grpc_call(
            self.stub.Glob(
                fs.GlobRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    root=self.locator(path),
                    pattern=pattern,
                    include_hidden=include_hidden,
                    limit=max(1, min(limit, 100)),
                ),
                metadata=self.actor.metadata,
                timeout=30,
            )
        )
        hits: list[GlobHit] = []
        for h in resp.hits:
            full = posixpath.normpath(posixpath.join(path.virtual, h.path))
            hits.append(
                GlobHit(
                    path=full,
                    node_id=h.node_id,
                    kind="directory" if h.kind == fs.NODE_KIND_DIRECTORY else "file",
                    artifact_path=h.artifact_path,
                    size_bytes=int(h.size_bytes),
                )
            )
        return GlobResult(hits=hits, truncated=bool(resp.truncated))

    @vfs_call(effect=Effect.READ, target=Target.ANY)
    async def grep_files(
        self,
        path: PathSpec,
        pattern: str,
        *,
        include_glob: str = "",
        literal: bool = False,
        case_sensitive: bool = True,
        limit: int = 100,
    ) -> GrepResult:
        """Search file contents beneath path using regex or literal matching."""
        resp = await _grpc_call(
            self.stub.Grep(
                fs.GrepRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    root=self.locator(path),
                    pattern=pattern,
                    include_glob=include_glob,
                    literal=literal,
                    case_sensitive=case_sensitive,
                    limit=max(1, min(limit, 100)),
                ),
                metadata=self.actor.metadata,
                timeout=30,
            )
        )
        hits: list[GrepHit] = []
        for h in resp.hits:
            full = (
                path.virtual
                if h.path == "."
                else posixpath.normpath(posixpath.join(path.virtual, h.path))
            )
            hits.append(
                GrepHit(
                    path=full,
                    line_number=int(h.line_number),
                    line_text=h.line_text,
                    node_id=h.node_id,
                    artifact_path=h.artifact_path,
                )
            )
        return GrepResult(hits=hits, truncated=bool(resp.truncated))

    @vfs_call(effect=Effect.READ, target=Target.FILE)
    async def read_text_with_version(self, path: PathSpec) -> VersionedText:
        """Read a text file along with its optimistic-concurrency version."""
        resp = await _grpc_call(
            self.stub.ReadText(
                fs.ReadTextRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    target=self.locator(path),
                ),
                metadata=self.actor.metadata,
                timeout=15,
            )
        )
        return VersionedText(text=resp.content, version=int(resp.version))

    @vfs_call(effect=Effect.READ, target=Target.FILE)
    async def read_raw_bytes(self, path: PathSpec, max_bytes: int) -> bytes:
        """Download raw file bytes up to max_bytes from text or presigned blob storage."""
        dl = await _grpc_call(
            self.stub.GetDownload(
                fs.NodeRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    target=self.locator(path),
                ),
                metadata=self.actor.metadata,
                timeout=15,
            )
        )
        if dl.HasField("text"):
            raw = dl.text.content.encode("utf-8")
            if len(raw) > max_bytes:
                raise ValueError(f"file exceeds {max_bytes} bytes")
            return raw
        if dl.HasField("blob") and dl.blob.url:

            async def _fetch_blob() -> bytes:
                async with (
                    httpx.AsyncClient(timeout=30.0) as client,
                    client.stream("GET", dl.blob.url) as resp,
                ):
                    resp.raise_for_status()
                    buf = bytearray()
                    async for chunk in resp.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > max_bytes:
                            raise ValueError(f"file exceeds {max_bytes} bytes")
                    return bytes(buf)

            return await run_with_network(None, _fetch_blob())
        raise FileNotFoundError(errno.ENOENT, "download unavailable")

    @vfs_call(effect=Effect.READ, target=Target.ANY)
    async def semantic_search(
        self,
        path: PathSpec,
        query: str,
        limit: int = 10,
        *,
        baggage: str | None = None,
    ) -> list[SemanticHit]:
        """Run semantic search scoped to path with optional W3C trace baggage."""
        scope_path = "/" + path.vfs_path.lstrip("/") if path.vfs_path else "/"
        meta = (
            (*self.actor.metadata, ("baggage", baggage))
            if baggage
            else self.actor.metadata
        )
        resp = await _grpc_call(
            self.stub.SemanticSearch(
                fs.SemanticSearchRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    root=fs.SemanticScope(path=scope_path),
                    query=query,
                    limit=max(1, min(limit, 25)),
                ),
                metadata=meta,
                timeout=30,
            )
        )
        mount_root = path.virtual.removesuffix(path.vfs_path).rstrip("/") or "/"
        out: list[SemanticHit] = []
        for h in resp.hits:
            virt = posixpath.normpath(posixpath.join(mount_root, h.path.lstrip("/")))
            out.append(
                SemanticHit(
                    path=virt,
                    artifact_path=h.artifact_path,
                    file_id=h.file_id,
                    score=float(h.score),
                    text=h.text,
                )
            )
        return out

    @vfs_call(effect=Effect.WRITE, target=Target.FILE, creates=True)
    async def write_text_optimistic(
        self,
        path: PathSpec,
        content: str,
        expected_version: int | None = None,
    ) -> FileStat:
        """Write or create a text file with optional optimistic-concurrency version check."""
        if expected_version is not None:
            node = await _grpc_call(
                self.stub.MutateText(
                    fs.MutateTextRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        target=self.locator(path),
                        replace=content,
                        expected_version=expected_version,
                        request_id=_req_id(
                            "replace", str(self.storage), str(self.root), path.vfs_path
                        ),
                    ),
                    metadata=self.actor.metadata,
                    timeout=30,
                )
            )
            return node_to_stat(node)

        try:
            node = await _grpc_call(
                self.stub.MutateText(
                    fs.MutateTextRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        target=self.locator(path),
                        replace=content,
                        request_id=_req_id(
                            "replace", str(self.storage), str(self.root), path.vfs_path
                        ),
                    ),
                    metadata=self.actor.metadata,
                    timeout=30,
                )
            )
            return node_to_stat(node)
        except FileNotFoundError:
            parent, name = posixpath.split(path.vfs_path)
            if parent:
                await _grpc_call(
                    self.stub.CreateDirectories(
                        fs.CreateDirectoriesRequest(
                            workspace_id=str(self.workspace),
                            storage_id=str(self.storage),
                            base=fs.NodeLocator(path=".", root_node_id=str(self.root)),
                            path=parent,
                        ),
                        metadata=self.actor.metadata,
                        timeout=15,
                    )
                )
            _, media = classify_file(name)
            node = await _grpc_call(
                self.stub.CreateNode(
                    fs.CreateNodeRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        parent=fs.NodeLocator(
                            path=parent or ".", root_node_id=str(self.root)
                        ),
                        name=name,
                        text=fs.TextContent(
                            content=content,
                            media_type=media or "text/plain",
                        ),
                        request_id=_req_id(
                            "create", str(self.storage), str(self.root), path.vfs_path
                        ),
                    ),
                    metadata=self.actor.metadata,
                    timeout=30,
                )
            )
            return node_to_stat(node)

    async def _upload_blob(self, path: PathSpec, data: bytes, media: str) -> FileStat:
        req = fs.CreateUploadRequest(
            workspace_id=str(self.workspace),
            storage_id=str(self.storage),
            size_bytes=len(data),
            media_type=media,
            checksum=base64.b64encode(google_crc32c.Checksum(data).digest()).decode(
                "ascii"
            ),
            request_id=_req_id(
                "upload", str(self.storage), str(self.root), path.vfs_path
            ),
        )
        try:
            existing = await self.stat(path)
        except FileNotFoundError:
            parent, name = posixpath.split(path.vfs_path)
            if parent:
                await _grpc_call(
                    self.stub.CreateDirectories(
                        fs.CreateDirectoriesRequest(
                            workspace_id=str(self.workspace),
                            storage_id=str(self.storage),
                            base=fs.NodeLocator(path=".", root_node_id=str(self.root)),
                            path=parent,
                        ),
                        metadata=self.actor.metadata,
                        timeout=15,
                    )
                )
            req.create.CopyFrom(
                fs.UploadCreate(
                    parent=fs.NodeLocator(
                        path=parent or ".", root_node_id=str(self.root)
                    ),
                    name=name,
                )
            )
        else:
            if (
                existing.type != FileType.FILE
                or existing.content == ContentType.TEXT
                or existing.revision is None
            ):
                raise OSError("blob write requires a new path or an existing blob")
            req.replace.CopyFrom(
                fs.UploadReplace(
                    target=self.locator(path), expected_version=int(existing.revision)
                )
            )

        upload = await _grpc_call(
            self.stub.CreateUpload(req, metadata=self.actor.metadata, timeout=10)
        )
        if upload.HasField("completed"):
            return node_to_stat(upload.completed)
        if upload.transfer.multipart or not upload.transfer.put_url:
            raise OSError("LetFS did not return a single-part upload URL")
        try:

            async def _put_blob() -> None:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    resp = await http.put(
                        upload.transfer.put_url,
                        headers=dict(upload.transfer.headers),
                        content=data,
                    )
                    if resp.status_code != 412:
                        resp.raise_for_status()

            await run_with_network(None, _put_blob())
            node = await _grpc_call(
                self.stub.CompleteUpload(
                    fs.CompleteUploadRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        upload_id=upload.id,
                    ),
                    metadata=self.actor.metadata,
                    timeout=15,
                )
            )
            return node_to_stat(node)
        except OSError, grpc.RpcError, httpx.HTTPError, asyncio.CancelledError:
            with suppress(Exception):
                await self.stub.AbortUpload(
                    fs.UploadRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        upload_id=upload.id,
                    ),
                    metadata=self.actor.metadata,
                    timeout=5,
                )
            raise

    @override
    async def write(self, path: PathSpec, data: ByteSource) -> None:
        """Write a text or binary file to LetFS based on filename classification."""
        raw = await materialize(ensure_stream(data))
        _, name = posixpath.split(path.vfs_path)
        kind, media = classify_file(name)
        if kind == "blob":
            if len(raw) > self.blob_limit:
                raise OSError(errno.EFBIG, "blob exceeds write size limit")
            await self._upload_blob(path, raw, media)
            return
        if len(raw) > self.text_limit:
            raise OSError(errno.EFBIG, "text file exceeds size limit")
        await self.write_text_optimistic(path, raw.decode("utf-8"))

    @override
    async def append(self, path: PathSpec, data: ByteSource) -> None:
        """Append UTF-8 text to an existing file or create it if absent."""
        raw = await materialize(ensure_stream(data))
        text = raw.decode("utf-8")
        try:
            await _grpc_call(
                self.stub.MutateText(
                    fs.MutateTextRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        target=self.locator(path),
                        append=text,
                        request_id=_req_id(
                            "append", str(self.storage), str(self.root), path.vfs_path
                        ),
                    ),
                    metadata=self.actor.metadata,
                    timeout=30,
                )
            )
        except FileNotFoundError:
            await self.write_text_optimistic(path, text)

    @override
    async def mkdir(self, path: PathSpec, parents: bool = False) -> None:
        """Create a directory node or missing parent hierarchy in LetFS."""
        if parents:
            await _grpc_call(
                self.stub.CreateDirectories(
                    fs.CreateDirectoriesRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        base=fs.NodeLocator(path=".", root_node_id=str(self.root)),
                        path=path.vfs_path,
                    ),
                    metadata=self.actor.metadata,
                    timeout=15,
                )
            )
            return
        parent, name = posixpath.split(path.vfs_path)
        await _grpc_call(
            self.stub.CreateNode(
                fs.CreateNodeRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    parent=fs.NodeLocator(
                        path=parent or ".", root_node_id=str(self.root)
                    ),
                    name=name,
                    directory=Empty(),
                    request_id=_req_id(
                        "mkdir", str(self.storage), str(self.root), path.vfs_path
                    ),
                ),
                metadata=self.actor.metadata,
                timeout=15,
            )
        )

    async def remove(self, path: PathSpec, *, recursive: bool = False) -> None:
        """Move a file or directory node to the LetFS trash."""
        _ = recursive
        await _grpc_call(
            self.stub.TrashNode(
                fs.TrashNodeRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    target=self.locator(path),
                    request_id=_req_id(
                        "trash", str(self.storage), str(self.root), path.vfs_path
                    ),
                ),
                metadata=self.actor.metadata,
                timeout=15,
            )
        )

    @override
    async def rename(self, src: PathSpec, dst: PathSpec) -> None:
        """Move or rename a node within the same LetFS storage."""
        parent, name = posixpath.split(dst.vfs_path)
        await _grpc_call(
            self.stub.MoveNode(
                fs.TransferNodeRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    source=self.locator(src),
                    destination_storage_id=str(self.storage),
                    parent=fs.NodeLocator(
                        path=parent or ".", root_node_id=str(self.root)
                    ),
                    name=name,
                    request_id=_req_id(
                        "move", str(self.storage), str(self.root), dst.vfs_path
                    ),
                ),
                metadata=self.actor.metadata,
                timeout=30,
            )
        )


def parse_letfs_by_id_path(vfs_path: str) -> tuple[str, str, str]:
    """Parse '<storage_id>/<node_id>[/<subpath>]' under /letfs mount."""
    parts = [p for p in vfs_path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise PermissionError(
            errno.EACCES,
            "direct enumeration of /letfs is not allowed; specify /letfs/<storage_id>/<node_id>",
        )
    storage_id = str(UUID(parts[0]))
    node_id = str(UUID(parts[1]))
    subpath = "/".join(parts[2:])
    return storage_id, node_id, subpath


class LetFSByID(BaseVFS):
    """Universal canonical LetFS mount at /letfs/<storage_id>/<node_id>[/<subpath>]."""

    name = "letfs_by_id"
    caches_reads = False
    sizes_always_known = True

    def __init__(
        self,
        stub: LetFSServiceAsyncStub,
        actor: Actor,
        workspace: UUID,
        settings: LetFSSettings,
    ) -> None:
        super().__init__()
        self.stub = stub
        self.actor = actor
        self.workspace = workspace
        self.settings = settings

    def _delegate(self, path: PathSpec) -> tuple[LetFS, PathSpec]:
        try:
            storage_id, node_id, subpath = parse_letfs_by_id_path(path.vfs_path)
        except ValueError as exc:
            raise FileNotFoundError(errno.ENOENT, "invalid /letfs path") from exc
        driver = LetFS(
            self.stub,
            self.actor,
            self.workspace,
            UUID(storage_id),
            UUID(node_id),
            self.settings,
        )
        sub_spec = PathSpec(
            virtual=path.virtual,
            directory=path.directory,
            vfs_path=subpath,
        )
        return driver, sub_spec

    @override
    async def stat(self, path: PathSpec) -> FileStat:
        """Stat a node addressed via /letfs/<storage_id>/<node_id>."""
        if not path.vfs_path.strip("/"):
            return FileStat(name="letfs", type=FileType.DIRECTORY)
        driver, sub = self._delegate(path)
        return await driver.stat(sub)

    @override
    async def readdir(self, path: PathSpec) -> list[FileStat] | DirListing:
        """List directory entries beneath path."""
        if not path.vfs_path.strip("/"):
            return []
        driver, sub = self._delegate(path)
        return await driver.readdir(sub)

    @override
    async def read(self, path: PathSpec) -> bytes:
        """Read the full UTF-8 text bytes of a file."""
        driver, sub = self._delegate(path)
        return await driver.read(sub)

    @override
    async def write(self, path: PathSpec, data: ByteSource) -> None:
        """Write a text or binary file to LetFS based on filename classification."""
        driver, sub = self._delegate(path)
        await driver.write(sub, data)

    @vfs_call(effect=Effect.READ, target=Target.ANY)
    async def glob_files(
        self,
        path: PathSpec,
        pattern: str,
        *,
        include_hidden: bool = False,
        limit: int = 100,
    ) -> GlobResult:
        """Search paths beneath path matching a glob pattern."""
        driver, sub = self._delegate(path)
        return await driver.glob_files(
            sub, pattern, include_hidden=include_hidden, limit=limit
        )

    @vfs_call(effect=Effect.READ, target=Target.ANY)
    async def grep_files(
        self,
        path: PathSpec,
        pattern: str,
        *,
        include_glob: str = "",
        literal: bool = False,
        case_sensitive: bool = True,
        limit: int = 100,
    ) -> GrepResult:
        """Search file contents beneath path using regex or literal matching."""
        driver, sub = self._delegate(path)
        return await driver.grep_files(
            sub,
            pattern,
            include_glob=include_glob,
            literal=literal,
            case_sensitive=case_sensitive,
            limit=limit,
        )

    @vfs_call(effect=Effect.READ, target=Target.FILE)
    async def read_text_with_version(self, path: PathSpec) -> VersionedText:
        """Read a text file along with its optimistic-concurrency version."""
        driver, sub = self._delegate(path)
        return await driver.read_text_with_version(sub)

    @vfs_call(effect=Effect.READ, target=Target.FILE)
    async def read_raw_bytes(self, path: PathSpec, max_bytes: int) -> bytes:
        """Download raw file bytes up to max_bytes via the delegated LetFS driver."""
        driver, sub = self._delegate(path)
        return await driver.read_raw_bytes(sub, max_bytes)

    @vfs_call(effect=Effect.WRITE, target=Target.FILE, creates=True)
    async def write_text_optimistic(
        self,
        path: PathSpec,
        content: str,
        expected_version: int | None = None,
    ) -> FileStat:
        """Write or create a text file with optional optimistic-concurrency version check."""
        driver, sub = self._delegate(path)
        return await driver.write_text_optimistic(sub, content, expected_version)
