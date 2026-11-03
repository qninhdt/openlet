import re
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime

from openlet.errors import AppError
from openlet.rpc import RpcClient
from openlet_api.letfs.v1 import letfs_pb2 as pb
from openlet_api.letfs.v1.letfs_pb2_grpc import (
    FilesystemServiceStub,
    IngestServiceStub,
    StorageAdministrationServiceStub,
)


@dataclass(frozen=True)
class Generation:
    file_id: str
    generation: int


@dataclass(frozen=True)
class SemanticMetadata:
    title: str
    description: str
    semantic_type: str
    context: str


@dataclass(frozen=True)
class VectorSpace:
    model: str
    collection: str
    dimension: int

    def validate(self):
        if not self.model.strip() or not re.fullmatch(
            r"[a-zA-Z0-9_-]{1,100}", self.collection
        ):
            raise ValueError("invalid vector model/collection")
        if not 1 <= self.dimension <= 65536:
            raise ValueError("invalid vector dimension")


@dataclass(frozen=True)
class InventoryNode:
    id: str
    parent_id: str | None
    path: str
    name: str
    kind: str
    size_bytes: int
    media_type: str
    title: str
    description: str
    context: str
    inline_content: bytes | None = None
    signed_url: str | None = None


@dataclass(frozen=True)
class ParseInput:
    format: str
    size_bytes: int
    inline_limit_bytes: int
    multipart_threshold_bytes: int
    max_outputs: int
    max_output_bytes: int
    inline_content: bytes | None = None
    signed_url: str | None = None


@dataclass(frozen=True)
class EnrichmentInput:
    nodes: tuple[InventoryNode, ...]
    inline_limit_bytes: int
    multipart_threshold_bytes: int
    max_output_bytes: int


@dataclass(frozen=True)
class IndexInput:
    filesystem_id: str
    source_id: str
    generation: int
    nodes: tuple[InventoryNode, ...]
    vector_space: VectorSpace | None
    max_output_bytes: int


@dataclass(frozen=True)
class OutputDescription:
    path: str
    storage: str
    size_bytes: int
    content_md5: str | None = None


@dataclass(frozen=True)
class OutputScope:
    source: Generation
    stage: str
    upload_id: str


@dataclass(frozen=True)
class Transfer:
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    content_length: int | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class Upload:
    id: str
    status: str
    part_size_bytes: int = 0
    part_count: int = 0
    transfer: Transfer | None = None


@dataclass(frozen=True)
class UploadPart:
    part_number: int
    transfer: Transfer


@dataclass(frozen=True)
class PartReceipt:
    part_number: int
    etag: str


@dataclass(frozen=True)
class UploadReceipt:
    id: str
    status: str
    size_bytes: int


@dataclass(frozen=True)
class EnrichmentUpdate:
    id: str
    path: str
    metadata: SemanticMetadata | None = None
    upload_id: str | None = None


@dataclass(frozen=True)
class Node:
    id: str
    parent_id: str | None
    name: str
    kind: str
    revision: int
    size_bytes: int
    media_type: str | None
    filesystem_id: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    title: str | None = None
    description: str | None = None
    semantic_type: str | None = None
    context: str | None = None


@dataclass(frozen=True)
class Filesystem:
    id: str
    bucket_id: str
    root_id: str
    state: str


@dataclass(frozen=True)
class Locator:
    node_id: str | None = None
    path: str | None = None
    cwd_id: str | None = None
    expected_node_id: str | None = None
    expected_parent_id: str | None = None


@dataclass(frozen=True)
class Mount:
    path: str
    filesystem_id: str


@dataclass(frozen=True)
class PathContext:
    mounts: tuple[Mount, ...]

    @classmethod
    def root(cls, filesystem_id: str):
        return cls((Mount("/", filesystem_id),))


@dataclass(frozen=True)
class Bucket:
    id: str
    limit_bytes: int
    used_bytes: int
    state: str


@dataclass(frozen=True)
class UploadLimits:
    inline_limit_bytes: int
    max_file_bytes: int
    multipart_threshold_bytes: int
    multipart_part_bytes: int


@dataclass(frozen=True)
class BucketUsage:
    bucket: Bucket
    upload_limits: UploadLimits


@dataclass(frozen=True)
class Copy:
    id: str
    destination_root_id: str
    status: str
    committed_nodes: int
    committed_bytes: int
    error_code: str | None = None


@dataclass(frozen=True)
class ProcessingStatus:
    file_id: str
    desired_generation: int
    publication_status: str
    error_code: str | None = None


@dataclass(frozen=True)
class Reprocessing:
    file_id: str
    generation: int
    workflow_id: str


@dataclass(frozen=True)
class TrashEntry:
    id: str
    node_id: str
    parent_id: str | None
    name: str
    actor_id: str
    status: str
    created_at: datetime


@dataclass(frozen=True)
class UploadPublication:
    node_id: str
    status: str
    revision: int


@dataclass(frozen=True)
class FileUpload:
    id: str
    status: str
    transport: str
    expires_at: datetime
    size_bytes: int | None = None
    part_size_bytes: int | None = None
    part_count: int | None = None
    transfer: Transfer | None = None
    publication: UploadPublication | None = None
    receipt: UploadReceipt | None = None


