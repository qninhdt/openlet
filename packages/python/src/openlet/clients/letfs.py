import posixpath
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import aclosing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from openlet.errors import AppError
from openlet.rpc import Actor, RpcClient
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
    scope_id: str
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
    scope_id: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    title: str | None = None
    description: str | None = None
    semantic_type: str | None = None
    context: str | None = None
    readonly: bool = False


@dataclass(frozen=True)
class Filesystem:
    id: str
    limit_bytes: int
    used_bytes: int
    node_count: int
    state: str


@dataclass(frozen=True)
class Scope:
    id: str
    filesystem_id: str
    root_id: str
    state: str
    allow_blob_files: bool
    allow_indexing: bool


@dataclass(frozen=True)
class ScopePage:
    items: tuple[Scope, ...]
    next_cursor: str | None = None


@dataclass(frozen=True)
class Locator:
    node_id: str | None = None
    path: str | None = None
    cwd_id: str | None = None
    expected_node_id: str | None = None
    expected_parent_id: str | None = None
    root_id: str | None = None


@dataclass(frozen=True)
class ScopedLocator:
    scope_id: str
    locator: Locator


@dataclass(frozen=True)
class FileStat:
    node: Node
    storage_kind: str
    representation_kind: str
    readable_size: int
    fingerprint: str
    newline_count: int | None
    sha256: str | None


@dataclass(frozen=True)
class ExistingText:
    locator: Locator
    revision: int
    expected_fingerprint: str | None = None


@dataclass(frozen=True)
class TextCreation:
    parent: Locator
    name: str
    idempotency_key: str
    media_type: str = "text/plain"
    node_id: str | None = None


TextTarget = ExistingText | TextCreation


@dataclass(frozen=True)
class TextMutationResult:
    stat: FileStat
    before_revision: int
    before_fingerprint: str


@dataclass(frozen=True)
class TextSelection:
    kind: Literal["whole", "bytes", "lines", "head", "tail"] = "whole"
    offset: int = 0
    length: int | None = None
    start_line: int = 1
    line_count: int = 0


@dataclass(frozen=True)
class TextRead:
    stat: FileStat
    content: bytes
    offset: int
    length: int


@dataclass(frozen=True)
class TextMetric:
    stat: FileStat
    algorithm: str
    digest: str
    supported: bool


@dataclass(frozen=True)
class TreeEntry:
    path: str
    stat: FileStat


@dataclass(frozen=True)
class TreePage:
    items: tuple[TreeEntry, ...]
    next_cursor: str | None
    complete: bool


@dataclass(frozen=True)
class TextSearchResult:
    complete: bool
    items: tuple[TreeEntry, ...] = ()
    content: bytes = b""
    stat: FileStat | None = None


@dataclass(frozen=True)
class ImageRead:
    stat: FileStat
    content: bytes
    mime: str
    width: int
    height: int
    sha256: str


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
    actor_kind: str
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
class SemanticSearchResults:
    items: tuple[SearchResult, ...]
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
    if value.root_id is not None:
        result.root_id = value.root_id
    return result


def _datetime(value):
    return value.ToDatetime(tzinfo=UTC)


def _set_timestamp(target, name: str, value: datetime | None):
    if value is not None:
        getattr(target, name).FromDatetime(value)


def _node(value, scope_id: str | None = None):
    if scope_id is not None and value.scope_id != scope_id:
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
        value.scope_id,
        _datetime(value.created_at),
        _datetime(value.updated_at),
        value.title if value.HasField("title") else None,
        value.description if value.HasField("description") else None,
        value.semantic_type if value.HasField("semantic_type") else None,
        value.context if value.HasField("context") else None,
        value.readonly,
    )


def _invalid_result():
    return AppError(
        "invalid filesystem result",
        reason="FILESYSTEM_SCOPE_CONFLICT",
        kind="conflict",
        retryable=False,
    )


def _file_stat(value, scope_id: str, locator: Locator | None = None):
    node = _node(value.node, scope_id)
    if (
        not node.id
        or value.readable_size < 0
        or not value.fingerprint
        or value.representation_kind not in {"directory", "text", "blob_metadata"}
        or node.kind
        != ("directory" if value.representation_kind == "directory" else "file")
        or locator is not None
        and (
            locator.node_id is not None
            and node.id != locator.node_id
            or locator.expected_node_id is not None
            and node.id != locator.expected_node_id
        )
    ):
        raise _invalid_result()
    return FileStat(
        node,
        value.storage_kind,
        value.representation_kind,
        value.readable_size,
        value.fingerprint,
        value.newline_count if value.HasField("newline_count") else None,
        value.sha256 if value.HasField("sha256") else None,
    )


