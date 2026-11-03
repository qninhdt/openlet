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

class CreateStorageRequest(_message.Message):
    __slots__ = ("bucket", "filesystem")
    BUCKET_FIELD_NUMBER: _ClassVar[int]
    FILESYSTEM_FIELD_NUMBER: _ClassVar[int]
    bucket: CreateBucketRequest
    filesystem: CreateFilesystemRequest
    def __init__(self, bucket: _Optional[_Union[CreateBucketRequest, _Mapping]] = ..., filesystem: _Optional[_Union[CreateFilesystemRequest, _Mapping]] = ...) -> None: ...

class CreateStorageResponse(_message.Message):
    __slots__ = ("bucket", "filesystem")
    BUCKET_FIELD_NUMBER: _ClassVar[int]
    FILESYSTEM_FIELD_NUMBER: _ClassVar[int]
    bucket: Bucket
    filesystem: Filesystem
    def __init__(self, bucket: _Optional[_Union[Bucket, _Mapping]] = ..., filesystem: _Optional[_Union[Filesystem, _Mapping]] = ...) -> None: ...

class Node(_message.Message):
    __slots__ = ("id", "filesystem_id", "parent_id", "name", "kind", "revision", "size_bytes", "media_type", "created_at", "updated_at", "title", "description", "semantic_type", "context")
    ID_FIELD_NUMBER: _ClassVar[int]
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
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
    id: str
    filesystem_id: str
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
    def __init__(self, id: _Optional[str] = ..., filesystem_id: _Optional[str] = ..., parent_id: _Optional[str] = ..., name: _Optional[str] = ..., kind: _Optional[str] = ..., revision: _Optional[int] = ..., size_bytes: _Optional[int] = ..., media_type: _Optional[str] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., updated_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., title: _Optional[str] = ..., description: _Optional[str] = ..., semantic_type: _Optional[str] = ..., context: _Optional[str] = ...) -> None: ...

class GetNodeRequest(_message.Message):
    __slots__ = ("filesystem_id", "node_id", "path_context")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    node_id: str
    path_context: PathContext
    def __init__(self, filesystem_id: _Optional[str] = ..., node_id: _Optional[str] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ...) -> None: ...

class GetNodeResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class GetDownloadRequest(_message.Message):
    __slots__ = ("filesystem_id", "node_id", "revision", "path_context")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    node_id: str
    revision: int
    path_context: PathContext
    def __init__(self, filesystem_id: _Optional[str] = ..., node_id: _Optional[str] = ..., revision: _Optional[int] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ...) -> None: ...

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
    __slots__ = ("filesystem_id", "node_id", "path_context")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    node_id: str
    path_context: PathContext
    def __init__(self, filesystem_id: _Optional[str] = ..., node_id: _Optional[str] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ...) -> None: ...

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

class CreateBucketRequest(_message.Message):
    __slots__ = ("bucket_id", "idempotency_key", "limit_bytes")
    BUCKET_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    LIMIT_BYTES_FIELD_NUMBER: _ClassVar[int]
    bucket_id: str
    idempotency_key: str
    limit_bytes: int
    def __init__(self, bucket_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., limit_bytes: _Optional[int] = ...) -> None: ...

class Bucket(_message.Message):
    __slots__ = ("id", "limit_bytes", "used_bytes", "state")
    ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_BYTES_FIELD_NUMBER: _ClassVar[int]
    USED_BYTES_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    id: str
    limit_bytes: int
    used_bytes: int
    state: str
    def __init__(self, id: _Optional[str] = ..., limit_bytes: _Optional[int] = ..., used_bytes: _Optional[int] = ..., state: _Optional[str] = ...) -> None: ...

class CreateBucketResponse(_message.Message):
    __slots__ = ("bucket",)
    BUCKET_FIELD_NUMBER: _ClassVar[int]
    bucket: Bucket
    def __init__(self, bucket: _Optional[_Union[Bucket, _Mapping]] = ...) -> None: ...

class CreateFilesystemRequest(_message.Message):
    __slots__ = ("filesystem_id", "bucket_id", "idempotency_key", "root_name")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    BUCKET_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    ROOT_NAME_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    bucket_id: str
    idempotency_key: str
    root_name: str
    def __init__(self, filesystem_id: _Optional[str] = ..., bucket_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., root_name: _Optional[str] = ...) -> None: ...