@dataclass(frozen=True)
class UploadDestination:
    parent: Locator
    name: str


@dataclass(frozen=True)
class UploadReplacement:
    locator: Locator
    revision: int | None = None


@dataclass(frozen=True)
class SearchFilters:
    parent: Locator | None = None
    semantic_type: str | None = None
    media_type: str | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    updated_after: datetime | None = None
    updated_before: datetime | None = None


@dataclass(frozen=True)
class Breadcrumb:
    node_id: str
    filename: str


@dataclass(frozen=True)
class SearchMatch:
    file_id: str
    breadcrumb: tuple[Breadcrumb, ...]
    snippet: str


@dataclass(frozen=True)
class SearchResult:
    node: Node
    path: str
    matched: SearchMatch | None


@dataclass(frozen=True)
class SearchPage:
    items: tuple[SearchResult, ...]
    next_cursor: str | None
    degraded: bool
    degraded_reason: str | None


@dataclass(frozen=True)
class Download:
    mime: str
    filename: str
    etag: str
    size_bytes: int
    inline_content: bytes | None = None
    signed_url: str | None = None


@dataclass(frozen=True)
class ArchiveFrame:
    filename: str | None = None
    mime: str | None = None
    data: bytes | None = None


@dataclass(frozen=True)
class Storage:
    limit_bytes: int
    bucket_id: str
    filesystem_id: str
    root_id: str = ""


def _generation(value: Generation):
    return pb.ProcessingGeneration(file_id=value.file_id, generation=value.generation)


def _scope(value: OutputScope):
    return pb.OutputUploadScope(
        source=_generation(value.source), stage=value.stage, upload_id=value.upload_id
    )


def _transfer(value):
    return Transfer(
        value.url,
        dict(value.headers),
        value.content_length if hasattr(value, "content_length") else None,
        _datetime(value.expires_at) if hasattr(value, "expires_at") else None,
    )


def _upload(value):
    return Upload(
        value.id,
        value.status,
        value.part_size_bytes,
        value.part_count,
        _transfer(value.transfer) if value.HasField("transfer") else None,
    )


def _nodes(values):
    return tuple(
        InventoryNode(
            node.id,
            node.parent_id or None,
            node.path,
            node.name,
            node.kind,
            node.size_bytes,
            node.media_type,
            node.title,
            node.description,
            node.context,
            node.inline_content
            if node.WhichOneof("content") == "inline_content"
            else None,
            node.signed_url if node.WhichOneof("content") == "signed_url" else None,
        )
        for node in values
    )


def _locator(value: Locator):
    if (value.node_id is None) == (value.path is None):
        raise ValueError("locator requires exactly one target")
    result = (
        pb.Locator(node_id=value.node_id)
        if value.node_id is not None
        else pb.Locator(path=pb.PathLocator(path=value.path, cwd_id=value.cwd_id))
    )
    if value.expected_node_id is not None:
        result.expected_node_id = value.expected_node_id
    if value.expected_parent_id is not None:
        result.expected_parent_id = value.expected_parent_id
    return result


def _path_context(filesystem_id: str, value: PathContext | None):
    context = value or PathContext.root(filesystem_id)
    if not 1 <= len(context.mounts) <= 32:
        raise ValueError("path context requires 1 to 32 mounts")
    return pb.PathContext(
        mounts=[
            pb.Mount(path=mount.path, filesystem_id=mount.filesystem_id)
            for mount in context.mounts
        ]
    )


def _datetime(value):
    return value.ToDatetime(tzinfo=UTC)


def _set_timestamp(target, name: str, value: datetime | None):
    if value is not None:
        getattr(target, name).FromDatetime(value)


def _node(value, filesystem_id: str | None = None):
    if filesystem_id is not None and value.filesystem_id != filesystem_id:
        raise AppError(
            "invalid filesystem result",
            reason="FILESYSTEM_SCOPE_CONFLICT",
            kind="conflict",
            retryable=False,
        )
    return Node(
        value.id,
        value.parent_id or None,
        value.name,
        value.kind,
        value.revision,
        value.size_bytes,
        value.media_type if value.HasField("media_type") else None,
        value.filesystem_id,
        _datetime(value.created_at),
        _datetime(value.updated_at),
        value.title if value.HasField("title") else None,
        value.description if value.HasField("description") else None,
        value.semantic_type if value.HasField("semantic_type") else None,
        value.context if value.HasField("context") else None,
    )


def _bucket(value):
    return Bucket(value.id, value.limit_bytes, value.used_bytes, value.state)


def _copy(value):
    return Copy(
        value.id,
        value.destination_root_id,
        value.status,
        value.committed_nodes,
        value.committed_bytes,
        value.error_code if value.HasField("error_code") else None,
    )


def _trash(value):
    return TrashEntry(
        value.id,
        value.node_id,
        value.parent_id if value.HasField("parent_id") else None,
        value.name,
        value.actor_id,
        value.status,
        _datetime(value.created_at),
    )


def _publication(value):
    return UploadPublication(value.node_id, value.status, value.revision)


