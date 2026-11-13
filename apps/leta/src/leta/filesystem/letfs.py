import base64
import errno
import posixpath
from collections.abc import Awaitable
from contextvars import ContextVar
from typing import cast
from uuid import UUID, uuid4

import grpc
from google.protobuf.json_format import MessageToDict
from mirage import BaseVFS, ContentType, FileStat, FileType, PathSpec
from mirage.io.types import ByteSource, materialize
from mirage.types import DirListing
from mirage.utils.key_prefix import mounted_path
from mirage.vfs.call import vfs_call
from mirage.vfs.types import Effect, Target
from openlet_api.letfs.v1 import letfs_pb2 as fs
from openlet_api.letfs.v1.letfs_pb2_grpc import LetFSServiceStub
from openlet_sdk.config import JSON

from ..agents import stable
from ..auth import Actor

current_operation: ContextVar[UUID | None] = ContextVar("file_operation", default=None)


def stat(node: fs.Node) -> FileStat:
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
        content=(
            ContentType.TEXT
            if node.HasField("file") and node.file.type == fs.FILE_TYPE_TEXT
            else None
        ),
        extra={
            "node_id": node.id,
            "media_type": node.file.media_type,
            "readonly": node.readonly,
        },
    )


class LetFS(BaseVFS):
    name = "letfs"
    caches_reads = True
    sizes_always_known = True

    def __init__(
        self,
        stub: LetFSServiceStub,
        actor: Actor,
        workspace: UUID,
        storage: UUID,
        root: UUID,
    ) -> None:
        super().__init__()
        self.stub, self.actor = stub, actor
        self.workspace, self.storage, self.root = workspace, storage, root

    def locator(self, path: PathSpec) -> fs.NodeLocator:
        return fs.NodeLocator(path=path.vfs_path or ".", root_node_id=str(self.root))

    def request_id(self, method: str, path: PathSpec) -> str:
        operation = current_operation.get()
        return str(
            stable(
                operation,
                f"{method}/{self.storage}/{self.root}/{path.vfs_path}",
            )
            if operation
            else uuid4()
        )

    async def call[T](self, result: Awaitable[T]) -> T:
        try:
            return await result
        except grpc.aio.AioRpcError as error:
            code = error.code()
            if code == grpc.StatusCode.NOT_FOUND:
                raise FileNotFoundError(errno.ENOENT, "file not found") from error
            if code == grpc.StatusCode.ALREADY_EXISTS:
                raise FileExistsError(errno.EEXIST, "file already exists") from error
            if code == grpc.StatusCode.PERMISSION_DENIED:
                raise PermissionError(
                    errno.EACCES, "storage permission denied"
                ) from error
            if code in (
                grpc.StatusCode.INVALID_ARGUMENT,
                grpc.StatusCode.ABORTED,
                grpc.StatusCode.FAILED_PRECONDITION,
                grpc.StatusCode.RESOURCE_EXHAUSTED,
            ):
                raise OSError(errno.EINVAL, error.details()) from error
            raise

    async def stat(self, path: PathSpec) -> FileStat:
        node: fs.Node = await self.call(
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
        return stat(node)

    async def readdir(self, path: PathSpec) -> list[FileStat] | DirListing:
        rows: list[FileStat] = []
        token = ""
        while True:
            response: fs.ListNodesResponse = await self.call(
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
            rows.extend(stat(node) for node in response.nodes)
            token = response.next_page_token
            if not token or len(rows) >= 1000:
                return DirListing(rows, partial=bool(token))

    async def read(self, path: PathSpec) -> bytes:
        response: fs.ReadTextResponse = await self.call(
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
        return response.content.encode()

    async def first_lines(self, path: PathSpec, n: int) -> bytes:
        response: fs.ReadTextResponse = await self.call(
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
        return response.content.encode()

    async def last_lines(self, path: PathSpec, n: int) -> bytes:
        response: fs.ReadTextResponse = await self.call(
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
        return response.content.encode()

    async def line_count(self, path: PathSpec) -> int:
        response: fs.ReadTextResponse = await self.call(
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
        return response.metrics.lines

    async def files_containing(
        self, path: PathSpec, text: str, *, whole_word: bool, ignore_case: bool
    ) -> list[PathSpec] | None:
        if whole_word:
            return None
        tree = await self.read_tree(path)
        if tree is None:
            return None
        paths = {item.extra["node_id"]: name for name, item in tree.items()}
        found: list[PathSpec] = []
        token = ""
        while True:
            response = await self.call(
                self.stub.TextSearch(
                    fs.TextSearchRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        root=self.locator(path),
                        query=text,
                        case_sensitive=not ignore_case,
                        page_size=100,
                        page_token=token,
                    ),
                    metadata=self.actor.metadata,
                    timeout=15,
                )
            )
            for hit in response.hits:
                if hit.node.id not in paths:
                    return None
                found.append(
                    mounted_path(
                        path, posixpath.join("/", path.vfs_path, paths[hit.node.id])
                    )
                )
            token = response.next_page_token
            if not token:
                return found

    async def lines_containing(
        self, path: PathSpec, text: str, *, ignore_case: bool
    ) -> bytes | None:
        response = await self.call(
            self.stub.TextSearch(
                fs.TextSearchRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    root=self.locator(path),
                    query=text,
                    case_sensitive=not ignore_case,
                    lines_mode=True,
                    page_size=100,
                ),
                metadata=self.actor.metadata,
                timeout=15,
            )
        )
        if response.next_page_token:
            return None
        return "".join(hit.snippet for hit in response.hits).encode()

    @vfs_call(effect=Effect.READ, target=Target.FILE)
    async def preview(self, path: PathSpec, image: bool) -> JSON:
        if image:
            result = await self.call(
                self.stub.ReadImage(
                    fs.ReadImageRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        target=self.locator(path),
                        max_width=1024,
                        max_height=1024,
                    ),
                    metadata=self.actor.metadata,
                    timeout=30,
                )
            )
            return [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{result.content_type};base64,{base64.b64encode(result.data).decode()}"
                    },
                }
            ]
        response = await self.call(
            self.stub.ReadTree(
                fs.ReadTreeRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    root=self.locator(path),
                    max_depth=4,
                    max_nodes=100,
                ),
                metadata=self.actor.metadata,
                timeout=15,
            )
        )
        return cast(JSON, MessageToDict(response, preserving_proto_field_name=True))

    @vfs_call(effect=Effect.READ, target=Target.FILE)
    async def read_text_lines(self, path: PathSpec, first: int, count: int) -> bytes:
        response: fs.ReadTextResponse = await self.call(
            self.stub.ReadText(
                fs.ReadTextRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    target=self.locator(path),
                    lines=fs.LineRange(first=first, count=count),
                ),
                metadata=self.actor.metadata,
                timeout=15,
            )
        )
        return response.content.encode()

    async def read_tree(self, path: PathSpec) -> dict[str, FileStat] | None:
        response: fs.ReadTreeResponse = await self.call(
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
        if response.truncated:
            return None
        return {
            item.path: stat(item.node)
            for item in response.entries
            if item.path not in ("", ".")
        }

    @vfs_call(effect=Effect.READ, target=Target.DIR)
    async def list_page(
        self, path: PathSpec, cursor: str = "", depth: int = 1
    ) -> dict[str, JSON]:
        if depth > 1:
            if cursor:
                raise ValueError("recursive tree has no cursor")
            response = await self.call(
                self.stub.ReadTree(
                    fs.ReadTreeRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        root=self.locator(path),
                        max_depth=depth,
                        max_nodes=100,
                    ),
                    metadata=self.actor.metadata,
                    timeout=15,
                )
            )
        else:
            response = await self.call(
                self.stub.ListNodes(
                    fs.ListNodesRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        parent=self.locator(path),
                        page_size=20,
                        page_token=cursor,
                    ),
                    metadata=self.actor.metadata,
                    timeout=15,
                )
            )
        items: list[JSON] = []
        if depth > 1:
            for entry in response.entries:
                items.append(
                    {
                        "path": posixpath.join(path.virtual, entry.path),
                        "kind": "directory"
                        if entry.node.kind == fs.NODE_KIND_DIRECTORY
                        else "file",
                        "size_bytes": entry.node.file.size_bytes
                        if entry.node.HasField("file")
                        else None,
                    }
                )
            return {
                "items": items,
                "truncated": response.truncated,
                "next_cursor": None,
            }
        for node in response.nodes:
            items.append(
                {
                    "path": posixpath.join(path.virtual, node.name),
                    "kind": "directory"
                    if node.kind == fs.NODE_KIND_DIRECTORY
                    else "file",
                    "size_bytes": node.file.size_bytes
                    if node.HasField("file")
                    else None,
                }
            )
        return {
            "items": items,
            "truncated": False,
            "next_cursor": response.next_page_token or None,
        }

    @vfs_call(effect=Effect.WRITE, target=Target.FILE, creates=True)
    async def write_text(
        self, path: PathSpec, content: str, overwrite: bool = False
    ) -> FileStat:
        if overwrite:
            try:
                node = await self.call(
                    self.stub.MutateText(
                        fs.MutateTextRequest(
                            workspace_id=str(self.workspace),
                            storage_id=str(self.storage),
                            target=self.locator(path),
                            replace=content,
                            request_id=self.request_id("replace", path),
                        ),
                        metadata=self.actor.metadata,
                        timeout=30,
                    )
                )
                return stat(node)
            except FileNotFoundError:
                pass
        parent, name = posixpath.split(path.vfs_path)
        node = await self.call(
            self.stub.CreateNode(
                fs.CreateNodeRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    parent=fs.NodeLocator(
                        path=parent or ".", root_node_id=str(self.root)
                    ),
                    name=name,
                    text=fs.TextContent(content=content, media_type="text/plain"),
                    request_id=self.request_id("create", path),
                ),
                metadata=self.actor.metadata,
                timeout=30,
            )
        )
        return stat(node)

    @vfs_call(effect=Effect.WRITE, target=Target.FILE)
    async def edit_text(
        self, path: PathSpec, old_text: str, new_text: str, replace_all: bool = False
    ) -> FileStat:
        node = await self.call(
            self.stub.MutateText(
                fs.MutateTextRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    target=self.locator(path),
                    literal_replace=fs.TextReplace(
                        old_text=old_text, new_text=new_text, replace_all=replace_all
                    ),
                    request_id=self.request_id("edit", path),
                ),
                metadata=self.actor.metadata,
                timeout=30,
            )
        )
        return stat(node)

    async def write(self, path: PathSpec, data: ByteSource) -> FileStat:
        return await self.write_text(
            path, (await materialize(data)).decode("utf-8"), overwrite=True
        )

    async def append(self, path: PathSpec, data: ByteSource) -> FileStat:
        content = (await materialize(data)).decode("utf-8")
        try:
            node = await self.call(
                self.stub.MutateText(
                    fs.MutateTextRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        target=self.locator(path),
                        append=content,
                        request_id=self.request_id("append", path),
                    ),
                    metadata=self.actor.metadata,
                    timeout=30,
                )
            )
            return stat(node)
        except FileNotFoundError:
            return await self.write_text(path, content)

    async def mkdir(self, path: PathSpec, parents: bool = False) -> FileStat:
        if parents:
            node = await self.call(
                self.stub.CreateDirectories(
                    fs.CreateDirectoriesRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        base=fs.NodeLocator(
                            node_id=str(self.root), root_node_id=str(self.root)
                        ),
                        path=path.vfs_path,
                    ),
                    metadata=self.actor.metadata,
                    timeout=30,
                )
            )
        else:
            parent, name = posixpath.split(path.vfs_path)
            from google.protobuf.empty_pb2 import Empty

            node = await self.call(
                self.stub.CreateNode(
                    fs.CreateNodeRequest(
                        workspace_id=str(self.workspace),
                        storage_id=str(self.storage),
                        parent=fs.NodeLocator(
                            path=parent or ".", root_node_id=str(self.root)
                        ),
                        name=name,
                        directory=Empty(),
                        request_id=self.request_id("mkdir", path),
                    ),
                    metadata=self.actor.metadata,
                    timeout=30,
                )
            )
        return stat(node)

    async def unlink(self, path: PathSpec) -> None:
        await self.call(
            self.stub.TrashNode(
                fs.TrashNodeRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    target=self.locator(path),
                    request_id=self.request_id("trash", path),
                ),
                metadata=self.actor.metadata,
                timeout=30,
            )
        )

    async def rmdir(self, path: PathSpec) -> None:
        await self.unlink(path)

    async def rm_r(self, path: PathSpec) -> None:
        await self.unlink(path)

    async def rename(self, src: PathSpec, dst: PathSpec) -> FileStat:
        parent, name = posixpath.split(dst.vfs_path)
        node = await self.call(
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
                    request_id=self.request_id("move", dst),
                ),
                metadata=self.actor.metadata,
                timeout=30,
            )
        )
        return stat(node)

    async def copy(self, src: PathSpec, dst: PathSpec) -> FileStat:
        return await self.transfer(self, src, dst)

    async def dir_copy(self, src: PathSpec, dst: PathSpec) -> FileStat:
        return await self.copy(src, dst)

    async def copy_from(self, source: BaseVFS, src: PathSpec, dst: PathSpec) -> None:
        if not isinstance(source, LetFS):
            raise OSError(errno.EXDEV, "different storage backend")
        await self.transfer(source, src, dst)

    async def transfer(self, source: "LetFS", src: PathSpec, dst: PathSpec) -> FileStat:
        parent, name = posixpath.split(dst.vfs_path)
        node = await self.call(
            self.stub.CopyNode(
                fs.TransferNodeRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(source.storage),
                    source=source.locator(src),
                    destination_storage_id=str(self.storage),
                    parent=fs.NodeLocator(
                        path=parent or ".", root_node_id=str(self.root)
                    ),
                    name=name,
                    request_id=self.request_id("copy", dst),
                ),
                metadata=self.actor.metadata,
                timeout=30,
            )
        )
        return stat(node)

    @vfs_call(effect=Effect.READ)
    async def semantic_search(self, path: PathSpec, query: str) -> dict[str, JSON]:
        response = await self.call(
            self.stub.SemanticSearch(
                fs.SemanticSearchRequest(
                    workspace_id=str(self.workspace),
                    storage_id=str(self.storage),
                    root=self.locator(path),
                    query=query,
                    top_k=10,
                ),
                metadata=self.actor.metadata,
                timeout=60,
            )
        )
        parents: dict[str, fs.Node] = {}
        hits: list[JSON] = []
        for hit in response.hits:
            node, parts = hit.node, []
            while node.id != str(self.root):
                parts.append(node.name)
                parent = node.parent_id
                if parent == str(self.root):
                    break
                if parent not in parents:
                    parents[parent] = await self.call(
                        self.stub.Stat(
                            fs.NodeRequest(
                                workspace_id=str(self.workspace),
                                storage_id=str(self.storage),
                                target=fs.NodeLocator(
                                    node_id=parent, root_node_id=str(self.root)
                                ),
                            ),
                            metadata=self.actor.metadata,
                            timeout=15,
                        )
                    )
                node = parents[parent]
            resolved = mounted_path(path, "/" + "/".join(reversed(parts)))
            hits.append({"path": resolved.virtual, "text": hit.snippet})
        return {"path": path.virtual, "hits": hits}