def _text_target(value: TextTarget) -> pb.TextTarget:
    if isinstance(value, TextCreation):
        return pb.TextTarget(
            create=pb.TextCreation(
                parent=_locator(value.parent),
                name=value.name,
                media_type=value.media_type,
                idempotency_key=value.idempotency_key,
                node_id=value.node_id,
            )
        )
    return pb.TextTarget(
        existing=pb.ExistingText(
            locator=_locator(value.locator),
            revision=value.revision,
            expected_fingerprint=value.expected_fingerprint,
        )
    )


def _text_mutation(
    value: pb.TextMutation, scope_id: str, target: TextTarget
) -> TextMutationResult:
    stat = _file_stat(
        value.stat,
        scope_id,
        target.locator if isinstance(target, ExistingText) else None,
    )
    if (
        stat.storage_kind != "text"
        or stat.representation_kind != "text"
        or stat.newline_count is None
        or stat.sha256 is None
    ):
        raise _invalid_result()
    if isinstance(target, TextCreation):
        if (
            value.before_revision != 0
            or value.before_fingerprint
            or target.node_id is not None
            and stat.node.id != target.node_id
        ):
            raise _invalid_result()
    elif (
        value.before_revision != target.revision
        or not value.before_fingerprint
        or stat.node.revision < target.revision
        or target.expected_fingerprint is not None
        and value.before_fingerprint != target.expected_fingerprint
    ):
        raise _invalid_result()
    return TextMutationResult(stat, value.before_revision, value.before_fingerprint)