def _file_upload(value):
    result = value.WhichOneof("result")
    return FileUpload(
        value.id,
        value.status,
        value.transport,
        _datetime(value.expires_at),
        value.size_bytes if value.HasField("size_bytes") else None,
        value.part_size_bytes if value.HasField("part_size_bytes") else None,
        value.part_count if value.HasField("part_count") else None,
        _transfer(value.transfer) if value.HasField("transfer") else None,
        _publication(value.publication) if result == "publication" else None,
        UploadReceipt(value.receipt.id, value.receipt.status, value.receipt.size_bytes)
        if result == "receipt"
        else None,
    )


def _search_result(value, filesystem_id: str):
    matched = None
    if value.HasField("matched"):
        matched = SearchMatch(
            value.matched.file_id,
            tuple(
                Breadcrumb(item.node_id, item.filename)
                for item in value.matched.breadcrumb
            ),
            value.matched.snippet,
        )
    return SearchResult(_node(value.node, filesystem_id), value.path, matched)


def _search_page(value, filesystem_id: str):
    return SearchPage(
        tuple(_search_result(item, filesystem_id) for item in value.items),
        value.next_cursor if value.HasField("next_cursor") else None,
        value.degraded,
        value.degraded_reason if value.HasField("degraded_reason") else None,
    )


def _search_filters(value: SearchFilters | None):
    result = pb.SearchFilters()
    if value is None:
        return result
    if value.parent is not None:
        result.parent.CopyFrom(_locator(value.parent))
    if value.semantic_type is not None:
        result.semantic_type = value.semantic_type
    if value.media_type is not None:
        result.media_type = value.media_type
    for name in (
        "created_after",
        "created_before",
        "updated_after",
        "updated_before",
    ):
        _set_timestamp(result, name, getattr(value, name))
    return result


def _input(response):
    result = response.WhichOneof("result")
    if result == "complete":
        return None
    if result != "input":
        raise AppError("missing processing input", reason="DEPENDENCY_UNAVAILABLE")
    return response.input


class ProcessingClient:
    """Native processing client; protobuf and idempotent transport retry stay here."""

    def __init__(self, rpc: RpcClient):
        self._rpc = rpc
        self._stub = IngestServiceStub(rpc.channel)

    async def _call(self, method, request):
        return await self._rpc.invoke(method, request, retry_transient=True, timeout=30)

    async def prepare_parse(self, source: Generation) -> ParseInput | None:
        value = _input(
            await self._call(
                self._stub.PrepareParse,
                pb.PrepareParseRequest(
                    file_id=source.file_id, generation=source.generation
                ),
            )
        )
        if value is None:
            return None
        return ParseInput(
            value.format,
            value.size_bytes,
            value.inline_limit_bytes,
            value.multipart_threshold_bytes,
            value.max_outputs,
            value.max_output_bytes,
            value.inline_content
            if value.WhichOneof("source") == "inline_content"
            else None,
            value.signed_url if value.WhichOneof("source") == "signed_url" else None,
        )

    async def prepare_enrichment(self, source: Generation) -> EnrichmentInput | None:
        value = _input(
            await self._call(
                self._stub.PrepareEnrichment,
                pb.PrepareEnrichmentRequest(source=_generation(source)),
            )
        )
        return (
            None
            if value is None
            else EnrichmentInput(
                _nodes(value.nodes),
                value.inline_limit_bytes,
                value.multipart_threshold_bytes,
                value.max_output_bytes,
            )
        )

    async def prepare_index(self, source: Generation) -> IndexInput | None:
        value = _input(
            await self._call(
                self._stub.PrepareIndex,
                pb.PrepareIndexRequest(source=_generation(source)),
            )
        )
        if value is None:
            return None
        space = value.vector_space
        return IndexInput(
            value.filesystem_id,
            value.source_id,
            value.generation,
            _nodes(value.nodes),
            VectorSpace(space.model, space.collection, space.dimension)
            if value.HasField("vector_space")
            else None,
            value.max_output_bytes,
        )

    async def _prepare_output(self, method, request_type, source, output):
        description = pb.OutputDescription(
            path=output.path,
            storage=output.storage,
            size_bytes=output.size_bytes,
            content_md5=output.content_md5,
        )
        return _upload(
            (
                await self._call(
                    method, request_type(source=_generation(source), output=description)
                )
            ).upload
        )

    async def prepare_parse_output(
        self, source: Generation, output: OutputDescription
    ) -> Upload:
        return await self._prepare_output(
            self._stub.PrepareParseOutput,
            pb.PrepareParseOutputRequest,
            source,
            output,
        )

    async def prepare_enrichment_output(
        self, source: Generation, output: OutputDescription
    ) -> Upload:
        return await self._prepare_output(
            self._stub.PrepareEnrichmentOutput,
            pb.PrepareEnrichmentOutputRequest,
            source,
            output,
        )

    async def complete_parse(
        self, source: Generation, uploads: Sequence[str], directories: Sequence[str]
    ) -> None:
        await self._call(
            self._stub.CompleteParse,
            pb.CompleteParseRequest(
                source=_generation(source), uploads=uploads, directories=directories
            ),
        )

    async def abort_parse(self, source: Generation, error_code: str) -> None:
        await self._call(
            self._stub.AbortParse,
            pb.AbortParseRequest(source=_generation(source), error_code=error_code),
        )

    async def complete_enrichment(
        self, source: Generation, nodes: Sequence[EnrichmentUpdate]
    ) -> None:
        updates = []
        for node in nodes:
            metadata = node.metadata
            semantic = (
                None
                if metadata is None
                else pb.SemanticMetadata(
                    title=metadata.title,
                    description=metadata.description,
                    semantic_type=metadata.semantic_type,
                    context=metadata.context,
                )
            )
            updates.append(
                pb.EnrichmentUpdate(
                    id=node.id,
                    path=node.path,
                    metadata=semantic,
                    upload_id=node.upload_id,
                )
            )
        await self._call(
            self._stub.CompleteEnrichment,
            pb.CompleteEnrichmentRequest(source=_generation(source), nodes=updates),
        )

    async def fail_enrichment(self, source: Generation, error_code: str) -> None:
        await self._call(
            self._stub.FailEnrichment,
            pb.FailEnrichmentRequest(source=_generation(source), error_code=error_code),
        )

    async def complete_index(self, source: Generation) -> None:
        await self._call(
            self._stub.CompleteIndex,
            pb.CompleteIndexRequest(source=_generation(source)),
        )

    async def fail_index(self, source: Generation, error_code: str) -> None:
        await self._call(
            self._stub.FailIndex,
            pb.FailIndexRequest(source=_generation(source), error_code=error_code),
        )

    async def get_output_upload(self, scope: OutputScope) -> Upload:
        return _upload(
            (
                await self._call(
                    self._stub.GetOutputUpload,
                    pb.GetOutputUploadRequest(scope=_scope(scope)),
                )
            ).upload
        )

    async def get_output_upload_parts(
        self, scope: OutputScope, numbers: Sequence[int]
    ) -> tuple[UploadPart, ...]:
        response = await self._call(
            self._stub.GetOutputUploadParts,
            pb.GetOutputUploadPartsRequest(scope=_scope(scope), numbers=numbers),
        )
        return tuple(
            UploadPart(item.part_number, _transfer(item.transfer))
            for item in response.items
        )

    async def complete_output_upload(
        self, scope: OutputScope, parts: Sequence[PartReceipt] = ()
    ) -> UploadReceipt:
        response = await self._call(
            self._stub.CompleteOutputUpload,
            pb.CompleteOutputUploadRequest(
                scope=_scope(scope),
                parts=[
                    pb.PartReceipt(part_number=item.part_number, etag=item.etag)
                    for item in parts
                ],
            ),
        )
        return UploadReceipt(
            response.receipt.id, response.receipt.status, response.receipt.size_bytes
        )

    async def write_output_bytes(
        self, scope: OutputScope, content: bytes
    ) -> UploadReceipt:
        response = await self._call(
            self._stub.WriteOutputBytes,
            pb.WriteOutputBytesRequest(scope=_scope(scope), content=content),
        )
        return UploadReceipt(
            response.receipt.id, response.receipt.status, response.receipt.size_bytes
        )


