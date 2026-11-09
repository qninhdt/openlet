import datetime

from google.api import annotations_pb2 as _annotations_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class DeleteFilesystemRequest(_message.Message):
    __slots__ = ("filesystem_id",)
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    def __init__(self, filesystem_id: _Optional[str] = ...) -> None: ...

class DeleteFilesystemResponse(_message.Message):
    __slots__ = ("completed",)
    COMPLETED_FIELD_NUMBER: _ClassVar[int]
    completed: bool
    def __init__(self, completed: _Optional[bool] = ...) -> None: ...

class Node(_message.Message):
    __slots__ = ("id", "parent_id", "name", "kind", "revision", "size_bytes", "media_type", "created_at", "updated_at", "title", "description", "semantic_type", "context", "scope_id", "readonly")
    ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    SEMANTIC_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    READONLY_FIELD_NUMBER: _ClassVar[int]
    id: str
    parent_id: str
    name: str
    kind: str
    revision: int
    size_bytes: int
    media_type: str
    created_at: _timestamp_pb2.Timestamp
    updated_at: _timestamp_pb2.Timestamp
    title: str
    description: str
    semantic_type: str
    context: str
    scope_id: str
    readonly: bool
    def __init__(self, id: _Optional[str] = ..., parent_id: _Optional[str] = ..., name: _Optional[str] = ..., kind: _Optional[str] = ..., revision: _Optional[int] = ..., size_bytes: _Optional[int] = ..., media_type: _Optional[str] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., updated_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., title: _Optional[str] = ..., description: _Optional[str] = ..., semantic_type: _Optional[str] = ..., context: _Optional[str] = ..., scope_id: _Optional[str] = ..., readonly: _Optional[bool] = ...) -> None: ...

class GetNodeRequest(_message.Message):
    __slots__ = ("filesystem_id", "node_id", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    node_id: str
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., node_id: _Optional[str] = ..., scope_id: _Optional[str] = ...) -> None: ...

class GetNodeResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class GetDownloadRequest(_message.Message):
    __slots__ = ("filesystem_id", "node_id", "revision", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    node_id: str
    revision: int
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., node_id: _Optional[str] = ..., revision: _Optional[int] = ..., scope_id: _Optional[str] = ...) -> None: ...

class Download(_message.Message):
    __slots__ = ("mime", "filename", "etag", "size_bytes", "inline_content", "signed_url")
    MIME_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    INLINE_CONTENT_FIELD_NUMBER: _ClassVar[int]
    SIGNED_URL_FIELD_NUMBER: _ClassVar[int]
    mime: str
    filename: str
    etag: str
    size_bytes: int
    inline_content: bytes
    signed_url: str
    def __init__(self, mime: _Optional[str] = ..., filename: _Optional[str] = ..., etag: _Optional[str] = ..., size_bytes: _Optional[int] = ..., inline_content: _Optional[bytes] = ..., signed_url: _Optional[str] = ...) -> None: ...

class GetDownloadResponse(_message.Message):
    __slots__ = ("download",)
    DOWNLOAD_FIELD_NUMBER: _ClassVar[int]
    download: Download
    def __init__(self, download: _Optional[_Union[Download, _Mapping]] = ...) -> None: ...

class StreamArchiveRequest(_message.Message):
    __slots__ = ("filesystem_id", "node_id", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    node_id: str
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., node_id: _Optional[str] = ..., scope_id: _Optional[str] = ...) -> None: ...

class ArchiveMetadata(_message.Message):
    __slots__ = ("filename", "mime")
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    MIME_FIELD_NUMBER: _ClassVar[int]
    filename: str
    mime: str
    def __init__(self, filename: _Optional[str] = ..., mime: _Optional[str] = ...) -> None: ...

class StreamArchiveResponse(_message.Message):
    __slots__ = ("metadata", "data")
    METADATA_FIELD_NUMBER: _ClassVar[int]
    DATA_FIELD_NUMBER: _ClassVar[int]
    metadata: ArchiveMetadata
    data: bytes
    def __init__(self, metadata: _Optional[_Union[ArchiveMetadata, _Mapping]] = ..., data: _Optional[bytes] = ...) -> None: ...

class PrepareParseRequest(_message.Message):
    __slots__ = ("file_id", "generation")
    FILE_ID_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    file_id: str
    generation: int
    def __init__(self, file_id: _Optional[str] = ..., generation: _Optional[int] = ...) -> None: ...

class ParseInput(_message.Message):
    __slots__ = ("source_id", "format", "size_bytes", "inline_limit_bytes", "multipart_threshold_bytes", "max_outputs", "max_output_bytes", "inline_content", "signed_url")
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    FORMAT_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    INLINE_LIMIT_BYTES_FIELD_NUMBER: _ClassVar[int]
    MULTIPART_THRESHOLD_BYTES_FIELD_NUMBER: _ClassVar[int]
    MAX_OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    MAX_OUTPUT_BYTES_FIELD_NUMBER: _ClassVar[int]
    INLINE_CONTENT_FIELD_NUMBER: _ClassVar[int]
    SIGNED_URL_FIELD_NUMBER: _ClassVar[int]
    source_id: str
    format: str
    size_bytes: int
    inline_limit_bytes: int
    multipart_threshold_bytes: int
    max_outputs: int
    max_output_bytes: int
    inline_content: bytes
    signed_url: str
    def __init__(self, source_id: _Optional[str] = ..., format: _Optional[str] = ..., size_bytes: _Optional[int] = ..., inline_limit_bytes: _Optional[int] = ..., multipart_threshold_bytes: _Optional[int] = ..., max_outputs: _Optional[int] = ..., max_output_bytes: _Optional[int] = ..., inline_content: _Optional[bytes] = ..., signed_url: _Optional[str] = ...) -> None: ...

class ParseComplete(_message.Message):
    __slots__ = ("source_id",)
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    source_id: str
    def __init__(self, source_id: _Optional[str] = ...) -> None: ...

class PrepareParseResponse(_message.Message):
    __slots__ = ("input", "complete")
    INPUT_FIELD_NUMBER: _ClassVar[int]
    COMPLETE_FIELD_NUMBER: _ClassVar[int]
    input: ParseInput
    complete: ParseComplete
    def __init__(self, input: _Optional[_Union[ParseInput, _Mapping]] = ..., complete: _Optional[_Union[ParseComplete, _Mapping]] = ...) -> None: ...

class CreateFilesystemRequest(_message.Message):
    __slots__ = ("filesystem_id", "idempotency_key", "limit_bytes")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    LIMIT_BYTES_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    idempotency_key: str
    limit_bytes: int
    def __init__(self, filesystem_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., limit_bytes: _Optional[int] = ...) -> None: ...

class Filesystem(_message.Message):
    __slots__ = ("id", "limit_bytes", "used_bytes", "node_count", "state")
    ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_BYTES_FIELD_NUMBER: _ClassVar[int]
    USED_BYTES_FIELD_NUMBER: _ClassVar[int]
    NODE_COUNT_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    id: str
    limit_bytes: int
    used_bytes: int
    node_count: int
    state: str
    def __init__(self, id: _Optional[str] = ..., limit_bytes: _Optional[int] = ..., used_bytes: _Optional[int] = ..., node_count: _Optional[int] = ..., state: _Optional[str] = ...) -> None: ...

class CreateFilesystemResponse(_message.Message):
    __slots__ = ("filesystem",)
    FILESYSTEM_FIELD_NUMBER: _ClassVar[int]
    filesystem: Filesystem
    def __init__(self, filesystem: _Optional[_Union[Filesystem, _Mapping]] = ...) -> None: ...