class Filesystem(_message.Message):
    __slots__ = ("id", "bucket_id", "root_id", "state")
    ID_FIELD_NUMBER: _ClassVar[int]
    BUCKET_ID_FIELD_NUMBER: _ClassVar[int]
    ROOT_ID_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    id: str
    bucket_id: str
    root_id: str
    state: str
    def __init__(self, id: _Optional[str] = ..., bucket_id: _Optional[str] = ..., root_id: _Optional[str] = ..., state: _Optional[str] = ...) -> None: ...

class CreateFilesystemResponse(_message.Message):
    __slots__ = ("filesystem",)
    FILESYSTEM_FIELD_NUMBER: _ClassVar[int]
    filesystem: Filesystem
    def __init__(self, filesystem: _Optional[_Union[Filesystem, _Mapping]] = ...) -> None: ...

class FreezeBucketRequest(_message.Message):
    __slots__ = ("bucket_id", "idempotency_key")
    BUCKET_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    bucket_id: str
    idempotency_key: str
    def __init__(self, bucket_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ...) -> None: ...

class FreezeBucketResponse(_message.Message):
    __slots__ = ("bucket",)
    BUCKET_FIELD_NUMBER: _ClassVar[int]
    bucket: Bucket
    def __init__(self, bucket: _Optional[_Union[Bucket, _Mapping]] = ...) -> None: ...

class ListBucketFilesystemsRequest(_message.Message):
    __slots__ = ("bucket_id", "after_id")
    BUCKET_ID_FIELD_NUMBER: _ClassVar[int]
    AFTER_ID_FIELD_NUMBER: _ClassVar[int]
    bucket_id: str
    after_id: str
    def __init__(self, bucket_id: _Optional[str] = ..., after_id: _Optional[str] = ...) -> None: ...

class ListBucketFilesystemsResponse(_message.Message):
    __slots__ = ("filesystem_ids",)
    FILESYSTEM_IDS_FIELD_NUMBER: _ClassVar[int]
    filesystem_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, filesystem_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class CompleteBucketDeletionRequest(_message.Message):
    __slots__ = ("bucket_id", "idempotency_key")
    BUCKET_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    bucket_id: str
    idempotency_key: str
    def __init__(self, bucket_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ...) -> None: ...

class CompleteBucketDeletionResponse(_message.Message):
    __slots__ = ("bucket",)
    BUCKET_FIELD_NUMBER: _ClassVar[int]
    bucket: Bucket
    def __init__(self, bucket: _Optional[_Union[Bucket, _Mapping]] = ...) -> None: ...

class ReleaseProvisioningRequest(_message.Message):
    __slots__ = ("bucket_id", "filesystem_id", "root_id")
    BUCKET_ID_FIELD_NUMBER: _ClassVar[int]
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    ROOT_ID_FIELD_NUMBER: _ClassVar[int]
    bucket_id: str
    filesystem_id: str
    root_id: str
    def __init__(self, bucket_id: _Optional[str] = ..., filesystem_id: _Optional[str] = ..., root_id: _Optional[str] = ...) -> None: ...

class ReleaseProvisioningResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Mount(_message.Message):
    __slots__ = ("path", "filesystem_id")
    PATH_FIELD_NUMBER: _ClassVar[int]
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    path: str
    filesystem_id: str
    def __init__(self, path: _Optional[str] = ..., filesystem_id: _Optional[str] = ...) -> None: ...

class PathContext(_message.Message):
    __slots__ = ("mounts",)
    MOUNTS_FIELD_NUMBER: _ClassVar[int]
    mounts: _containers.RepeatedCompositeFieldContainer[Mount]
    def __init__(self, mounts: _Optional[_Iterable[_Union[Mount, _Mapping]]] = ...) -> None: ...

class PathLocator(_message.Message):
    __slots__ = ("path", "cwd_id")
    PATH_FIELD_NUMBER: _ClassVar[int]
    CWD_ID_FIELD_NUMBER: _ClassVar[int]
    path: str
    cwd_id: str
    def __init__(self, path: _Optional[str] = ..., cwd_id: _Optional[str] = ...) -> None: ...