class FilesystemClient:
    def __init__(self, rpc: RpcClient):
        self._rpc = rpc
        self._stub = FilesystemServiceStub(rpc.channel)

    async def get_filesystem(self, filesystem_id: str, *, actor_id=None) -> Filesystem:
        response = await self._rpc.invoke(
            self._stub.GetFilesystem,
            pb.GetFilesystemRequest(filesystem_id=filesystem_id),
            actor_id=actor_id,
        )
        value = response.filesystem
        if value.id != filesystem_id:
            raise AppError(
                "invalid filesystem result",
                reason="FILESYSTEM_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return Filesystem(value.id, value.bucket_id, value.root_id, value.state)

    async def get_bucket_usage(self, bucket_id: str, *, actor_id=None) -> BucketUsage:
        response = await self._rpc.invoke(
            self._stub.GetBucketUsage,
            pb.GetBucketUsageRequest(bucket_id=bucket_id),
            actor_id=actor_id,
        )
        limits = response.upload_limits
        if response.bucket.id != bucket_id:
            raise AppError(
                "invalid bucket result",
                reason="STORAGE_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return BucketUsage(
            _bucket(response.bucket),
            UploadLimits(
                limits.inline_limit_bytes,
                limits.max_file_bytes,
                limits.multipart_threshold_bytes,
                limits.multipart_part_bytes,
            ),
        )

    async def get_node(
        self,
        filesystem_id: str,
        node_id: str,
        *,
        actor_id=None,
        path_context: PathContext | None = None,
    ) -> Node:
        response = await self._rpc.invoke(
            self._stub.GetNode,
            pb.GetNodeRequest(
                filesystem_id=filesystem_id,
                node_id=node_id,
                path_context=_path_context(filesystem_id, path_context),
            ),
            actor_id=actor_id,
        )
        return _node(response.node, filesystem_id)

    async def resolve_node(
        self,
        filesystem_id: str,
        locator: Locator,
        *,
        actor_id=None,
        path_context: PathContext | None = None,
    ) -> Node:
        response = await self._rpc.invoke(
            self._stub.ResolveNode,
            pb.ResolveNodeRequest(
                filesystem_id=filesystem_id,
                locator=_locator(locator),
                path_context=_path_context(filesystem_id, path_context),
            ),
            actor_id=actor_id,
        )
        return _node(response.node, filesystem_id)

    async def batch_stat(
        self,
        filesystem_id: str,
        locators: Sequence[Locator],
        *,
        actor_id=None,
        path_context: PathContext | None = None,
    ) -> tuple[Node, ...]:
        if not locators or len(locators) > 100:
            raise ValueError("batch stat requires 1 to 100 locators")
        response = await self._rpc.invoke(
            self._stub.BatchStat,
            pb.BatchStatRequest(
                filesystem_id=filesystem_id,
                locators=[_locator(item) for item in locators],
                path_context=_path_context(filesystem_id, path_context),
            ),
            actor_id=actor_id,
        )
        return tuple(_node(item, filesystem_id) for item in response.items)

    async def create_directory(
        self,
        filesystem_id: str,
        parent: Locator,
        name: str,
        idempotency_key: str,
        *,
        actor_id=None,
        path_context: PathContext | None = None,
    ) -> Node:
        response = await self._rpc.invoke(
            self._stub.CreateNode,
            pb.CreateNodeRequest(
                filesystem_id=filesystem_id,
                idempotency_key=idempotency_key,
                path_context=_path_context(filesystem_id, path_context),
                directory=pb.DirectoryCreation(parent=_locator(parent), name=name),
            ),
            actor_id=actor_id,
        )
        return _node(response.node, filesystem_id)

    async def create_inline_file(
        self,
        filesystem_id: str,
        parent: Locator,
        name: str,
        content: bytes,
        media_type: str,
        idempotency_key: str,
        *,
        actor_id=None,
        path_context: PathContext | None = None,
    ) -> Node:
        response = await self._rpc.invoke(
            self._stub.CreateNode,
            pb.CreateNodeRequest(
                filesystem_id=filesystem_id,
                idempotency_key=idempotency_key,
                path_context=_path_context(filesystem_id, path_context),
                file=pb.InlineFileCreation(
                    parent=_locator(parent),
                    name=name,
                    content=content,
                    media_type=media_type,
                ),
            ),
            actor_id=actor_id,
        )
        return _node(response.node, filesystem_id)

    async def list_nodes(
        self,
        filesystem_id: str,
        parent_id: str,
        *,
        actor_id=None,
        path_context: PathContext | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> tuple[tuple[Node, ...], str | None]:
        request = pb.ListNodesRequest(
            filesystem_id=filesystem_id,
            parent=pb.Locator(node_id=parent_id),
            path_context=_path_context(filesystem_id, path_context),
        )
        if limit is not None:
            request.limit = limit
        if cursor is not None:
            request.cursor = cursor
        response = await self._rpc.invoke(
            self._stub.ListNodes, request, actor_id=actor_id
        )
        return tuple(
            _node(item, filesystem_id) for item in response.items
        ), response.next_cursor if response.HasField("next_cursor") else None

    async def update_node(
        self,
        filesystem_id: str,
        locator: Locator,
        *,
        actor_id=None,
        revision: int | None = None,
        name: str | None = None,
        parent: Locator | None = None,
        path_context: PathContext | None = None,
    ) -> Node:
        request = pb.UpdateNodeRequest(
            filesystem_id=filesystem_id,
            locator=_locator(locator),
            path_context=_path_context(filesystem_id, path_context),
        )
        if revision is not None:
            request.revision = revision
        if name is not None:
            request.name = name
        if parent is not None:
            request.parent.CopyFrom(_locator(parent))
        response = await self._rpc.invoke(
            self._stub.UpdateNode, request, actor_id=actor_id
        )
        return _node(response.node, filesystem_id)

    async def replace_content(
        self,
        filesystem_id: str,
        node_id: str,
        content: bytes,
        media_type: str,
        *,
        actor_id=None,
        revision: int | None = None,
        path_context: PathContext | None = None,
    ) -> Node:
        request = pb.ReplaceContentRequest(
            filesystem_id=filesystem_id,
            locator=pb.Locator(node_id=node_id),
            path_context=_path_context(filesystem_id, path_context),
            content=content,
            media_type=media_type,
        )
        if revision is not None:
            request.revision = revision
        response = await self._rpc.invoke(
            self._stub.ReplaceContent, request, actor_id=actor_id
        )
        return _node(response.node, filesystem_id)

    async def create_copy(
        self,
        filesystem_id: str,
        source_id: str,
        parent_id: str,
        name: str,
        idempotency_key: str,
        *,
        actor_id=None,
        revision: int | None = None,
        path_context: PathContext | None = None,
    ) -> Copy:
        request = pb.CreateCopyRequest(
            filesystem_id=filesystem_id,
            source_id=source_id,
            parent_id=parent_id,
            name=name,
            idempotency_key=idempotency_key,
            path_context=_path_context(filesystem_id, path_context),
        )
        if revision is not None:
            request.revision = revision
        response = await self._rpc.invoke(
            self._stub.CreateCopy, request, actor_id=actor_id
        )
        return _copy(response.copy)

    async def get_copy(
        self, filesystem_id: str, copy_id: str, *, actor_id=None
    ) -> Copy:
        response = await self._rpc.invoke(
            self._stub.GetCopy,
            pb.GetCopyRequest(filesystem_id=filesystem_id, copy_id=copy_id),
            actor_id=actor_id,
        )
        result = _copy(response.copy)
        if result.id != copy_id:
            raise AppError(
                "invalid filesystem result",
                reason="FILESYSTEM_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return result

    async def get_processing(
        self,
        filesystem_id: str,
        node_id: str,
        *,
        actor_id=None,
        path_context: PathContext | None = None,
    ) -> ProcessingStatus:
        response = await self._rpc.invoke(
            self._stub.GetProcessing,
            pb.GetProcessingRequest(
                filesystem_id=filesystem_id,
                node_id=node_id,
                path_context=_path_context(filesystem_id, path_context),
            ),
            actor_id=actor_id,
        )
        value = response.processing
        return ProcessingStatus(
            value.file_id,
            value.desired_generation,
            value.publication_status,
            value.error_code if value.HasField("error_code") else None,
        )

    async def reprocess_node(
        self,
        filesystem_id: str,
        node_id: str,
        idempotency_key: str,
        *,
        actor_id=None,
        path_context: PathContext | None = None,
    ) -> Reprocessing:
        response = await self._rpc.invoke(
            self._stub.ReprocessNode,
            pb.ReprocessNodeRequest(
                filesystem_id=filesystem_id,
                node_id=node_id,
                idempotency_key=idempotency_key,
                path_context=_path_context(filesystem_id, path_context),
            ),
            actor_id=actor_id,
        )
        return Reprocessing(response.file_id, response.generation, response.workflow_id)

    async def trash_node(
        self,
        filesystem_id: str,
        locator: Locator,
        *,
        actor_id=None,
        revision: int | None = None,
        path_context: PathContext | None = None,
    ) -> TrashEntry:
        request = pb.TrashNodeRequest(
            filesystem_id=filesystem_id,
            locator=_locator(locator),
            path_context=_path_context(filesystem_id, path_context),
        )
        if revision is not None:
            request.revision = revision
        response = await self._rpc.invoke(
            self._stub.TrashNode, request, actor_id=actor_id
        )
        return _trash(response.entry)

    async def list_trash(
        self,
        filesystem_id: str,
        *,
        actor_id=None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> tuple[tuple[TrashEntry, ...], str | None]:
        request = pb.ListTrashRequest(filesystem_id=filesystem_id)
        if limit is not None:
            request.limit = limit
        if cursor is not None:
            request.cursor = cursor
        response = await self._rpc.invoke(
            self._stub.ListTrash, request, actor_id=actor_id
        )
        return tuple(_trash(item) for item in response.items), (
            response.next_cursor if response.HasField("next_cursor") else None
        )

    async def get_trash(
        self, filesystem_id: str, entry_id: str, *, actor_id=None
    ) -> TrashEntry:
        response = await self._rpc.invoke(
            self._stub.GetTrash,
            pb.GetTrashRequest(filesystem_id=filesystem_id, entry_id=entry_id),
            actor_id=actor_id,
        )
        result = _trash(response.entry)
        if result.id != entry_id:
            raise AppError(
                "invalid filesystem result",
                reason="FILESYSTEM_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return result

    async def restore_trash(
        self, filesystem_id: str, entry_id: str, *, actor_id=None
    ) -> Node:
        response = await self._rpc.invoke(
            self._stub.RestoreTrash,
            pb.RestoreTrashRequest(filesystem_id=filesystem_id, entry_id=entry_id),
            actor_id=actor_id,
        )
        return _node(response.node, filesystem_id)

    async def purge_trash(
        self, filesystem_id: str, entry_id: str, *, actor_id=None
    ) -> TrashEntry | None:
        response = await self._rpc.invoke(
            self._stub.PurgeTrash,
            pb.PurgeTrashRequest(filesystem_id=filesystem_id, entry_id=entry_id),
            actor_id=actor_id,
        )
        return _trash(response.entry) if response.HasField("entry") else None

    async def create_upload(
        self,
        filesystem_id: str,
        idempotency_key: str,
        media_type: str,
        *,
        destination: UploadDestination | None = None,
        replacement: UploadReplacement | None = None,
        size_bytes: int | None = None,
        content_md5: str | None = None,
        actor_id=None,
        path_context: PathContext | None = None,
    ) -> FileUpload:
        if (destination is None) == (replacement is None):
            raise ValueError("upload requires exactly one target")
        request = pb.CreateUploadRequest(
            filesystem_id=filesystem_id,
            idempotency_key=idempotency_key,
            media_type=media_type,
            path_context=_path_context(filesystem_id, path_context),
        )
        if size_bytes is not None:
            request.size_bytes = size_bytes
        if content_md5 is not None:
            request.content_md5 = content_md5
        if destination is not None:
            request.destination.CopyFrom(
                pb.UploadDestination(
                    parent=_locator(destination.parent), name=destination.name
                )
            )
        else:
            request.replacement.locator.CopyFrom(_locator(replacement.locator))
            if replacement.revision is not None:
                request.replacement.revision = replacement.revision
        response = await self._rpc.invoke(
            self._stub.CreateUpload, request, actor_id=actor_id
        )
        return _file_upload(response.upload)

    async def get_upload(
        self, filesystem_id: str, upload_id: str, *, actor_id=None
    ) -> FileUpload:
        response = await self._rpc.invoke(
            self._stub.GetUpload,
            pb.GetUploadRequest(filesystem_id=filesystem_id, upload_id=upload_id),
            actor_id=actor_id,
        )
        result = _file_upload(response.upload)
        if result.id != upload_id:
            raise AppError(
                "invalid filesystem result",
                reason="FILESYSTEM_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return result

    async def get_upload_parts(
        self,
        filesystem_id: str,
        upload_id: str,
        numbers: Sequence[int],
        *,
        actor_id=None,
    ) -> tuple[UploadPart, ...]:
        response = await self._rpc.invoke(
            self._stub.GetUploadParts,
            pb.GetUploadPartsRequest(
                filesystem_id=filesystem_id,
                upload_id=upload_id,
                numbers=numbers,
            ),
            actor_id=actor_id,
        )
        return tuple(
            UploadPart(item.part_number, _transfer(item.transfer))
            for item in response.items
        )

    async def complete_upload(
        self,
        filesystem_id: str,
        upload_id: str,
        parts: Sequence[PartReceipt] = (),
        *,
        actor_id=None,
    ) -> UploadPublication:
        response = await self._rpc.invoke(
            self._stub.CompleteUpload,
            pb.CompleteUploadRequest(
                filesystem_id=filesystem_id,
                upload_id=upload_id,
                parts=[
                    pb.PartReceipt(part_number=item.part_number, etag=item.etag)
                    for item in parts
                ],
            ),
            actor_id=actor_id,
        )
        return _publication(response.publication)

    async def abort_upload(
        self, filesystem_id: str, upload_id: str, *, actor_id=None
    ) -> None:
        await self._rpc.invoke(
            self._stub.AbortUpload,
            pb.AbortUploadRequest(filesystem_id=filesystem_id, upload_id=upload_id),
            actor_id=actor_id,
        )

    async def _search(
        self,
        method,
        request_type,
        filesystem_id: str,
        query: str,
        *,
        actor_id=None,
        filters: SearchFilters | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
        path_context: PathContext | None = None,
    ) -> SearchPage:
        request = request_type(
            filesystem_id=filesystem_id,
            query=query,
            filters=_search_filters(filters),
            path_context=_path_context(filesystem_id, path_context),
        )
        for name, value in (
            ("limit", limit),
            ("cursor", cursor),
            ("sort", sort),
            ("direction", direction),
        ):
            if value is not None and hasattr(request, name):
                setattr(request, name, value)
        return _search_page(
            await self._rpc.invoke(method, request, actor_id=actor_id), filesystem_id
        )

    async def search_files(
        self,
        filesystem_id: str,
        query: str,
        *,
        actor_id=None,
        filters: SearchFilters | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
        path_context: PathContext | None = None,
    ) -> SearchPage:
        return await self._search(
            self._stub.SearchFiles,
            pb.SearchFilesRequest,
            filesystem_id,
            query,
            actor_id=actor_id,
            filters=filters,
            limit=limit,
            cursor=cursor,
            sort=sort,
            direction=direction,
            path_context=path_context,
        )

    async def semantic_search(
        self,
        filesystem_id: str,
        query: str,
        *,
        actor_id=None,
        filters: SearchFilters | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        path_context: PathContext | None = None,
    ) -> SearchPage:
        return await self._search(
            self._stub.SemanticSearch,
            pb.SemanticSearchRequest,
            filesystem_id,
            query,
            actor_id=actor_id,
            filters=filters,
            limit=limit,
            cursor=cursor,
            path_context=path_context,
        )

    async def get_download(
        self,
        filesystem_id: str,
        node_id: str,
        *,
        actor_id=None,
        revision: int | None = None,
        path_context: PathContext | None = None,
    ) -> Download:
        request = pb.GetDownloadRequest(
            filesystem_id=filesystem_id,
            node_id=node_id,
            path_context=_path_context(filesystem_id, path_context),
        )
        if revision is not None:
            request.revision = revision
        value = (
            await self._rpc.invoke(self._stub.GetDownload, request, actor_id=actor_id)
        ).download
        return Download(
            value.mime,
            value.filename,
            value.etag,
            value.size_bytes,
            value.inline_content
            if value.WhichOneof("source") == "inline_content"
            else None,
            value.signed_url if value.WhichOneof("source") == "signed_url" else None,
        )

    async def stream_archive(
        self,
        filesystem_id: str,
        node_id: str,
        *,
        actor_id=None,
        path_context: PathContext | None = None,
    ) -> AsyncIterator[ArchiveFrame]:
        request = pb.StreamArchiveRequest(
            filesystem_id=filesystem_id,
            node_id=node_id,
            path_context=_path_context(filesystem_id, path_context),
        )
        async with aclosing(
            self._rpc.invoke_stream(
                self._stub.StreamArchive, request, actor_id=actor_id
            )
        ) as stream:
            async for value in stream:
                frame = value.WhichOneof("frame")
                yield (
                    ArchiveFrame(value.metadata.filename, value.metadata.mime)
                    if frame == "metadata"
                    else ArchiveFrame(data=value.data)
                )


class StorageAdministrationClient:
    def __init__(self, rpc: RpcClient):
        self._rpc = rpc
        self._stub = StorageAdministrationServiceStub(rpc.channel)

    async def create_storage(self, value: Storage) -> Storage:
        response = await self._rpc.invoke(
            self._stub.CreateStorage,
            pb.CreateStorageRequest(
                bucket=pb.CreateBucketRequest(
                    bucket_id=value.bucket_id,
                    idempotency_key=value.bucket_id,
                    limit_bytes=value.limit_bytes,
                ),
                filesystem=pb.CreateFilesystemRequest(
                    filesystem_id=value.filesystem_id,
                    bucket_id=value.bucket_id,
                    idempotency_key=value.filesystem_id,
                    root_name="drive",
                ),
            ),
            timeout=10,
        )
        bucket, filesystem = response.bucket, response.filesystem
        if (
            bucket.id != value.bucket_id
            or bucket.limit_bytes != value.limit_bytes
            or bucket.state != "active"
            or filesystem.id != value.filesystem_id
            or filesystem.bucket_id != value.bucket_id
            or filesystem.state != "active"
            or not filesystem.root_id
        ):
            raise AppError(
                "invalid storage result",
                reason="STORAGE_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return Storage(
            value.limit_bytes, value.bucket_id, value.filesystem_id, filesystem.root_id
        )

    async def create_bucket(
        self, bucket_id: str, limit_bytes: int, idempotency_key: str
    ) -> Bucket:
        response = await self._rpc.invoke(
            self._stub.CreateBucket,
            pb.CreateBucketRequest(
                bucket_id=bucket_id,
                limit_bytes=limit_bytes,
                idempotency_key=idempotency_key,
            ),
            timeout=10,
        )
        result = _bucket(response.bucket)
        if result.id != bucket_id or result.limit_bytes != limit_bytes:
            raise AppError(
                "invalid storage result",
                reason="STORAGE_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return result

    async def create_filesystem(
        self,
        filesystem_id: str,
        bucket_id: str,
        idempotency_key: str,
        root_name: str,
    ) -> Filesystem:
        value = (
            await self._rpc.invoke(
                self._stub.CreateFilesystem,
                pb.CreateFilesystemRequest(
                    filesystem_id=filesystem_id,
                    bucket_id=bucket_id,
                    idempotency_key=idempotency_key,
                    root_name=root_name,
                ),
                timeout=10,
            )
        ).filesystem
        if value.id != filesystem_id or value.bucket_id != bucket_id:
            raise AppError(
                "invalid storage result",
                reason="STORAGE_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return Filesystem(value.id, value.bucket_id, value.root_id, value.state)

    async def release_provisioning(self, value: Storage) -> None:
        await self._rpc.invoke(
            self._stub.ReleaseProvisioning,
            pb.ReleaseProvisioningRequest(
                bucket_id=value.bucket_id,
                filesystem_id=value.filesystem_id,
                root_id=value.root_id,
            ),
            timeout=10,
        )

    async def freeze_bucket(self, bucket_id: str, idempotency_key: str) -> Bucket:
        result = _bucket(
            (
                await self._rpc.invoke(
                    self._stub.FreezeBucket,
                    pb.FreezeBucketRequest(
                        bucket_id=bucket_id, idempotency_key=idempotency_key
                    ),
                    timeout=10,
                )
            ).bucket
        )
        if result.id != bucket_id or result.state not in {"frozen", "deleted"}:
            raise AppError(
                "invalid storage result",
                reason="STORAGE_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return result

    async def list_filesystems(
        self, bucket_id: str, after_id: str | None = None
    ) -> tuple[str, ...]:
        request = pb.ListBucketFilesystemsRequest(bucket_id=bucket_id)
        if after_id is not None:
            request.after_id = after_id
        response = await self._rpc.invoke(
            self._stub.ListBucketFilesystems, request, timeout=10
        )
        result = tuple(response.filesystem_ids)
        if (
            len(result) > 100
            or list(result) != sorted(result)
            or len(set(result)) != len(result)
            or (after_id is not None and any(item <= after_id for item in result))
        ):
            raise AppError(
                "invalid storage result",
                reason="STORAGE_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return result

    async def delete_filesystem(self, filesystem_id: str) -> bool:
        response = await self._rpc.invoke(
            self._stub.DeleteFilesystem,
            pb.DeleteFilesystemRequest(filesystem_id=filesystem_id),
            timeout=10,
        )
        return response.completed

    async def complete_bucket_deletion(
        self, bucket_id: str, idempotency_key: str
    ) -> Bucket:
        result = _bucket(
            (
                await self._rpc.invoke(
                    self._stub.CompleteBucketDeletion,
                    pb.CompleteBucketDeletionRequest(
                        bucket_id=bucket_id, idempotency_key=idempotency_key
                    ),
                    timeout=10,
                )
            ).bucket
        )
        if result.id != bucket_id or result.state != "deleted":
            raise AppError(
                "invalid storage result",
                reason="STORAGE_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return result