class PathLocator(_message.Message):
    __slots__ = ("path", "cwd_id")
    PATH_FIELD_NUMBER: _ClassVar[int]
    CWD_ID_FIELD_NUMBER: _ClassVar[int]
    path: str
    cwd_id: str
    def __init__(self, path: _Optional[str] = ..., cwd_id: _Optional[str] = ...) -> None: ...

class Locator(_message.Message):
    __slots__ = ("node_id", "path", "expected_node_id", "expected_parent_id", "root_id")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_NODE_ID_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    ROOT_ID_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    path: PathLocator
    expected_node_id: str
    expected_parent_id: str
    root_id: str
    def __init__(self, node_id: _Optional[str] = ..., path: _Optional[_Union[PathLocator, _Mapping]] = ..., expected_node_id: _Optional[str] = ..., expected_parent_id: _Optional[str] = ..., root_id: _Optional[str] = ...) -> None: ...

class FileStat(_message.Message):
    __slots__ = ("node", "storage_kind", "representation_kind", "readable_size", "fingerprint", "newline_count", "sha256")
    NODE_FIELD_NUMBER: _ClassVar[int]
    STORAGE_KIND_FIELD_NUMBER: _ClassVar[int]
    REPRESENTATION_KIND_FIELD_NUMBER: _ClassVar[int]
    READABLE_SIZE_FIELD_NUMBER: _ClassVar[int]
    FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    NEWLINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    node: Node
    storage_kind: str
    representation_kind: str
    readable_size: int
    fingerprint: str
    newline_count: int
    sha256: str
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ..., storage_kind: _Optional[str] = ..., representation_kind: _Optional[str] = ..., readable_size: _Optional[int] = ..., fingerprint: _Optional[str] = ..., newline_count: _Optional[int] = ..., sha256: _Optional[str] = ...) -> None: ...

class StatRequest(_message.Message):
    __slots__ = ("filesystem_id", "scope_id", "locator", "content_check")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    CONTENT_CHECK_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    scope_id: str
    locator: Locator
    content_check: bool
    def __init__(self, filesystem_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ..., content_check: _Optional[bool] = ...) -> None: ...

class StatResponse(_message.Message):
    __slots__ = ("stat",)
    STAT_FIELD_NUMBER: _ClassVar[int]
    stat: FileStat
    def __init__(self, stat: _Optional[_Union[FileStat, _Mapping]] = ...) -> None: ...

class ByteRange(_message.Message):
    __slots__ = ("offset", "length")
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    LENGTH_FIELD_NUMBER: _ClassVar[int]
    offset: int
    length: int
    def __init__(self, offset: _Optional[int] = ..., length: _Optional[int] = ...) -> None: ...

class LineRange(_message.Message):
    __slots__ = ("start_line", "line_count")
    START_LINE_FIELD_NUMBER: _ClassVar[int]
    LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    start_line: int
    line_count: int
    def __init__(self, start_line: _Optional[int] = ..., line_count: _Optional[int] = ...) -> None: ...

class LineCount(_message.Message):
    __slots__ = ("line_count",)
    LINE_COUNT_FIELD_NUMBER: _ClassVar[int]
    line_count: int
    def __init__(self, line_count: _Optional[int] = ...) -> None: ...