class Locator(_message.Message):
    __slots__ = ("node_id", "path", "expected_node_id", "expected_parent_id")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_NODE_ID_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    path: PathLocator
    expected_node_id: str
    expected_parent_id: str
    def __init__(self, node_id: _Optional[str] = ..., path: _Optional[_Union[PathLocator, _Mapping]] = ..., expected_node_id: _Optional[str] = ..., expected_parent_id: _Optional[str] = ...) -> None: ...

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

class GetBucketUsageRequest(_message.Message):
    __slots__ = ("bucket_id",)
    BUCKET_ID_FIELD_NUMBER: _ClassVar[int]
    bucket_id: str
    def __init__(self, bucket_id: _Optional[str] = ...) -> None: ...

class UploadLimits(_message.Message):
    __slots__ = ("inline_limit_bytes", "max_file_bytes", "multipart_threshold_bytes", "multipart_part_bytes")
    INLINE_LIMIT_BYTES_FIELD_NUMBER: _ClassVar[int]
    MAX_FILE_BYTES_FIELD_NUMBER: _ClassVar[int]
    MULTIPART_THRESHOLD_BYTES_FIELD_NUMBER: _ClassVar[int]
    MULTIPART_PART_BYTES_FIELD_NUMBER: _ClassVar[int]
    inline_limit_bytes: int
    max_file_bytes: int
    multipart_threshold_bytes: int
    multipart_part_bytes: int
    def __init__(self, inline_limit_bytes: _Optional[int] = ..., max_file_bytes: _Optional[int] = ..., multipart_threshold_bytes: _Optional[int] = ..., multipart_part_bytes: _Optional[int] = ...) -> None: ...

class GetBucketUsageResponse(_message.Message):
    __slots__ = ("bucket", "upload_limits")
    BUCKET_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_LIMITS_FIELD_NUMBER: _ClassVar[int]
    bucket: Bucket
    upload_limits: UploadLimits
    def __init__(self, bucket: _Optional[_Union[Bucket, _Mapping]] = ..., upload_limits: _Optional[_Union[UploadLimits, _Mapping]] = ...) -> None: ...

class DirectoryCreation(_message.Message):
    __slots__ = ("parent", "name")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    parent: Locator
    name: str
    def __init__(self, parent: _Optional[_Union[Locator, _Mapping]] = ..., name: _Optional[str] = ...) -> None: ...

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
    __slots__ = ("filesystem_id", "idempotency_key", "path_context", "directory", "file")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    DIRECTORY_FIELD_NUMBER: _ClassVar[int]
    FILE_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    idempotency_key: str
    path_context: PathContext
    directory: DirectoryCreation
    file: InlineFileCreation
    def __init__(self, filesystem_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ..., directory: _Optional[_Union[DirectoryCreation, _Mapping]] = ..., file: _Optional[_Union[InlineFileCreation, _Mapping]] = ...) -> None: ...

class CreateNodeResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class ListNodesRequest(_message.Message):
    __slots__ = ("filesystem_id", "parent", "path_context", "limit", "cursor")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    parent: Locator
    path_context: PathContext
    limit: int
    cursor: str
    def __init__(self, filesystem_id: _Optional[str] = ..., parent: _Optional[_Union[Locator, _Mapping]] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ..., limit: _Optional[int] = ..., cursor: _Optional[str] = ...) -> None: ...

class ListNodesResponse(_message.Message):
    __slots__ = ("items", "next_cursor")
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    NEXT_CURSOR_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[Node]
    next_cursor: str
    def __init__(self, items: _Optional[_Iterable[_Union[Node, _Mapping]]] = ..., next_cursor: _Optional[str] = ...) -> None: ...

class ResolveNodeRequest(_message.Message):
    __slots__ = ("filesystem_id", "locator", "path_context")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    locator: Locator
    path_context: PathContext
    def __init__(self, filesystem_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ...) -> None: ...

class ResolveNodeResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class BatchStatRequest(_message.Message):
    __slots__ = ("filesystem_id", "locators", "path_context")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATORS_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    locators: _containers.RepeatedCompositeFieldContainer[Locator]
    path_context: PathContext
    def __init__(self, filesystem_id: _Optional[str] = ..., locators: _Optional[_Iterable[_Union[Locator, _Mapping]]] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ...) -> None: ...