def _trash(value):
    if value.actor_kind not in {"user", "leta"}:
        raise ValueError("invalid trash actor")
    return TrashEntry(
        value.id,
        value.node_id,
        value.parent_id if value.HasField("parent_id") else None,
        value.name,
        value.actor_id,
        value.actor_kind,
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
            value.scope_id,
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

    async def get_filesystem(
        self, filesystem_id: str, *, actor: Actor | None = None
    ) -> Filesystem:
        response = await self._rpc.invoke(
            self._stub.GetFilesystem,
            pb.GetFilesystemRequest(filesystem_id=filesystem_id),
            actor=actor,
        )
        value = response.filesystem
        if value.id != filesystem_id:
            raise AppError(
                "invalid filesystem result",
                reason="FILESYSTEM_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return Filesystem(
            value.id,
            value.limit_bytes,
            value.used_bytes,
            value.node_count,
            value.state,
        )

    async def get_node(
        self,
        filesystem_id: str,
        scope_id: str,
        node_id: str,
        *,
        actor: Actor | None = None,
    ) -> Node:
        response = await self._rpc.invoke(
            self._stub.GetNode,
            pb.GetNodeRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                node_id=node_id,
            ),
            actor=actor,
        )
        return _node(response.node, scope_id)

    async def resolve_node(
        self,
        filesystem_id: str,
        scope_id: str,
        locator: Locator,
        *,
        actor: Actor | None = None,
    ) -> Node:
        response = await self._rpc.invoke(
            self._stub.ResolveNode,
            pb.ResolveNodeRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                locator=_locator(locator),
            ),
            actor=actor,
        )
        return _node(response.node, scope_id)

    async def stat(
        self,
        filesystem_id: str,
        scope_id: str,
        locator: Locator,
        *,
        content_check: bool = False,
        actor: Actor | None = None,
    ) -> FileStat:
        response = await self._rpc.invoke(
            self._stub.Stat,
            pb.StatRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                locator=_locator(locator),
                content_check=content_check,
            ),
            actor=actor,
        )
        return _file_stat(response.stat, scope_id, locator)

    async def read_text(
        self,
        filesystem_id: str,
        scope_id: str,
        locator: Locator,
        selection: TextSelection = TextSelection(),
        *,
        expected_fingerprint: str | None = None,
        actor: Actor | None = None,
    ) -> TextRead:
        request = pb.ReadTextRequest(
            filesystem_id=filesystem_id,
            scope_id=scope_id,
            locator=_locator(locator),
            expected_fingerprint=expected_fingerprint,
        )
        match selection.kind:
            case "whole":
                request.whole.SetInParent()
            case "bytes":
                request.bytes.CopyFrom(
                    pb.ByteRange(offset=selection.offset, length=selection.length)
                )
            case "lines":
                request.lines.CopyFrom(
                    pb.LineRange(
                        start_line=selection.start_line, line_count=selection.line_count
                    )
                )
            case "head" | "tail":
                getattr(request, selection.kind).CopyFrom(
                    pb.LineCount(line_count=selection.line_count)
                )
            case _:
                raise ValueError("invalid text selection")
        response = await self._rpc.invoke(self._stub.ReadText, request, actor=actor)
        stat = _file_stat(response.stat, scope_id, locator)
        if (
            not 0 <= response.offset <= stat.readable_size
            or response.length != len(response.content)
            or response.length > stat.readable_size - response.offset
            or expected_fingerprint is not None
            and stat.fingerprint != expected_fingerprint
        ):
            raise _invalid_result()
        return TextRead(stat, response.content, response.offset, response.length)

    async def text_metrics(
        self,
        filesystem_id: str,
        scope_id: str,
        locator: Locator,
        algorithm: str,
        *,
        actor: Actor | None = None,
    ) -> TextMetric:
        response = await self._rpc.invoke(
            self._stub.TextMetrics,
            pb.TextMetricsRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                locator=_locator(locator),
                algorithm=algorithm,
            ),
            actor=actor,
        )
        return TextMetric(
            _file_stat(response.stat, scope_id, locator),
            response.algorithm,
            response.digest,
            response.supported,
        )

    async def read_tree(
        self,
        filesystem_id: str,
        scope_id: str,
        root: Locator,
        *,
        depth: int | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        max_bytes: int | None = None,
        actor: Actor | None = None,
    ) -> TreePage:
        response = await self._rpc.invoke(
            self._stub.ReadTree,
            pb.ReadTreeRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                root=_locator(root),
                depth=depth,
                cursor=cursor,
                limit=limit,
                max_bytes=max_bytes,
            ),
            actor=actor,
        )
        cursor = response.next_cursor if response.HasField("next_cursor") else None
        if response.complete != (cursor is None):
            raise _invalid_result()
        return TreePage(
            tuple(
                TreeEntry(item.path, _file_stat(item.stat, scope_id))
                for item in response.items
            ),
            cursor,
            response.complete,
        )

    async def text_search(
        self,
        filesystem_id: str,
        scope_id: str,
        locator: Locator,
        text: str,
        *,
        mode: Literal["files", "lines"] = "files",
        ignore_case: bool = False,
        max_files: int | None = None,
        max_lines: int | None = None,
        max_bytes: int | None = None,
        actor: Actor | None = None,
    ) -> TextSearchResult:
        if mode not in {"files", "lines"}:
            raise ValueError("invalid text search mode")
        response = await self._rpc.invoke(
            self._stub.TextSearch,
            pb.TextSearchRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                locator=_locator(locator),
                mode=mode,
                text=text,
                ignore_case=ignore_case,
                max_files=max_files,
                max_lines=max_lines,
                max_bytes=max_bytes,
            ),
            actor=actor,
        )
        if not response.complete:
            if response.items or response.content or response.HasField("stat"):
                raise _invalid_result()
            return TextSearchResult(False)
        if mode == "lines":
            stat = _file_stat(response.stat, scope_id, locator)
            if (
                response.items
                or stat.node.kind != "file"
                or len(response.content) > stat.readable_size
            ):
                raise _invalid_result()
            return TextSearchResult(True, content=response.content, stat=stat)
        if (
            response.HasField("stat")
            or response.content
            or max_files is not None
            and len(response.items) > max_files
        ):
            raise _invalid_result()
        items = []
        seen = set()
        last = ""
        for item in response.items:
            stat = _file_stat(item.stat, scope_id)
            path = item.path
            if (
                not path
                or path in {".", ".."}
                or path.startswith(("/", "../"))
                or posixpath.normpath(path) != path
                or stat.node.kind != "file"
                or stat.node.id in seen
                or path <= last
            ):
                raise _invalid_result()
            seen.add(stat.node.id)
            last = path
            items.append(TreeEntry(path, stat))
        return TextSearchResult(True, tuple(items))

    async def read_image(
        self,
        filesystem_id: str,
        scope_id: str,
        locator: Locator,
        *,
        expected_fingerprint: str | None = None,
        actor: Actor | None = None,
    ) -> ImageRead:
        response = await self._rpc.invoke(
            self._stub.ReadImage,
            pb.ReadImageRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                locator=_locator(locator),
                expected_fingerprint=expected_fingerprint,
            ),
            actor=actor,
        )
        stat = _file_stat(response.stat, scope_id, locator)
        if (
            response.mime != "image/png"
            or not 1 <= response.width <= 2048
            or not 1 <= response.height <= 2048
            or not response.content
            or not response.sha256
            or expected_fingerprint is not None
            and stat.fingerprint != expected_fingerprint
        ):
            raise _invalid_result()
        return ImageRead(
            stat,
            response.content,
            response.mime,
            response.width,
            response.height,
            response.sha256,
        )

    async def batch_stat(
        self,
        filesystem_id: str,
        locators: Sequence[ScopedLocator],
        *,
        actor: Actor | None = None,
    ) -> tuple[Node, ...]:
        if not locators or len(locators) > 100:
            raise ValueError("batch stat requires 1 to 100 locators")
        response = await self._rpc.invoke(
            self._stub.BatchStat,
            pb.BatchStatRequest(
                filesystem_id=filesystem_id,
                locators=[
                    pb.ScopedLocator(
                        scope_id=item.scope_id, locator=_locator(item.locator)
                    )
                    for item in locators
                ],
            ),
            actor=actor,
        )
        if len(response.items) != len(locators):
            raise AppError(
                "invalid filesystem result",
                reason="FILESYSTEM_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return tuple(
            _node(item, locator.scope_id)
            for item, locator in zip(response.items, locators, strict=True)
        )

    async def write_text(
        self,
        filesystem_id: str,
        scope_id: str,
        target: TextTarget,
        content: bytes,
        *,
        actor: Actor | None = None,
    ) -> TextMutationResult:
        response = await self._rpc.invoke(
            self._stub.WriteText,
            pb.WriteTextRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                target=_text_target(target),
                content=content,
            ),
            actor=actor,
        )
        return _text_mutation(response.result, scope_id, target)

    async def append_text(
        self,
        filesystem_id: str,
        scope_id: str,
        target: TextTarget,
        content: bytes,
        *,
        actor: Actor | None = None,
    ) -> TextMutationResult:
        response = await self._rpc.invoke(
            self._stub.AppendText,
            pb.AppendTextRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                target=_text_target(target),
                content=content,
            ),
            actor=actor,
        )
        return _text_mutation(response.result, scope_id, target)

    async def patch_text(
        self,
        filesystem_id: str,
        scope_id: str,
        target: TextTarget,
        content: bytes,
        *,
        offset: int | None = None,
        old_text: str | None = None,
        replace_all: bool = False,
        actor: Actor | None = None,
    ) -> TextMutationResult:
        if (offset is None) == (old_text is None) or offset is not None and replace_all:
            raise ValueError("exactly one patch kind required")
        request = pb.PatchTextRequest(
            filesystem_id=filesystem_id, scope_id=scope_id, target=_text_target(target)
        )
        if offset is not None:
            request.bytes.CopyFrom(pb.ByteOverwrite(offset=offset, content=content))
        else:
            request.literal.CopyFrom(
                pb.LiteralReplacement(
                    old_text=old_text,
                    new_text=content.decode("utf-8"),
                    replace_all=replace_all,
                )
            )
        response = await self._rpc.invoke(self._stub.PatchText, request, actor=actor)
        return _text_mutation(response.result, scope_id, target)

    async def truncate_text(
        self,
        filesystem_id: str,
        scope_id: str,
        target: TextTarget,
        length: int,
        *,
        no_create: bool = False,
        actor: Actor | None = None,
    ) -> TextMutationResult:
        response = await self._rpc.invoke(
            self._stub.TruncateText,
            pb.TruncateTextRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                target=_text_target(target),
                length=length,
                no_create=no_create,
            ),
            actor=actor,
        )
        return _text_mutation(response.result, scope_id, target)

    async def create_directories(
        self,
        filesystem_id: str,
        scope_id: str,
        parent: Locator,
        components: list[str],
        *,
        parents: bool = False,
        actor: Actor | None = None,
    ) -> Node:
        response = await self._rpc.invoke(
            self._stub.CreateDirectories,
            pb.CreateDirectoriesRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                parent=_locator(parent),
                components=components,
                parents=parents,
            ),
            actor=actor,
        )
        node = _node(response.node, scope_id)
        if node.kind != "directory":
            raise _invalid_result()
        return node

    async def create_directory(
        self,
        filesystem_id: str,
        scope_id: str,
        parent: Locator,
        name: str,
        idempotency_key: str,
        *,
        node_id: str | None = None,
        actor: Actor | None = None,
    ) -> Node:
        response = await self._rpc.invoke(
            self._stub.CreateNode,
            pb.CreateNodeRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                idempotency_key=idempotency_key,
                node_id=node_id,
                directory=pb.DirectoryCreation(parent=_locator(parent), name=name),
            ),
            actor=actor,
        )
        node = _node(response.node, scope_id)
        if node_id is not None and node.id != node_id:
            raise _invalid_result()
        return node

    async def create_inline_file(
        self,
        filesystem_id: str,
        scope_id: str,
        parent: Locator,
        name: str,
        content: bytes,
        media_type: str,
        idempotency_key: str,
        *,
        node_id: str | None = None,
        actor: Actor | None = None,
    ) -> Node:
        response = await self._rpc.invoke(
            self._stub.CreateNode,
            pb.CreateNodeRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                idempotency_key=idempotency_key,
                node_id=node_id,
                file=pb.InlineFileCreation(
                    parent=_locator(parent),
                    name=name,
                    content=content,
                    media_type=media_type,
                ),
            ),
            actor=actor,
        )
        node = _node(response.node, scope_id)
        if node_id is not None and node.id != node_id:
            raise _invalid_result()
        return node

    async def list_nodes(
        self,
        filesystem_id: str,
        scope_id: str,
        parent_id: str | Locator,
        *,
        actor: Actor | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> tuple[tuple[Node, ...], str | None]:
        request = pb.ListNodesRequest(
            filesystem_id=filesystem_id,
            scope_id=scope_id,
            parent=_locator(
                parent_id
                if isinstance(parent_id, Locator)
                else Locator(node_id=parent_id)
            ),
        )
        if limit is not None:
            request.limit = limit
        if cursor is not None:
            request.cursor = cursor
        response = await self._rpc.invoke(self._stub.ListNodes, request, actor=actor)
        return tuple(
            _node(item, scope_id) for item in response.items
        ), response.next_cursor if response.HasField("next_cursor") else None

    async def update_node(
        self,
        filesystem_id: str,
        scope_id: str,
        locator: Locator,
        *,
        actor: Actor | None = None,
        revision: int | None = None,
        name: str | None = None,
        parent: Locator | None = None,
        destination_scope_id: str | None = None,
    ) -> Node:
        request = pb.UpdateNodeRequest(
            filesystem_id=filesystem_id,
            scope_id=scope_id,
            locator=_locator(locator),
        )
        if destination_scope_id is not None:
            request.destination_scope_id = destination_scope_id
        if revision is not None:
            request.revision = revision
        if name is not None:
            request.name = name
        if parent is not None:
            request.parent.CopyFrom(_locator(parent))
        response = await self._rpc.invoke(self._stub.UpdateNode, request, actor=actor)
        return _node(response.node, destination_scope_id or scope_id)

    async def replace_content(
        self,
        filesystem_id: str,
        scope_id: str,
        node_id: str,
        content: bytes,
        media_type: str,
        *,
        actor: Actor | None = None,
        revision: int | None = None,
    ) -> Node:
        request = pb.ReplaceContentRequest(
            filesystem_id=filesystem_id,
            scope_id=scope_id,
            locator=pb.Locator(node_id=node_id),
            content=content,
            media_type=media_type,
        )
        if revision is not None:
            request.revision = revision
        response = await self._rpc.invoke(
            self._stub.ReplaceContent, request, actor=actor
        )
        return _node(response.node, scope_id)

    async def create_copy(
        self,
        filesystem_id: str,
        scope_id: str,
        source_id: str,
        parent_id: str,
        idempotency_key: str,
        *,
        destination_scope_id: str | None = None,
        source_root_id: str | None = None,
        destination_root_id: str | None = None,
        name: str = "",
        actor: Actor | None = None,
        revision: int | None = None,
    ) -> Node:
        request = pb.CreateCopyRequest(
            filesystem_id=filesystem_id,
            scope_id=scope_id,
            source_id=source_id,
            destination_scope_id=destination_scope_id or scope_id,
            source_root_id=source_root_id,
            destination_root_id=destination_root_id,
            parent_id=parent_id,
            name=name,
            idempotency_key=idempotency_key,
        )
        if revision is not None:
            request.revision = revision
        response = await self._rpc.invoke(
            self._stub.CreateCopy, request, actor=actor, timeout=120
        )
        return _node(response.node, destination_scope_id or scope_id)

    async def get_processing(
        self,
        filesystem_id: str,
        scope_id: str,
        node_id: str,
        *,
        actor: Actor | None = None,
    ) -> ProcessingStatus:
        response = await self._rpc.invoke(
            self._stub.GetProcessing,
            pb.GetProcessingRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                node_id=node_id,
            ),
            actor=actor,
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
        scope_id: str,
        node_id: str,
        idempotency_key: str,
        *,
        actor: Actor | None = None,
    ) -> Reprocessing:
        response = await self._rpc.invoke(
            self._stub.ReprocessNode,
            pb.ReprocessNodeRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                node_id=node_id,
                idempotency_key=idempotency_key,
            ),
            actor=actor,
        )
        return Reprocessing(response.file_id, response.generation, response.workflow_id)

    async def trash_node(
        self,
        filesystem_id: str,
        scope_id: str,
        locator: Locator,
        *,
        actor: Actor | None = None,
        revision: int | None = None,
        empty_directory: bool = False,
    ) -> TrashEntry:
        request = pb.TrashNodeRequest(
            filesystem_id=filesystem_id,
            scope_id=scope_id,
            locator=_locator(locator),
            empty_directory=empty_directory,
        )
        if revision is not None:
            request.revision = revision
        response = await self._rpc.invoke(self._stub.TrashNode, request, actor=actor)
        return _trash(response.entry)

    async def list_trash(
        self,
        filesystem_id: str,
        scope_id: str,
        *,
        actor: Actor | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> tuple[tuple[TrashEntry, ...], str | None]:
        request = pb.ListTrashRequest(filesystem_id=filesystem_id, scope_id=scope_id)
        if limit is not None:
            request.limit = limit
        if cursor is not None:
            request.cursor = cursor
        response = await self._rpc.invoke(self._stub.ListTrash, request, actor=actor)
        return tuple(_trash(item) for item in response.items), (
            response.next_cursor if response.HasField("next_cursor") else None
        )

    async def get_trash(
        self,
        filesystem_id: str,
        scope_id: str,
        entry_id: str,
        *,
        actor: Actor | None = None,
    ) -> TrashEntry:
        response = await self._rpc.invoke(
            self._stub.GetTrash,
            pb.GetTrashRequest(
                filesystem_id=filesystem_id, scope_id=scope_id, entry_id=entry_id
            ),
            actor=actor,
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
        self,
        filesystem_id: str,
        scope_id: str,
        entry_id: str,
        *,
        actor: Actor | None = None,
        destination_scope_id: str | None = None,
        root_id: str | None = None,
        parent: Locator | None = None,
        name: str | None = None,
    ) -> Node:
        request = pb.RestoreTrashRequest(
            filesystem_id=filesystem_id,
            scope_id=scope_id,
            entry_id=entry_id,
            root_id=root_id,
        )
        if destination_scope_id is not None:
            request.destination_scope_id = destination_scope_id
        if parent is not None:
            request.parent.CopyFrom(_locator(parent))
        if name is not None:
            request.name = name
        response = await self._rpc.invoke(self._stub.RestoreTrash, request, actor=actor)
        return _node(response.node, destination_scope_id or scope_id)

    async def purge_trash(
        self,
        filesystem_id: str,
        scope_id: str,
        entry_id: str,
        *,
        actor: Actor | None = None,
    ) -> None:
        await self._rpc.invoke(
            self._stub.PurgeTrash,
            pb.PurgeTrashRequest(
                filesystem_id=filesystem_id, scope_id=scope_id, entry_id=entry_id
            ),
            actor=actor,
            timeout=120,
        )

    async def create_upload(
        self,
        filesystem_id: str,
        scope_id: str,
        idempotency_key: str,
        media_type: str,
        *,
        destination: UploadDestination | None = None,
        replacement: UploadReplacement | None = None,
        size_bytes: int | None = None,
        content_md5: str | None = None,
        actor: Actor | None = None,
    ) -> FileUpload:
        if (destination is None) == (replacement is None):
            raise ValueError("upload requires exactly one target")
        request = pb.CreateUploadRequest(
            filesystem_id=filesystem_id,
            scope_id=scope_id,
            idempotency_key=idempotency_key,
            media_type=media_type,
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
        response = await self._rpc.invoke(self._stub.CreateUpload, request, actor=actor)
        return _file_upload(response.upload)

    async def get_upload(
        self,
        filesystem_id: str,
        scope_id: str,
        upload_id: str,
        *,
        actor: Actor | None = None,
    ) -> FileUpload:
        response = await self._rpc.invoke(
            self._stub.GetUpload,
            pb.GetUploadRequest(
                filesystem_id=filesystem_id, scope_id=scope_id, upload_id=upload_id
            ),
            actor=actor,
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
        scope_id: str,
        upload_id: str,
        numbers: Sequence[int],
        *,
        actor: Actor | None = None,
    ) -> tuple[UploadPart, ...]:
        response = await self._rpc.invoke(
            self._stub.GetUploadParts,
            pb.GetUploadPartsRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                upload_id=upload_id,
                numbers=numbers,
            ),
            actor=actor,
        )
        return tuple(
            UploadPart(item.part_number, _transfer(item.transfer))
            for item in response.items
        )

    async def complete_upload(
        self,
        filesystem_id: str,
        scope_id: str,
        upload_id: str,
        parts: Sequence[PartReceipt] = (),
        *,
        actor: Actor | None = None,
    ) -> UploadPublication:
        response = await self._rpc.invoke(
            self._stub.CompleteUpload,
            pb.CompleteUploadRequest(
                filesystem_id=filesystem_id,
                scope_id=scope_id,
                upload_id=upload_id,
                parts=[
                    pb.PartReceipt(part_number=item.part_number, etag=item.etag)
                    for item in parts
                ],
            ),
            actor=actor,
        )
        return _publication(response.publication)

    async def abort_upload(
        self,
        filesystem_id: str,
        scope_id: str,
        upload_id: str,
        *,
        actor: Actor | None = None,
    ) -> None:
        await self._rpc.invoke(
            self._stub.AbortUpload,
            pb.AbortUploadRequest(
                filesystem_id=filesystem_id, scope_id=scope_id, upload_id=upload_id
            ),
            actor=actor,
        )

    async def search_files(
        self,
        filesystem_id: str,
        scope_id: str,
        query: str,
        *,
        actor: Actor | None = None,
        filters: SearchFilters | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        sort: str | None = None,
        direction: str | None = None,
    ) -> SearchPage:
        request = pb.SearchFilesRequest(
            filesystem_id=filesystem_id,
            scope_id=scope_id,
            query=query,
            filters=_search_filters(filters),
        )
        for name, value in (
            ("limit", limit),
            ("cursor", cursor),
            ("sort", sort),
            ("direction", direction),
        ):
            if value is not None:
                setattr(request, name, value)
        return _search_page(
            await self._rpc.invoke(self._stub.SearchFiles, request, actor=actor),
            scope_id,
        )

    async def semantic_search(
        self,
        filesystem_id: str,
        scope_id: str,
        query: str,
        *,
        actor: Actor | None = None,
        filters: SearchFilters | None = None,
        limit: int | None = None,
    ) -> SemanticSearchResults:
        request = pb.SemanticSearchRequest(
            filesystem_id=filesystem_id,
            scope_id=scope_id,
            query=query,
            filters=_search_filters(filters),
        )
        if limit is not None:
            request.limit = limit
        value = await self._rpc.invoke(self._stub.SemanticSearch, request, actor=actor)
        return SemanticSearchResults(
            tuple(_search_result(item, scope_id) for item in value.items),
            value.degraded,
            value.degraded_reason if value.HasField("degraded_reason") else None,
        )

    async def get_download(
        self,
        filesystem_id: str,
        scope_id: str,
        node_id: str,
        *,
        actor: Actor | None = None,
        revision: int | None = None,
    ) -> Download:
        request = pb.GetDownloadRequest(
            filesystem_id=filesystem_id,
            scope_id=scope_id,
            node_id=node_id,
        )
        if revision is not None:
            request.revision = revision
        value = (
            await self._rpc.invoke(self._stub.GetDownload, request, actor=actor)
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
        scope_id: str,
        node_id: str,
        *,
        actor: Actor | None = None,
    ) -> AsyncIterator[ArchiveFrame]:
        request = pb.StreamArchiveRequest(
            filesystem_id=filesystem_id,
            scope_id=scope_id,
            node_id=node_id,
        )
        async with aclosing(
            self._rpc.invoke_stream(self._stub.StreamArchive, request, actor=actor)
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

    async def list_scopes(
        self, filesystem_id: str, *, limit: int = 100, cursor: str | None = None
    ) -> ScopePage:
        if not 1 <= limit <= 100 or cursor is not None and not 1 <= len(cursor) <= 512:
            raise ValueError("invalid scope page")
        response = await self._rpc.invoke(
            self._stub.ListScopes,
            pb.ListScopesRequest(
                filesystem_id=filesystem_id, limit=limit, cursor=cursor
            ),
            timeout=10,
        )
        values = response.scopes
        next_cursor = response.next_cursor if response.HasField("next_cursor") else None
        if (
            len(values) > limit
            or any(
                not value.id
                or not value.root_id
                or value.filesystem_id != filesystem_id
                or value.state != "active"
                for value in values
            )
            or [value.id for value in values] != sorted({value.id for value in values})
            or len({value.root_id for value in values}) != len(values)
            or next_cursor is not None
            and (
                not values or not 1 <= len(next_cursor) <= 512 or next_cursor == cursor
            )
        ):
            raise AppError(
                "invalid scope result",
                reason="STORAGE_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return ScopePage(
            tuple(
                Scope(
                    value.id,
                    value.filesystem_id,
                    value.root_id,
                    value.state,
                    value.allow_blob_files,
                    value.allow_indexing,
                )
                for value in values
            ),
            next_cursor,
        )

    async def create_filesystem(
        self,
        filesystem_id: str,
        limit_bytes: int,
        idempotency_key: str,
    ) -> Filesystem:
        value = (
            await self._rpc.invoke(
                self._stub.CreateFilesystem,
                pb.CreateFilesystemRequest(
                    filesystem_id=filesystem_id,
                    limit_bytes=limit_bytes,
                    idempotency_key=idempotency_key,
                ),
                timeout=10,
            )
        ).filesystem
        if value.id != filesystem_id or value.limit_bytes != limit_bytes:
            raise AppError(
                "invalid filesystem result",
                reason="STORAGE_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return Filesystem(
            value.id,
            value.limit_bytes,
            value.used_bytes,
            value.node_count,
            value.state,
        )

    async def create_scopes(
        self,
        filesystem_id: str,
        scope_ids: Sequence[str],
        idempotency_key: str,
        *,
        allow_blob_files: bool = True,
        allow_indexing: bool = True,
    ) -> tuple[Scope, ...]:
        if not 1 <= len(scope_ids) <= 100 or len(set(scope_ids)) != len(scope_ids):
            raise ValueError("scope IDs must contain 1 to 100 distinct IDs")
        response = await self._rpc.invoke(
            self._stub.CreateScopes,
            pb.CreateScopesRequest(
                filesystem_id=filesystem_id,
                scope_ids=scope_ids,
                allow_blob_files=allow_blob_files,
                allow_indexing=allow_indexing,
                idempotency_key=idempotency_key,
            ),
            timeout=10,
        )
        if (
            len(response.scopes) != len(scope_ids)
            or {v.id for v in response.scopes} != set(scope_ids)
            or any(
                v.filesystem_id != filesystem_id
                or not v.root_id
                or v.allow_blob_files != allow_blob_files
                or v.allow_indexing != allow_indexing
                for v in response.scopes
            )
        ):
            raise AppError(
                "invalid scope result",
                reason="STORAGE_SCOPE_CONFLICT",
                kind="conflict",
                retryable=False,
            )
        return tuple(
            Scope(
                v.id,
                v.filesystem_id,
                v.root_id,
                v.state,
                v.allow_blob_files,
                v.allow_indexing,
            )
            for v in response.scopes
        )

    async def delete_filesystem(self, filesystem_id: str) -> bool:
        response = await self._rpc.invoke(
            self._stub.DeleteFilesystem,
            pb.DeleteFilesystemRequest(filesystem_id=filesystem_id),
            timeout=10,
        )
        return response.completed