class WholeText(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ReadTextRequest(_message.Message):
    __slots__ = ("filesystem_id", "scope_id", "locator", "whole", "bytes", "lines", "head", "tail", "expected_fingerprint")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    WHOLE_FIELD_NUMBER: _ClassVar[int]
    BYTES_FIELD_NUMBER: _ClassVar[int]
    LINES_FIELD_NUMBER: _ClassVar[int]
    HEAD_FIELD_NUMBER: _ClassVar[int]
    TAIL_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    scope_id: str
    locator: Locator
    whole: WholeText
    bytes: ByteRange
    lines: LineRange
    head: LineCount
    tail: LineCount
    expected_fingerprint: str
    def __init__(self, filesystem_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ..., whole: _Optional[_Union[WholeText, _Mapping]] = ..., bytes: _Optional[_Union[ByteRange, _Mapping]] = ..., lines: _Optional[_Union[LineRange, _Mapping]] = ..., head: _Optional[_Union[LineCount, _Mapping]] = ..., tail: _Optional[_Union[LineCount, _Mapping]] = ..., expected_fingerprint: _Optional[str] = ...) -> None: ...

class ReadTextResponse(_message.Message):
    __slots__ = ("stat", "content", "offset", "length")
    STAT_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    LENGTH_FIELD_NUMBER: _ClassVar[int]
    stat: FileStat
    content: bytes
    offset: int
    length: int
    def __init__(self, stat: _Optional[_Union[FileStat, _Mapping]] = ..., content: _Optional[bytes] = ..., offset: _Optional[int] = ..., length: _Optional[int] = ...) -> None: ...

class TextMetricsRequest(_message.Message):
    __slots__ = ("filesystem_id", "scope_id", "locator", "algorithm")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    ALGORITHM_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    scope_id: str
    locator: Locator
    algorithm: str
    def __init__(self, filesystem_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ..., algorithm: _Optional[str] = ...) -> None: ...

class TextMetricsResponse(_message.Message):
    __slots__ = ("stat", "algorithm", "digest", "supported")
    STAT_FIELD_NUMBER: _ClassVar[int]
    ALGORITHM_FIELD_NUMBER: _ClassVar[int]
    DIGEST_FIELD_NUMBER: _ClassVar[int]
    SUPPORTED_FIELD_NUMBER: _ClassVar[int]
    stat: FileStat
    algorithm: str
    digest: str
    supported: bool
    def __init__(self, stat: _Optional[_Union[FileStat, _Mapping]] = ..., algorithm: _Optional[str] = ..., digest: _Optional[str] = ..., supported: _Optional[bool] = ...) -> None: ...

class ReadTreeRequest(_message.Message):
    __slots__ = ("filesystem_id", "scope_id", "root", "depth", "cursor", "limit", "max_bytes")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    ROOT_FIELD_NUMBER: _ClassVar[int]
    DEPTH_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    MAX_BYTES_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    scope_id: str
    root: Locator
    depth: int
    cursor: str
    limit: int
    max_bytes: int
    def __init__(self, filesystem_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., root: _Optional[_Union[Locator, _Mapping]] = ..., depth: _Optional[int] = ..., cursor: _Optional[str] = ..., limit: _Optional[int] = ..., max_bytes: _Optional[int] = ...) -> None: ...

class TreeEntry(_message.Message):
    __slots__ = ("path", "stat")
    PATH_FIELD_NUMBER: _ClassVar[int]
    STAT_FIELD_NUMBER: _ClassVar[int]
    path: str
    stat: FileStat
    def __init__(self, path: _Optional[str] = ..., stat: _Optional[_Union[FileStat, _Mapping]] = ...) -> None: ...

class ReadTreeResponse(_message.Message):
    __slots__ = ("items", "next_cursor", "complete")
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    NEXT_CURSOR_FIELD_NUMBER: _ClassVar[int]
    COMPLETE_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[TreeEntry]
    next_cursor: str
    complete: bool
    def __init__(self, items: _Optional[_Iterable[_Union[TreeEntry, _Mapping]]] = ..., next_cursor: _Optional[str] = ..., complete: _Optional[bool] = ...) -> None: ...

class TextSearchRequest(_message.Message):
    __slots__ = ("filesystem_id", "scope_id", "locator", "mode", "text", "ignore_case", "max_files", "max_lines", "max_bytes")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    IGNORE_CASE_FIELD_NUMBER: _ClassVar[int]
    MAX_FILES_FIELD_NUMBER: _ClassVar[int]
    MAX_LINES_FIELD_NUMBER: _ClassVar[int]
    MAX_BYTES_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    scope_id: str
    locator: Locator
    mode: str
    text: str
    ignore_case: bool
    max_files: int
    max_lines: int
    max_bytes: int
    def __init__(self, filesystem_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ..., mode: _Optional[str] = ..., text: _Optional[str] = ..., ignore_case: _Optional[bool] = ..., max_files: _Optional[int] = ..., max_lines: _Optional[int] = ..., max_bytes: _Optional[int] = ...) -> None: ...

class TextSearchResponse(_message.Message):
    __slots__ = ("complete", "items", "content", "stat")
    COMPLETE_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    STAT_FIELD_NUMBER: _ClassVar[int]
    complete: bool
    items: _containers.RepeatedCompositeFieldContainer[TreeEntry]
    content: bytes
    stat: FileStat
    def __init__(self, complete: _Optional[bool] = ..., items: _Optional[_Iterable[_Union[TreeEntry, _Mapping]]] = ..., content: _Optional[bytes] = ..., stat: _Optional[_Union[FileStat, _Mapping]] = ...) -> None: ...

class ReadImageRequest(_message.Message):
    __slots__ = ("filesystem_id", "scope_id", "locator", "expected_fingerprint")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    scope_id: str
    locator: Locator
    expected_fingerprint: str
    def __init__(self, filesystem_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ..., expected_fingerprint: _Optional[str] = ...) -> None: ...

class ReadImageResponse(_message.Message):
    __slots__ = ("stat", "content", "mime", "width", "height", "sha256")
    STAT_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    MIME_FIELD_NUMBER: _ClassVar[int]
    WIDTH_FIELD_NUMBER: _ClassVar[int]
    HEIGHT_FIELD_NUMBER: _ClassVar[int]
    SHA256_FIELD_NUMBER: _ClassVar[int]
    stat: FileStat
    content: bytes
    mime: str
    width: int
    height: int
    sha256: str
    def __init__(self, stat: _Optional[_Union[FileStat, _Mapping]] = ..., content: _Optional[bytes] = ..., mime: _Optional[str] = ..., width: _Optional[int] = ..., height: _Optional[int] = ..., sha256: _Optional[str] = ...) -> None: ...

class GetFilesystemRequest(_message.Message):
    __slots__ = ("filesystem_id",)
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    def __init__(self, filesystem_id: _Optional[str] = ...) -> None: ...

class GetFilesystemResponse(_message.Message):
    __slots__ = ("filesystem",)
    FILESYSTEM_FIELD_NUMBER: _ClassVar[int]
    filesystem: Filesystem
    def __init__(self, filesystem: _Optional[_Union[Filesystem, _Mapping]] = ...) -> None: ...

class ExistingText(_message.Message):
    __slots__ = ("locator", "revision", "expected_fingerprint")
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    locator: Locator
    revision: int
    expected_fingerprint: str
    def __init__(self, locator: _Optional[_Union[Locator, _Mapping]] = ..., revision: _Optional[int] = ..., expected_fingerprint: _Optional[str] = ...) -> None: ...

class TextCreation(_message.Message):
    __slots__ = ("parent", "name", "media_type", "idempotency_key", "node_id")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    parent: Locator
    name: str
    media_type: str
    idempotency_key: str
    node_id: str
    def __init__(self, parent: _Optional[_Union[Locator, _Mapping]] = ..., name: _Optional[str] = ..., media_type: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., node_id: _Optional[str] = ...) -> None: ...

class TextTarget(_message.Message):
    __slots__ = ("existing", "create")
    EXISTING_FIELD_NUMBER: _ClassVar[int]
    CREATE_FIELD_NUMBER: _ClassVar[int]
    existing: ExistingText
    create: TextCreation
    def __init__(self, existing: _Optional[_Union[ExistingText, _Mapping]] = ..., create: _Optional[_Union[TextCreation, _Mapping]] = ...) -> None: ...

class WriteTextRequest(_message.Message):
    __slots__ = ("filesystem_id", "scope_id", "target", "content")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    scope_id: str
    target: TextTarget
    content: bytes
    def __init__(self, filesystem_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., target: _Optional[_Union[TextTarget, _Mapping]] = ..., content: _Optional[bytes] = ...) -> None: ...

class AppendTextRequest(_message.Message):
    __slots__ = ("filesystem_id", "scope_id", "target", "content")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    scope_id: str
    target: TextTarget
    content: bytes
    def __init__(self, filesystem_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., target: _Optional[_Union[TextTarget, _Mapping]] = ..., content: _Optional[bytes] = ...) -> None: ...

class ByteOverwrite(_message.Message):
    __slots__ = ("offset", "content")
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    offset: int
    content: bytes
    def __init__(self, offset: _Optional[int] = ..., content: _Optional[bytes] = ...) -> None: ...

class LiteralReplacement(_message.Message):
    __slots__ = ("old_text", "new_text", "replace_all")
    OLD_TEXT_FIELD_NUMBER: _ClassVar[int]
    NEW_TEXT_FIELD_NUMBER: _ClassVar[int]
    REPLACE_ALL_FIELD_NUMBER: _ClassVar[int]
    old_text: str
    new_text: str
    replace_all: bool
    def __init__(self, old_text: _Optional[str] = ..., new_text: _Optional[str] = ..., replace_all: _Optional[bool] = ...) -> None: ...

class PatchTextRequest(_message.Message):
    __slots__ = ("filesystem_id", "scope_id", "target", "bytes", "literal")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    BYTES_FIELD_NUMBER: _ClassVar[int]
    LITERAL_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    scope_id: str
    target: TextTarget
    bytes: ByteOverwrite
    literal: LiteralReplacement
    def __init__(self, filesystem_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., target: _Optional[_Union[TextTarget, _Mapping]] = ..., bytes: _Optional[_Union[ByteOverwrite, _Mapping]] = ..., literal: _Optional[_Union[LiteralReplacement, _Mapping]] = ...) -> None: ...

class TruncateTextRequest(_message.Message):
    __slots__ = ("filesystem_id", "scope_id", "target", "length", "no_create")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    LENGTH_FIELD_NUMBER: _ClassVar[int]
    NO_CREATE_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    scope_id: str
    target: TextTarget
    length: int
    no_create: bool
    def __init__(self, filesystem_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., target: _Optional[_Union[TextTarget, _Mapping]] = ..., length: _Optional[int] = ..., no_create: _Optional[bool] = ...) -> None: ...

class TextMutation(_message.Message):
    __slots__ = ("stat", "before_revision", "before_fingerprint")
    STAT_FIELD_NUMBER: _ClassVar[int]
    BEFORE_REVISION_FIELD_NUMBER: _ClassVar[int]
    BEFORE_FINGERPRINT_FIELD_NUMBER: _ClassVar[int]
    stat: FileStat
    before_revision: int
    before_fingerprint: str
    def __init__(self, stat: _Optional[_Union[FileStat, _Mapping]] = ..., before_revision: _Optional[int] = ..., before_fingerprint: _Optional[str] = ...) -> None: ...

class WriteTextResponse(_message.Message):
    __slots__ = ("result",)
    RESULT_FIELD_NUMBER: _ClassVar[int]
    result: TextMutation
    def __init__(self, result: _Optional[_Union[TextMutation, _Mapping]] = ...) -> None: ...

class AppendTextResponse(_message.Message):
    __slots__ = ("result",)
    RESULT_FIELD_NUMBER: _ClassVar[int]
    result: TextMutation
    def __init__(self, result: _Optional[_Union[TextMutation, _Mapping]] = ...) -> None: ...

class PatchTextResponse(_message.Message):
    __slots__ = ("result",)
    RESULT_FIELD_NUMBER: _ClassVar[int]
    result: TextMutation
    def __init__(self, result: _Optional[_Union[TextMutation, _Mapping]] = ...) -> None: ...

class TruncateTextResponse(_message.Message):
    __slots__ = ("result",)
    RESULT_FIELD_NUMBER: _ClassVar[int]
    result: TextMutation
    def __init__(self, result: _Optional[_Union[TextMutation, _Mapping]] = ...) -> None: ...

class DirectoryCreation(_message.Message):
    __slots__ = ("parent", "name")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    parent: Locator
    name: str
    def __init__(self, parent: _Optional[_Union[Locator, _Mapping]] = ..., name: _Optional[str] = ...) -> None: ...

class CreateDirectoriesRequest(_message.Message):
    __slots__ = ("filesystem_id", "scope_id", "parent", "components", "parents")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_FIELD_NUMBER: _ClassVar[int]
    COMPONENTS_FIELD_NUMBER: _ClassVar[int]
    PARENTS_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    scope_id: str
    parent: Locator
    components: _containers.RepeatedScalarFieldContainer[str]
    parents: bool
    def __init__(self, filesystem_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., parent: _Optional[_Union[Locator, _Mapping]] = ..., components: _Optional[_Iterable[str]] = ..., parents: _Optional[bool] = ...) -> None: ...

class CreateDirectoriesResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class InlineFileCreation(_message.Message):
    __slots__ = ("parent", "name", "content", "media_type")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    parent: Locator
    name: str
    content: bytes
    media_type: str
    def __init__(self, parent: _Optional[_Union[Locator, _Mapping]] = ..., name: _Optional[str] = ..., content: _Optional[bytes] = ..., media_type: _Optional[str] = ...) -> None: ...

class CreateNodeRequest(_message.Message):
    __slots__ = ("filesystem_id", "idempotency_key", "directory", "file", "scope_id", "node_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    DIRECTORY_FIELD_NUMBER: _ClassVar[int]
    FILE_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    idempotency_key: str
    directory: DirectoryCreation
    file: InlineFileCreation
    scope_id: str
    node_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., directory: _Optional[_Union[DirectoryCreation, _Mapping]] = ..., file: _Optional[_Union[InlineFileCreation, _Mapping]] = ..., scope_id: _Optional[str] = ..., node_id: _Optional[str] = ...) -> None: ...

class CreateNodeResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class ListNodesRequest(_message.Message):
    __slots__ = ("filesystem_id", "parent", "limit", "cursor", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    parent: Locator
    limit: int
    cursor: str
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., parent: _Optional[_Union[Locator, _Mapping]] = ..., limit: _Optional[int] = ..., cursor: _Optional[str] = ..., scope_id: _Optional[str] = ...) -> None: ...

class ListNodesResponse(_message.Message):
    __slots__ = ("items", "next_cursor")
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    NEXT_CURSOR_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[Node]
    next_cursor: str
    def __init__(self, items: _Optional[_Iterable[_Union[Node, _Mapping]]] = ..., next_cursor: _Optional[str] = ...) -> None: ...

class ResolveNodeRequest(_message.Message):
    __slots__ = ("filesystem_id", "locator", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    locator: Locator
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ..., scope_id: _Optional[str] = ...) -> None: ...

class ResolveNodeResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class BatchStatRequest(_message.Message):
    __slots__ = ("filesystem_id", "locators")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATORS_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    locators: _containers.RepeatedCompositeFieldContainer[ScopedLocator]
    def __init__(self, filesystem_id: _Optional[str] = ..., locators: _Optional[_Iterable[_Union[ScopedLocator, _Mapping]]] = ...) -> None: ...

class ScopedLocator(_message.Message):
    __slots__ = ("scope_id", "locator")
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    scope_id: str
    locator: Locator
    def __init__(self, scope_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ...) -> None: ...

class BatchStatResponse(_message.Message):
    __slots__ = ("items",)
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[Node]
    def __init__(self, items: _Optional[_Iterable[_Union[Node, _Mapping]]] = ...) -> None: ...

class UpdateNodeRequest(_message.Message):
    __slots__ = ("destination_scope_id", "filesystem_id", "locator", "revision", "name", "parent", "scope_id")
    DESTINATION_SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    PARENT_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    destination_scope_id: str
    filesystem_id: str
    locator: Locator
    revision: int
    name: str
    parent: Locator
    scope_id: str
    def __init__(self, destination_scope_id: _Optional[str] = ..., filesystem_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ..., revision: _Optional[int] = ..., name: _Optional[str] = ..., parent: _Optional[_Union[Locator, _Mapping]] = ..., scope_id: _Optional[str] = ...) -> None: ...

class UpdateNodeResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class ReplaceContentRequest(_message.Message):
    __slots__ = ("filesystem_id", "locator", "revision", "content", "media_type", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    locator: Locator
    revision: int
    content: bytes
    media_type: str
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ..., revision: _Optional[int] = ..., content: _Optional[bytes] = ..., media_type: _Optional[str] = ..., scope_id: _Optional[str] = ...) -> None: ...

class ReplaceContentResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class CreateCopyRequest(_message.Message):
    __slots__ = ("destination_scope_id", "source_root_id", "destination_root_id", "filesystem_id", "source_id", "parent_id", "name", "revision", "idempotency_key", "scope_id")
    DESTINATION_SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_ROOT_ID_FIELD_NUMBER: _ClassVar[int]
    DESTINATION_ROOT_ID_FIELD_NUMBER: _ClassVar[int]
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    destination_scope_id: str
    source_root_id: str
    destination_root_id: str
    filesystem_id: str
    source_id: str
    parent_id: str
    name: str
    revision: int
    idempotency_key: str
    scope_id: str
    def __init__(self, destination_scope_id: _Optional[str] = ..., source_root_id: _Optional[str] = ..., destination_root_id: _Optional[str] = ..., filesystem_id: _Optional[str] = ..., source_id: _Optional[str] = ..., parent_id: _Optional[str] = ..., name: _Optional[str] = ..., revision: _Optional[int] = ..., idempotency_key: _Optional[str] = ..., scope_id: _Optional[str] = ...) -> None: ...

class CreateCopyResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class Processing(_message.Message):
    __slots__ = ("desired_generation", "publication_status", "error_code", "file_id")
    DESIRED_GENERATION_FIELD_NUMBER: _ClassVar[int]
    PUBLICATION_STATUS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    FILE_ID_FIELD_NUMBER: _ClassVar[int]
    desired_generation: int
    publication_status: str
    error_code: str
    file_id: str
    def __init__(self, desired_generation: _Optional[int] = ..., publication_status: _Optional[str] = ..., error_code: _Optional[str] = ..., file_id: _Optional[str] = ...) -> None: ...

class GetProcessingRequest(_message.Message):
    __slots__ = ("filesystem_id", "node_id", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    node_id: str
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., node_id: _Optional[str] = ..., scope_id: _Optional[str] = ...) -> None: ...

class GetProcessingResponse(_message.Message):
    __slots__ = ("processing",)
    PROCESSING_FIELD_NUMBER: _ClassVar[int]
    processing: Processing
    def __init__(self, processing: _Optional[_Union[Processing, _Mapping]] = ...) -> None: ...

class ReprocessNodeRequest(_message.Message):
    __slots__ = ("filesystem_id", "node_id", "idempotency_key", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    node_id: str
    idempotency_key: str
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., node_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., scope_id: _Optional[str] = ...) -> None: ...

class ReprocessNodeResponse(_message.Message):
    __slots__ = ("file_id", "generation", "workflow_id")
    FILE_ID_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    WORKFLOW_ID_FIELD_NUMBER: _ClassVar[int]
    file_id: str
    generation: int
    workflow_id: str
    def __init__(self, file_id: _Optional[str] = ..., generation: _Optional[int] = ..., workflow_id: _Optional[str] = ...) -> None: ...

class TrashEntry(_message.Message):
    __slots__ = ("actor_kind", "id", "node_id", "parent_id", "name", "actor_id", "status", "created_at")
    ACTOR_KIND_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    ACTOR_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    actor_kind: str
    id: str
    node_id: str
    parent_id: str
    name: str
    actor_id: str
    status: str
    created_at: _timestamp_pb2.Timestamp
    def __init__(self, actor_kind: _Optional[str] = ..., id: _Optional[str] = ..., node_id: _Optional[str] = ..., parent_id: _Optional[str] = ..., name: _Optional[str] = ..., actor_id: _Optional[str] = ..., status: _Optional[str] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class TrashNodeRequest(_message.Message):
    __slots__ = ("filesystem_id", "locator", "revision", "scope_id", "empty_directory")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    EMPTY_DIRECTORY_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    locator: Locator
    revision: int
    scope_id: str
    empty_directory: bool
    def __init__(self, filesystem_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ..., revision: _Optional[int] = ..., scope_id: _Optional[str] = ..., empty_directory: _Optional[bool] = ...) -> None: ...

class TrashNodeResponse(_message.Message):
    __slots__ = ("entry",)
    ENTRY_FIELD_NUMBER: _ClassVar[int]
    entry: TrashEntry
    def __init__(self, entry: _Optional[_Union[TrashEntry, _Mapping]] = ...) -> None: ...

class ListTrashRequest(_message.Message):
    __slots__ = ("filesystem_id", "limit", "cursor", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    limit: int
    cursor: str
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., limit: _Optional[int] = ..., cursor: _Optional[str] = ..., scope_id: _Optional[str] = ...) -> None: ...

class ListTrashResponse(_message.Message):
    __slots__ = ("items", "next_cursor")
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    NEXT_CURSOR_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[TrashEntry]
    next_cursor: str
    def __init__(self, items: _Optional[_Iterable[_Union[TrashEntry, _Mapping]]] = ..., next_cursor: _Optional[str] = ...) -> None: ...

class GetTrashRequest(_message.Message):
    __slots__ = ("filesystem_id", "entry_id", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    ENTRY_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    entry_id: str
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., entry_id: _Optional[str] = ..., scope_id: _Optional[str] = ...) -> None: ...

class GetTrashResponse(_message.Message):
    __slots__ = ("entry",)
    ENTRY_FIELD_NUMBER: _ClassVar[int]
    entry: TrashEntry
    def __init__(self, entry: _Optional[_Union[TrashEntry, _Mapping]] = ...) -> None: ...

class RestoreTrashRequest(_message.Message):
    __slots__ = ("filesystem_id", "entry_id", "scope_id", "destination_scope_id", "parent", "name", "root_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    ENTRY_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    DESTINATION_SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    ROOT_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    entry_id: str
    scope_id: str
    destination_scope_id: str
    parent: Locator
    name: str
    root_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., entry_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., destination_scope_id: _Optional[str] = ..., parent: _Optional[_Union[Locator, _Mapping]] = ..., name: _Optional[str] = ..., root_id: _Optional[str] = ...) -> None: ...

class RestoreTrashResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class PurgeTrashRequest(_message.Message):
    __slots__ = ("filesystem_id", "entry_id", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    ENTRY_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    entry_id: str
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., entry_id: _Optional[str] = ..., scope_id: _Optional[str] = ...) -> None: ...

class PurgeTrashResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class UploadDestination(_message.Message):
    __slots__ = ("parent", "name")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    parent: Locator
    name: str
    def __init__(self, parent: _Optional[_Union[Locator, _Mapping]] = ..., name: _Optional[str] = ...) -> None: ...

class UploadReplacement(_message.Message):
    __slots__ = ("locator", "revision")
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    locator: Locator
    revision: int
    def __init__(self, locator: _Optional[_Union[Locator, _Mapping]] = ..., revision: _Optional[int] = ...) -> None: ...

class SignedUpload(_message.Message):
    __slots__ = ("url", "headers", "content_length", "expires_at")
    class HeadersEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    URL_FIELD_NUMBER: _ClassVar[int]
    HEADERS_FIELD_NUMBER: _ClassVar[int]
    CONTENT_LENGTH_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    url: str
    headers: _containers.ScalarMap[str, str]
    content_length: int
    expires_at: _timestamp_pb2.Timestamp
    def __init__(self, url: _Optional[str] = ..., headers: _Optional[_Mapping[str, str]] = ..., content_length: _Optional[int] = ..., expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class UploadReceipt(_message.Message):
    __slots__ = ("id", "status", "size_bytes")
    ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    id: str
    status: str
    size_bytes: int
    def __init__(self, id: _Optional[str] = ..., status: _Optional[str] = ..., size_bytes: _Optional[int] = ...) -> None: ...

class UploadPublication(_message.Message):
    __slots__ = ("node_id", "status", "revision")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    status: str
    revision: int
    def __init__(self, node_id: _Optional[str] = ..., status: _Optional[str] = ..., revision: _Optional[int] = ...) -> None: ...

class Upload(_message.Message):
    __slots__ = ("id", "status", "transport", "expires_at", "size_bytes", "part_size_bytes", "part_count", "transfer", "publication", "receipt")
    ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    TRANSPORT_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    PART_SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    PART_COUNT_FIELD_NUMBER: _ClassVar[int]
    TRANSFER_FIELD_NUMBER: _ClassVar[int]
    PUBLICATION_FIELD_NUMBER: _ClassVar[int]
    RECEIPT_FIELD_NUMBER: _ClassVar[int]
    id: str
    status: str
    transport: str
    expires_at: _timestamp_pb2.Timestamp
    size_bytes: int
    part_size_bytes: int
    part_count: int
    transfer: SignedUpload
    publication: UploadPublication
    receipt: UploadReceipt
    def __init__(self, id: _Optional[str] = ..., status: _Optional[str] = ..., transport: _Optional[str] = ..., expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., size_bytes: _Optional[int] = ..., part_size_bytes: _Optional[int] = ..., part_count: _Optional[int] = ..., transfer: _Optional[_Union[SignedUpload, _Mapping]] = ..., publication: _Optional[_Union[UploadPublication, _Mapping]] = ..., receipt: _Optional[_Union[UploadReceipt, _Mapping]] = ...) -> None: ...

class CreateUploadRequest(_message.Message):
    __slots__ = ("filesystem_id", "idempotency_key", "size_bytes", "media_type", "content_md5", "destination", "replacement", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_MD5_FIELD_NUMBER: _ClassVar[int]
    DESTINATION_FIELD_NUMBER: _ClassVar[int]
    REPLACEMENT_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    idempotency_key: str
    size_bytes: int
    media_type: str
    content_md5: str
    destination: UploadDestination
    replacement: UploadReplacement
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., size_bytes: _Optional[int] = ..., media_type: _Optional[str] = ..., content_md5: _Optional[str] = ..., destination: _Optional[_Union[UploadDestination, _Mapping]] = ..., replacement: _Optional[_Union[UploadReplacement, _Mapping]] = ..., scope_id: _Optional[str] = ...) -> None: ...

class CreateUploadResponse(_message.Message):
    __slots__ = ("upload",)
    UPLOAD_FIELD_NUMBER: _ClassVar[int]
    upload: Upload
    def __init__(self, upload: _Optional[_Union[Upload, _Mapping]] = ...) -> None: ...

class GetUploadRequest(_message.Message):
    __slots__ = ("filesystem_id", "upload_id", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    upload_id: str
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., upload_id: _Optional[str] = ..., scope_id: _Optional[str] = ...) -> None: ...

class GetUploadResponse(_message.Message):
    __slots__ = ("upload",)
    UPLOAD_FIELD_NUMBER: _ClassVar[int]
    upload: Upload
    def __init__(self, upload: _Optional[_Union[Upload, _Mapping]] = ...) -> None: ...

class GetUploadPartsRequest(_message.Message):
    __slots__ = ("filesystem_id", "upload_id", "numbers", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    NUMBERS_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    upload_id: str
    numbers: _containers.RepeatedScalarFieldContainer[int]
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., upload_id: _Optional[str] = ..., numbers: _Optional[_Iterable[int]] = ..., scope_id: _Optional[str] = ...) -> None: ...

class UploadPart(_message.Message):
    __slots__ = ("part_number", "transfer")
    PART_NUMBER_FIELD_NUMBER: _ClassVar[int]
    TRANSFER_FIELD_NUMBER: _ClassVar[int]
    part_number: int
    transfer: SignedUpload
    def __init__(self, part_number: _Optional[int] = ..., transfer: _Optional[_Union[SignedUpload, _Mapping]] = ...) -> None: ...

class GetUploadPartsResponse(_message.Message):
    __slots__ = ("items",)
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[UploadPart]
    def __init__(self, items: _Optional[_Iterable[_Union[UploadPart, _Mapping]]] = ...) -> None: ...

class PartReceipt(_message.Message):
    __slots__ = ("part_number", "etag")
    PART_NUMBER_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    part_number: int
    etag: str
    def __init__(self, part_number: _Optional[int] = ..., etag: _Optional[str] = ...) -> None: ...

class CompleteUploadRequest(_message.Message):
    __slots__ = ("filesystem_id", "upload_id", "parts", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    PARTS_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    upload_id: str
    parts: _containers.RepeatedCompositeFieldContainer[PartReceipt]
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., upload_id: _Optional[str] = ..., parts: _Optional[_Iterable[_Union[PartReceipt, _Mapping]]] = ..., scope_id: _Optional[str] = ...) -> None: ...

class CompleteUploadResponse(_message.Message):
    __slots__ = ("publication",)
    PUBLICATION_FIELD_NUMBER: _ClassVar[int]
    publication: UploadPublication
    def __init__(self, publication: _Optional[_Union[UploadPublication, _Mapping]] = ...) -> None: ...

class AbortUploadRequest(_message.Message):
    __slots__ = ("filesystem_id", "upload_id", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    upload_id: str
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., upload_id: _Optional[str] = ..., scope_id: _Optional[str] = ...) -> None: ...

class AbortUploadResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class SearchFilters(_message.Message):
    __slots__ = ("parent", "semantic_type", "media_type", "created_after", "created_before", "updated_after", "updated_before")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    SEMANTIC_TYPE_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    CREATED_AFTER_FIELD_NUMBER: _ClassVar[int]
    CREATED_BEFORE_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AFTER_FIELD_NUMBER: _ClassVar[int]
    UPDATED_BEFORE_FIELD_NUMBER: _ClassVar[int]
    parent: Locator
    semantic_type: str
    media_type: str
    created_after: _timestamp_pb2.Timestamp
    created_before: _timestamp_pb2.Timestamp
    updated_after: _timestamp_pb2.Timestamp
    updated_before: _timestamp_pb2.Timestamp
    def __init__(self, parent: _Optional[_Union[Locator, _Mapping]] = ..., semantic_type: _Optional[str] = ..., media_type: _Optional[str] = ..., created_after: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., created_before: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., updated_after: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., updated_before: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class SearchFilesRequest(_message.Message):
    __slots__ = ("filesystem_id", "query", "filters", "limit", "cursor", "sort", "direction", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    FILTERS_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    SORT_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    query: str
    filters: SearchFilters
    limit: int
    cursor: str
    sort: str
    direction: str
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., query: _Optional[str] = ..., filters: _Optional[_Union[SearchFilters, _Mapping]] = ..., limit: _Optional[int] = ..., cursor: _Optional[str] = ..., sort: _Optional[str] = ..., direction: _Optional[str] = ..., scope_id: _Optional[str] = ...) -> None: ...

class Breadcrumb(_message.Message):
    __slots__ = ("node_id", "filename")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    filename: str
    def __init__(self, node_id: _Optional[str] = ..., filename: _Optional[str] = ...) -> None: ...

class SearchMatch(_message.Message):
    __slots__ = ("file_id", "breadcrumb", "snippet")
    FILE_ID_FIELD_NUMBER: _ClassVar[int]
    BREADCRUMB_FIELD_NUMBER: _ClassVar[int]
    SNIPPET_FIELD_NUMBER: _ClassVar[int]
    file_id: str
    breadcrumb: _containers.RepeatedCompositeFieldContainer[Breadcrumb]
    snippet: str
    def __init__(self, file_id: _Optional[str] = ..., breadcrumb: _Optional[_Iterable[_Union[Breadcrumb, _Mapping]]] = ..., snippet: _Optional[str] = ...) -> None: ...

class SearchResult(_message.Message):
    __slots__ = ("node", "path", "matched")
    NODE_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    MATCHED_FIELD_NUMBER: _ClassVar[int]
    node: Node
    path: str
    matched: SearchMatch
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ..., path: _Optional[str] = ..., matched: _Optional[_Union[SearchMatch, _Mapping]] = ...) -> None: ...

class SearchFilesResponse(_message.Message):
    __slots__ = ("items", "next_cursor", "degraded", "degraded_reason")
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    NEXT_CURSOR_FIELD_NUMBER: _ClassVar[int]
    DEGRADED_FIELD_NUMBER: _ClassVar[int]
    DEGRADED_REASON_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[SearchResult]
    next_cursor: str
    degraded: bool
    degraded_reason: str
    def __init__(self, items: _Optional[_Iterable[_Union[SearchResult, _Mapping]]] = ..., next_cursor: _Optional[str] = ..., degraded: _Optional[bool] = ..., degraded_reason: _Optional[str] = ...) -> None: ...

class SemanticSearchRequest(_message.Message):
    __slots__ = ("filesystem_id", "query", "filters", "limit", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    FILTERS_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    query: str
    filters: SearchFilters
    limit: int
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., query: _Optional[str] = ..., filters: _Optional[_Union[SearchFilters, _Mapping]] = ..., limit: _Optional[int] = ..., scope_id: _Optional[str] = ...) -> None: ...

class SemanticSearchResponse(_message.Message):
    __slots__ = ("items", "degraded", "degraded_reason")
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    DEGRADED_FIELD_NUMBER: _ClassVar[int]
    DEGRADED_REASON_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[SearchResult]
    degraded: bool
    degraded_reason: str
    def __init__(self, items: _Optional[_Iterable[_Union[SearchResult, _Mapping]]] = ..., degraded: _Optional[bool] = ..., degraded_reason: _Optional[str] = ...) -> None: ...

class ProcessingGeneration(_message.Message):
    __slots__ = ("file_id", "generation")
    FILE_ID_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    file_id: str
    generation: int
    def __init__(self, file_id: _Optional[str] = ..., generation: _Optional[int] = ...) -> None: ...

class OutputDescription(_message.Message):
    __slots__ = ("path", "storage", "size_bytes", "content_md5")
    PATH_FIELD_NUMBER: _ClassVar[int]
    STORAGE_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    CONTENT_MD5_FIELD_NUMBER: _ClassVar[int]
    path: str
    storage: str
    size_bytes: int
    content_md5: str
    def __init__(self, path: _Optional[str] = ..., storage: _Optional[str] = ..., size_bytes: _Optional[int] = ..., content_md5: _Optional[str] = ...) -> None: ...

class PrepareParseOutputRequest(_message.Message):
    __slots__ = ("source", "output")
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FIELD_NUMBER: _ClassVar[int]
    source: ProcessingGeneration
    output: OutputDescription
    def __init__(self, source: _Optional[_Union[ProcessingGeneration, _Mapping]] = ..., output: _Optional[_Union[OutputDescription, _Mapping]] = ...) -> None: ...

class PrepareParseOutputResponse(_message.Message):
    __slots__ = ("upload",)
    UPLOAD_FIELD_NUMBER: _ClassVar[int]
    upload: Upload
    def __init__(self, upload: _Optional[_Union[Upload, _Mapping]] = ...) -> None: ...

class CompleteParseRequest(_message.Message):
    __slots__ = ("source", "uploads", "directories")
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    UPLOADS_FIELD_NUMBER: _ClassVar[int]
    DIRECTORIES_FIELD_NUMBER: _ClassVar[int]
    source: ProcessingGeneration
    uploads: _containers.RepeatedScalarFieldContainer[str]
    directories: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, source: _Optional[_Union[ProcessingGeneration, _Mapping]] = ..., uploads: _Optional[_Iterable[str]] = ..., directories: _Optional[_Iterable[str]] = ...) -> None: ...

class CompleteParseResponse(_message.Message):
    __slots__ = ("source_id",)
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    source_id: str
    def __init__(self, source_id: _Optional[str] = ...) -> None: ...

class AbortParseRequest(_message.Message):
    __slots__ = ("source", "error_code")
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    source: ProcessingGeneration
    error_code: str
    def __init__(self, source: _Optional[_Union[ProcessingGeneration, _Mapping]] = ..., error_code: _Optional[str] = ...) -> None: ...

class AbortParseResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class InventoryNode(_message.Message):
    __slots__ = ("id", "parent_id", "path", "name", "kind", "size_bytes", "media_type", "title", "description", "context", "inline_content", "signed_url")
    ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    INLINE_CONTENT_FIELD_NUMBER: _ClassVar[int]
    SIGNED_URL_FIELD_NUMBER: _ClassVar[int]
    id: str
    parent_id: str
    path: str
    name: str
    kind: str
    size_bytes: int
    media_type: str
    title: str
    description: str
    context: str
    inline_content: bytes
    signed_url: str
    def __init__(self, id: _Optional[str] = ..., parent_id: _Optional[str] = ..., path: _Optional[str] = ..., name: _Optional[str] = ..., kind: _Optional[str] = ..., size_bytes: _Optional[int] = ..., media_type: _Optional[str] = ..., title: _Optional[str] = ..., description: _Optional[str] = ..., context: _Optional[str] = ..., inline_content: _Optional[bytes] = ..., signed_url: _Optional[str] = ...) -> None: ...

class PrepareEnrichmentRequest(_message.Message):
    __slots__ = ("source",)
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    source: ProcessingGeneration
    def __init__(self, source: _Optional[_Union[ProcessingGeneration, _Mapping]] = ...) -> None: ...

class EnrichmentInput(_message.Message):
    __slots__ = ("source_id", "nodes", "inline_limit_bytes", "multipart_threshold_bytes", "max_output_bytes")
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    NODES_FIELD_NUMBER: _ClassVar[int]
    INLINE_LIMIT_BYTES_FIELD_NUMBER: _ClassVar[int]
    MULTIPART_THRESHOLD_BYTES_FIELD_NUMBER: _ClassVar[int]
    MAX_OUTPUT_BYTES_FIELD_NUMBER: _ClassVar[int]
    source_id: str
    nodes: _containers.RepeatedCompositeFieldContainer[InventoryNode]
    inline_limit_bytes: int
    multipart_threshold_bytes: int
    max_output_bytes: int
    def __init__(self, source_id: _Optional[str] = ..., nodes: _Optional[_Iterable[_Union[InventoryNode, _Mapping]]] = ..., inline_limit_bytes: _Optional[int] = ..., multipart_threshold_bytes: _Optional[int] = ..., max_output_bytes: _Optional[int] = ...) -> None: ...

class EnrichmentComplete(_message.Message):
    __slots__ = ("source_id",)
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    source_id: str
    def __init__(self, source_id: _Optional[str] = ...) -> None: ...

class PrepareEnrichmentResponse(_message.Message):
    __slots__ = ("input", "complete")
    INPUT_FIELD_NUMBER: _ClassVar[int]
    COMPLETE_FIELD_NUMBER: _ClassVar[int]
    input: EnrichmentInput
    complete: EnrichmentComplete
    def __init__(self, input: _Optional[_Union[EnrichmentInput, _Mapping]] = ..., complete: _Optional[_Union[EnrichmentComplete, _Mapping]] = ...) -> None: ...

class PrepareEnrichmentOutputRequest(_message.Message):
    __slots__ = ("source", "output")
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    OUTPUT_FIELD_NUMBER: _ClassVar[int]
    source: ProcessingGeneration
    output: OutputDescription
    def __init__(self, source: _Optional[_Union[ProcessingGeneration, _Mapping]] = ..., output: _Optional[_Union[OutputDescription, _Mapping]] = ...) -> None: ...

class PrepareEnrichmentOutputResponse(_message.Message):
    __slots__ = ("upload",)
    UPLOAD_FIELD_NUMBER: _ClassVar[int]
    upload: Upload
    def __init__(self, upload: _Optional[_Union[Upload, _Mapping]] = ...) -> None: ...

class SemanticMetadata(_message.Message):
    __slots__ = ("title", "description", "semantic_type", "context")
    TITLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    SEMANTIC_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_FIELD_NUMBER: _ClassVar[int]
    title: str
    description: str
    semantic_type: str
    context: str
    def __init__(self, title: _Optional[str] = ..., description: _Optional[str] = ..., semantic_type: _Optional[str] = ..., context: _Optional[str] = ...) -> None: ...

class EnrichmentUpdate(_message.Message):
    __slots__ = ("id", "path", "metadata", "upload_id")
    ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    path: str
    metadata: SemanticMetadata
    upload_id: str
    def __init__(self, id: _Optional[str] = ..., path: _Optional[str] = ..., metadata: _Optional[_Union[SemanticMetadata, _Mapping]] = ..., upload_id: _Optional[str] = ...) -> None: ...

class CompleteEnrichmentRequest(_message.Message):
    __slots__ = ("source", "nodes")
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    NODES_FIELD_NUMBER: _ClassVar[int]
    source: ProcessingGeneration
    nodes: _containers.RepeatedCompositeFieldContainer[EnrichmentUpdate]
    def __init__(self, source: _Optional[_Union[ProcessingGeneration, _Mapping]] = ..., nodes: _Optional[_Iterable[_Union[EnrichmentUpdate, _Mapping]]] = ...) -> None: ...

class CompleteEnrichmentResponse(_message.Message):
    __slots__ = ("source_id",)
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    source_id: str
    def __init__(self, source_id: _Optional[str] = ...) -> None: ...

class FailEnrichmentRequest(_message.Message):
    __slots__ = ("source", "error_code")
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    source: ProcessingGeneration
    error_code: str
    def __init__(self, source: _Optional[_Union[ProcessingGeneration, _Mapping]] = ..., error_code: _Optional[str] = ...) -> None: ...

class FailEnrichmentResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class VectorSpace(_message.Message):
    __slots__ = ("model", "collection", "dimension")
    MODEL_FIELD_NUMBER: _ClassVar[int]
    COLLECTION_FIELD_NUMBER: _ClassVar[int]
    DIMENSION_FIELD_NUMBER: _ClassVar[int]
    model: str
    collection: str
    dimension: int
    def __init__(self, model: _Optional[str] = ..., collection: _Optional[str] = ..., dimension: _Optional[int] = ...) -> None: ...

class PrepareIndexRequest(_message.Message):
    __slots__ = ("source",)
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    source: ProcessingGeneration
    def __init__(self, source: _Optional[_Union[ProcessingGeneration, _Mapping]] = ...) -> None: ...

class IndexInput(_message.Message):
    __slots__ = ("filesystem_id", "source_id", "generation", "nodes", "vector_space", "max_output_bytes", "scope_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    NODES_FIELD_NUMBER: _ClassVar[int]
    VECTOR_SPACE_FIELD_NUMBER: _ClassVar[int]
    MAX_OUTPUT_BYTES_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    source_id: str
    generation: int
    nodes: _containers.RepeatedCompositeFieldContainer[InventoryNode]
    vector_space: VectorSpace
    max_output_bytes: int
    scope_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., source_id: _Optional[str] = ..., generation: _Optional[int] = ..., nodes: _Optional[_Iterable[_Union[InventoryNode, _Mapping]]] = ..., vector_space: _Optional[_Union[VectorSpace, _Mapping]] = ..., max_output_bytes: _Optional[int] = ..., scope_id: _Optional[str] = ...) -> None: ...

class IndexComplete(_message.Message):
    __slots__ = ("source_id",)
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    source_id: str
    def __init__(self, source_id: _Optional[str] = ...) -> None: ...

class PrepareIndexResponse(_message.Message):
    __slots__ = ("input", "complete")
    INPUT_FIELD_NUMBER: _ClassVar[int]
    COMPLETE_FIELD_NUMBER: _ClassVar[int]
    input: IndexInput
    complete: IndexComplete
    def __init__(self, input: _Optional[_Union[IndexInput, _Mapping]] = ..., complete: _Optional[_Union[IndexComplete, _Mapping]] = ...) -> None: ...

class CompleteIndexRequest(_message.Message):
    __slots__ = ("source",)
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    source: ProcessingGeneration
    def __init__(self, source: _Optional[_Union[ProcessingGeneration, _Mapping]] = ...) -> None: ...

class CompleteIndexResponse(_message.Message):
    __slots__ = ("source_id",)
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    source_id: str
    def __init__(self, source_id: _Optional[str] = ...) -> None: ...

class FailIndexRequest(_message.Message):
    __slots__ = ("source", "error_code")
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    source: ProcessingGeneration
    error_code: str
    def __init__(self, source: _Optional[_Union[ProcessingGeneration, _Mapping]] = ..., error_code: _Optional[str] = ...) -> None: ...

class FailIndexResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class OutputUploadScope(_message.Message):
    __slots__ = ("source", "stage", "upload_id")
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    source: ProcessingGeneration
    stage: str
    upload_id: str
    def __init__(self, source: _Optional[_Union[ProcessingGeneration, _Mapping]] = ..., stage: _Optional[str] = ..., upload_id: _Optional[str] = ...) -> None: ...

class GetOutputUploadRequest(_message.Message):
    __slots__ = ("scope",)
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    scope: OutputUploadScope
    def __init__(self, scope: _Optional[_Union[OutputUploadScope, _Mapping]] = ...) -> None: ...

class GetOutputUploadResponse(_message.Message):
    __slots__ = ("upload",)
    UPLOAD_FIELD_NUMBER: _ClassVar[int]
    upload: Upload
    def __init__(self, upload: _Optional[_Union[Upload, _Mapping]] = ...) -> None: ...

class GetOutputUploadPartsRequest(_message.Message):
    __slots__ = ("scope", "numbers")
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    NUMBERS_FIELD_NUMBER: _ClassVar[int]
    scope: OutputUploadScope
    numbers: _containers.RepeatedScalarFieldContainer[int]
    def __init__(self, scope: _Optional[_Union[OutputUploadScope, _Mapping]] = ..., numbers: _Optional[_Iterable[int]] = ...) -> None: ...

class GetOutputUploadPartsResponse(_message.Message):
    __slots__ = ("items",)
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[UploadPart]
    def __init__(self, items: _Optional[_Iterable[_Union[UploadPart, _Mapping]]] = ...) -> None: ...

class CompleteOutputUploadRequest(_message.Message):
    __slots__ = ("scope", "parts")
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    PARTS_FIELD_NUMBER: _ClassVar[int]
    scope: OutputUploadScope
    parts: _containers.RepeatedCompositeFieldContainer[PartReceipt]
    def __init__(self, scope: _Optional[_Union[OutputUploadScope, _Mapping]] = ..., parts: _Optional[_Iterable[_Union[PartReceipt, _Mapping]]] = ...) -> None: ...

class CompleteOutputUploadResponse(_message.Message):
    __slots__ = ("receipt",)
    RECEIPT_FIELD_NUMBER: _ClassVar[int]
    receipt: UploadReceipt
    def __init__(self, receipt: _Optional[_Union[UploadReceipt, _Mapping]] = ...) -> None: ...

class WriteOutputBytesRequest(_message.Message):
    __slots__ = ("scope", "content")
    SCOPE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    scope: OutputUploadScope
    content: bytes
    def __init__(self, scope: _Optional[_Union[OutputUploadScope, _Mapping]] = ..., content: _Optional[bytes] = ...) -> None: ...

class WriteOutputBytesResponse(_message.Message):
    __slots__ = ("receipt",)
    RECEIPT_FIELD_NUMBER: _ClassVar[int]
    receipt: UploadReceipt
    def __init__(self, receipt: _Optional[_Union[UploadReceipt, _Mapping]] = ...) -> None: ...

class Scope(_message.Message):
    __slots__ = ("id", "filesystem_id", "root_id", "state", "allow_blob_files", "allow_indexing")
    ID_FIELD_NUMBER: _ClassVar[int]
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    ROOT_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    ALLOW_BLOB_FILES_FIELD_NUMBER: _ClassVar[int]
    ALLOW_INDEXING_FIELD_NUMBER: _ClassVar[int]
    id: str
    filesystem_id: str
    root_id: str
    state: str
    allow_blob_files: bool
    allow_indexing: bool
    def __init__(self, id: _Optional[str] = ..., filesystem_id: _Optional[str] = ..., root_id: _Optional[str] = ..., state: _Optional[str] = ..., allow_blob_files: _Optional[bool] = ..., allow_indexing: _Optional[bool] = ...) -> None: ...

class CreateScopesRequest(_message.Message):
    __slots__ = ("filesystem_id", "scope_ids", "idempotency_key", "allow_blob_files", "allow_indexing")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_IDS_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    ALLOW_BLOB_FILES_FIELD_NUMBER: _ClassVar[int]
    ALLOW_INDEXING_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    scope_ids: _containers.RepeatedScalarFieldContainer[str]
    idempotency_key: str
    allow_blob_files: bool
    allow_indexing: bool
    def __init__(self, filesystem_id: _Optional[str] = ..., scope_ids: _Optional[_Iterable[str]] = ..., idempotency_key: _Optional[str] = ..., allow_blob_files: _Optional[bool] = ..., allow_indexing: _Optional[bool] = ...) -> None: ...

class CreateScopesResponse(_message.Message):
    __slots__ = ("scopes",)
    SCOPES_FIELD_NUMBER: _ClassVar[int]
    scopes: _containers.RepeatedCompositeFieldContainer[Scope]
    def __init__(self, scopes: _Optional[_Iterable[_Union[Scope, _Mapping]]] = ...) -> None: ...

class ListScopesRequest(_message.Message):
    __slots__ = ("filesystem_id", "cursor", "limit")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    cursor: str
    limit: int
    def __init__(self, filesystem_id: _Optional[str] = ..., cursor: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class ListScopesResponse(_message.Message):
    __slots__ = ("scopes", "next_cursor")
    SCOPES_FIELD_NUMBER: _ClassVar[int]
    NEXT_CURSOR_FIELD_NUMBER: _ClassVar[int]
    scopes: _containers.RepeatedCompositeFieldContainer[Scope]
    next_cursor: str
    def __init__(self, scopes: _Optional[_Iterable[_Union[Scope, _Mapping]]] = ..., next_cursor: _Optional[str] = ...) -> None: ...