class BatchStatResponse(_message.Message):
    __slots__ = ("items",)
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[Node]
    def __init__(self, items: _Optional[_Iterable[_Union[Node, _Mapping]]] = ...) -> None: ...

class UpdateNodeRequest(_message.Message):
    __slots__ = ("filesystem_id", "locator", "path_context", "revision", "name", "parent")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    PARENT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    locator: Locator
    path_context: PathContext
    revision: int
    name: str
    parent: Locator
    def __init__(self, filesystem_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ..., revision: _Optional[int] = ..., name: _Optional[str] = ..., parent: _Optional[_Union[Locator, _Mapping]] = ...) -> None: ...

class UpdateNodeResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class ReplaceContentRequest(_message.Message):
    __slots__ = ("filesystem_id", "locator", "path_context", "revision", "content", "media_type")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    locator: Locator
    path_context: PathContext
    revision: int
    content: bytes
    media_type: str
    def __init__(self, filesystem_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ..., revision: _Optional[int] = ..., content: _Optional[bytes] = ..., media_type: _Optional[str] = ...) -> None: ...

class ReplaceContentResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class Copy(_message.Message):
    __slots__ = ("id", "destination_root_id", "status", "committed_nodes", "committed_bytes", "error_code")
    ID_FIELD_NUMBER: _ClassVar[int]
    DESTINATION_ROOT_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    COMMITTED_NODES_FIELD_NUMBER: _ClassVar[int]
    COMMITTED_BYTES_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    id: str
    destination_root_id: str
    status: str
    committed_nodes: int
    committed_bytes: int
    error_code: str
    def __init__(self, id: _Optional[str] = ..., destination_root_id: _Optional[str] = ..., status: _Optional[str] = ..., committed_nodes: _Optional[int] = ..., committed_bytes: _Optional[int] = ..., error_code: _Optional[str] = ...) -> None: ...

class CreateCopyRequest(_message.Message):
    __slots__ = ("filesystem_id", "source_id", "parent_id", "name", "revision", "idempotency_key", "path_context")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    source_id: str
    parent_id: str
    name: str
    revision: int
    idempotency_key: str
    path_context: PathContext
    def __init__(self, filesystem_id: _Optional[str] = ..., source_id: _Optional[str] = ..., parent_id: _Optional[str] = ..., name: _Optional[str] = ..., revision: _Optional[int] = ..., idempotency_key: _Optional[str] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ...) -> None: ...

class CreateCopyResponse(_message.Message):
    __slots__ = ("copy",)
    COPY_FIELD_NUMBER: _ClassVar[int]
    copy: Copy
    def __init__(self, copy: _Optional[_Union[Copy, _Mapping]] = ...) -> None: ...

class GetCopyRequest(_message.Message):
    __slots__ = ("filesystem_id", "copy_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    COPY_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    copy_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., copy_id: _Optional[str] = ...) -> None: ...

class GetCopyResponse(_message.Message):
    __slots__ = ("copy",)
    COPY_FIELD_NUMBER: _ClassVar[int]
    copy: Copy
    def __init__(self, copy: _Optional[_Union[Copy, _Mapping]] = ...) -> None: ...

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
    __slots__ = ("filesystem_id", "node_id", "path_context")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    node_id: str
    path_context: PathContext
    def __init__(self, filesystem_id: _Optional[str] = ..., node_id: _Optional[str] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ...) -> None: ...

class GetProcessingResponse(_message.Message):
    __slots__ = ("processing",)
    PROCESSING_FIELD_NUMBER: _ClassVar[int]
    processing: Processing
    def __init__(self, processing: _Optional[_Union[Processing, _Mapping]] = ...) -> None: ...

class ReprocessNodeRequest(_message.Message):
    __slots__ = ("filesystem_id", "node_id", "idempotency_key", "path_context")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    node_id: str
    idempotency_key: str
    path_context: PathContext
    def __init__(self, filesystem_id: _Optional[str] = ..., node_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ...) -> None: ...

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
    __slots__ = ("id", "node_id", "parent_id", "name", "actor_id", "status", "created_at")
    ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    ACTOR_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    id: str
    node_id: str
    parent_id: str
    name: str
    actor_id: str
    status: str
    created_at: _timestamp_pb2.Timestamp
    def __init__(self, id: _Optional[str] = ..., node_id: _Optional[str] = ..., parent_id: _Optional[str] = ..., name: _Optional[str] = ..., actor_id: _Optional[str] = ..., status: _Optional[str] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class TrashNodeRequest(_message.Message):
    __slots__ = ("filesystem_id", "locator", "path_context", "revision")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    LOCATOR_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    locator: Locator
    path_context: PathContext
    revision: int
    def __init__(self, filesystem_id: _Optional[str] = ..., locator: _Optional[_Union[Locator, _Mapping]] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ..., revision: _Optional[int] = ...) -> None: ...

class TrashNodeResponse(_message.Message):
    __slots__ = ("entry",)
    ENTRY_FIELD_NUMBER: _ClassVar[int]
    entry: TrashEntry
    def __init__(self, entry: _Optional[_Union[TrashEntry, _Mapping]] = ...) -> None: ...

class ListTrashRequest(_message.Message):
    __slots__ = ("filesystem_id", "limit", "cursor")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    limit: int
    cursor: str
    def __init__(self, filesystem_id: _Optional[str] = ..., limit: _Optional[int] = ..., cursor: _Optional[str] = ...) -> None: ...

class ListTrashResponse(_message.Message):
    __slots__ = ("items", "next_cursor")
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    NEXT_CURSOR_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[TrashEntry]
    next_cursor: str
    def __init__(self, items: _Optional[_Iterable[_Union[TrashEntry, _Mapping]]] = ..., next_cursor: _Optional[str] = ...) -> None: ...

class GetTrashRequest(_message.Message):
    __slots__ = ("filesystem_id", "entry_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    ENTRY_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    entry_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., entry_id: _Optional[str] = ...) -> None: ...

class GetTrashResponse(_message.Message):
    __slots__ = ("entry",)
    ENTRY_FIELD_NUMBER: _ClassVar[int]
    entry: TrashEntry
    def __init__(self, entry: _Optional[_Union[TrashEntry, _Mapping]] = ...) -> None: ...

class RestoreTrashRequest(_message.Message):
    __slots__ = ("filesystem_id", "entry_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    ENTRY_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    entry_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., entry_id: _Optional[str] = ...) -> None: ...

class RestoreTrashResponse(_message.Message):
    __slots__ = ("node",)
    NODE_FIELD_NUMBER: _ClassVar[int]
    node: Node
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class PurgeTrashRequest(_message.Message):
    __slots__ = ("filesystem_id", "entry_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    ENTRY_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    entry_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., entry_id: _Optional[str] = ...) -> None: ...

class PurgeTrashResponse(_message.Message):
    __slots__ = ("entry",)
    ENTRY_FIELD_NUMBER: _ClassVar[int]
    entry: TrashEntry
    def __init__(self, entry: _Optional[_Union[TrashEntry, _Mapping]] = ...) -> None: ...

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
    __slots__ = ("filesystem_id", "idempotency_key", "path_context", "size_bytes", "media_type", "content_md5", "destination", "replacement")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_MD5_FIELD_NUMBER: _ClassVar[int]
    DESTINATION_FIELD_NUMBER: _ClassVar[int]
    REPLACEMENT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    idempotency_key: str
    path_context: PathContext
    size_bytes: int
    media_type: str
    content_md5: str
    destination: UploadDestination
    replacement: UploadReplacement
    def __init__(self, filesystem_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ..., size_bytes: _Optional[int] = ..., media_type: _Optional[str] = ..., content_md5: _Optional[str] = ..., destination: _Optional[_Union[UploadDestination, _Mapping]] = ..., replacement: _Optional[_Union[UploadReplacement, _Mapping]] = ...) -> None: ...

class CreateUploadResponse(_message.Message):
    __slots__ = ("upload",)
    UPLOAD_FIELD_NUMBER: _ClassVar[int]
    upload: Upload
    def __init__(self, upload: _Optional[_Union[Upload, _Mapping]] = ...) -> None: ...

class GetUploadRequest(_message.Message):
    __slots__ = ("filesystem_id", "upload_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    upload_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., upload_id: _Optional[str] = ...) -> None: ...

class GetUploadResponse(_message.Message):
    __slots__ = ("upload",)
    UPLOAD_FIELD_NUMBER: _ClassVar[int]
    upload: Upload
    def __init__(self, upload: _Optional[_Union[Upload, _Mapping]] = ...) -> None: ...

class GetUploadPartsRequest(_message.Message):
    __slots__ = ("filesystem_id", "upload_id", "numbers")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    NUMBERS_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    upload_id: str
    numbers: _containers.RepeatedScalarFieldContainer[int]
    def __init__(self, filesystem_id: _Optional[str] = ..., upload_id: _Optional[str] = ..., numbers: _Optional[_Iterable[int]] = ...) -> None: ...

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
    __slots__ = ("filesystem_id", "upload_id", "parts")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    PARTS_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    upload_id: str
    parts: _containers.RepeatedCompositeFieldContainer[PartReceipt]
    def __init__(self, filesystem_id: _Optional[str] = ..., upload_id: _Optional[str] = ..., parts: _Optional[_Iterable[_Union[PartReceipt, _Mapping]]] = ...) -> None: ...

class CompleteUploadResponse(_message.Message):
    __slots__ = ("publication",)
    PUBLICATION_FIELD_NUMBER: _ClassVar[int]
    publication: UploadPublication
    def __init__(self, publication: _Optional[_Union[UploadPublication, _Mapping]] = ...) -> None: ...

class AbortUploadRequest(_message.Message):
    __slots__ = ("filesystem_id", "upload_id")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    upload_id: str
    def __init__(self, filesystem_id: _Optional[str] = ..., upload_id: _Optional[str] = ...) -> None: ...

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
    __slots__ = ("filesystem_id", "query", "filters", "limit", "cursor", "sort", "direction", "path_context")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    FILTERS_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    SORT_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    query: str
    filters: SearchFilters
    limit: int
    cursor: str
    sort: str
    direction: str
    path_context: PathContext
    def __init__(self, filesystem_id: _Optional[str] = ..., query: _Optional[str] = ..., filters: _Optional[_Union[SearchFilters, _Mapping]] = ..., limit: _Optional[int] = ..., cursor: _Optional[str] = ..., sort: _Optional[str] = ..., direction: _Optional[str] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ...) -> None: ...

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
    __slots__ = ("filesystem_id", "query", "filters", "limit", "cursor", "path_context")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    FILTERS_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    PATH_CONTEXT_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    query: str
    filters: SearchFilters
    limit: int
    cursor: str
    path_context: PathContext
    def __init__(self, filesystem_id: _Optional[str] = ..., query: _Optional[str] = ..., filters: _Optional[_Union[SearchFilters, _Mapping]] = ..., limit: _Optional[int] = ..., cursor: _Optional[str] = ..., path_context: _Optional[_Union[PathContext, _Mapping]] = ...) -> None: ...

class SemanticSearchResponse(_message.Message):
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
    __slots__ = ("filesystem_id", "source_id", "generation", "nodes", "vector_space", "max_output_bytes")
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_ID_FIELD_NUMBER: _ClassVar[int]
    GENERATION_FIELD_NUMBER: _ClassVar[int]
    NODES_FIELD_NUMBER: _ClassVar[int]
    VECTOR_SPACE_FIELD_NUMBER: _ClassVar[int]
    MAX_OUTPUT_BYTES_FIELD_NUMBER: _ClassVar[int]
    filesystem_id: str
    source_id: str
    generation: int
    nodes: _containers.RepeatedCompositeFieldContainer[InventoryNode]
    vector_space: VectorSpace
    max_output_bytes: int
    def __init__(self, filesystem_id: _Optional[str] = ..., source_id: _Optional[str] = ..., generation: _Optional[int] = ..., nodes: _Optional[_Iterable[_Union[InventoryNode, _Mapping]]] = ..., vector_space: _Optional[_Union[VectorSpace, _Mapping]] = ..., max_output_bytes: _Optional[int] = ...) -> None: ...

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
