import datetime

from google.api import annotations_pb2 as _annotations_pb2
from google.api import httpbody_pb2 as _httpbody_pb2
from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.rpc import status_pb2 as _status_pb2
from buf.validate import validate_pb2 as _validate_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class StorageVisibility(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STORAGE_VISIBILITY_UNSPECIFIED: _ClassVar[StorageVisibility]
    STORAGE_VISIBILITY_PRIVATE: _ClassVar[StorageVisibility]
    STORAGE_VISIBILITY_PUBLIC: _ClassVar[StorageVisibility]

class StorageRole(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STORAGE_ROLE_UNSPECIFIED: _ClassVar[StorageRole]
    STORAGE_ROLE_OWNER: _ClassVar[StorageRole]
    STORAGE_ROLE_EDITOR: _ClassVar[StorageRole]
    STORAGE_ROLE_VIEWER: _ClassVar[StorageRole]

class NodeKind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    NODE_KIND_UNSPECIFIED: _ClassVar[NodeKind]
    NODE_KIND_DIRECTORY: _ClassVar[NodeKind]
    NODE_KIND_FILE: _ClassVar[NodeKind]

class FileType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    FILE_TYPE_UNSPECIFIED: _ClassVar[FileType]
    FILE_TYPE_TEXT: _ClassVar[FileType]
    FILE_TYPE_BLOB: _ClassVar[FileType]
STORAGE_VISIBILITY_UNSPECIFIED: StorageVisibility
STORAGE_VISIBILITY_PRIVATE: StorageVisibility
STORAGE_VISIBILITY_PUBLIC: StorageVisibility
STORAGE_ROLE_UNSPECIFIED: StorageRole
STORAGE_ROLE_OWNER: StorageRole
STORAGE_ROLE_EDITOR: StorageRole
STORAGE_ROLE_VIEWER: StorageRole
NODE_KIND_UNSPECIFIED: NodeKind
NODE_KIND_DIRECTORY: NodeKind
NODE_KIND_FILE: NodeKind
FILE_TYPE_UNSPECIFIED: FileType
FILE_TYPE_TEXT: FileType
FILE_TYPE_BLOB: FileType

class ActorRef(_message.Message):
    __slots__ = ("user_id", "agent_id")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    agent_id: str
    def __init__(self, user_id: _Optional[str] = ..., agent_id: _Optional[str] = ...) -> None: ...

class StorageOwnership(_message.Message):
    __slots__ = ("user_id", "agent_id", "workspace_id", "conversation_id")
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    user_id: str
    agent_id: str
    workspace_id: str
    conversation_id: str
    def __init__(self, user_id: _Optional[str] = ..., agent_id: _Optional[str] = ..., workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ...) -> None: ...

class StorageCapabilities(_message.Message):
    __slots__ = ("read", "write", "manage_access")
    READ_FIELD_NUMBER: _ClassVar[int]
    WRITE_FIELD_NUMBER: _ClassVar[int]
    MANAGE_ACCESS_FIELD_NUMBER: _ClassVar[int]
    read: bool
    write: bool
    manage_access: bool
    def __init__(self, read: _Optional[bool] = ..., write: _Optional[bool] = ..., manage_access: _Optional[bool] = ...) -> None: ...

class Storage(_message.Message):
    __slots__ = ("id", "workspace_id", "name", "visibility", "root_node_id", "allow_blob_files", "allow_indexing", "capabilities")
    ID_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    VISIBILITY_FIELD_NUMBER: _ClassVar[int]
    ROOT_NODE_ID_FIELD_NUMBER: _ClassVar[int]
    ALLOW_BLOB_FILES_FIELD_NUMBER: _ClassVar[int]
    ALLOW_INDEXING_FIELD_NUMBER: _ClassVar[int]
    CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    id: str
    workspace_id: str
    name: str
    visibility: StorageVisibility
    root_node_id: str
    allow_blob_files: bool
    allow_indexing: bool
    capabilities: StorageCapabilities
    def __init__(self, id: _Optional[str] = ..., workspace_id: _Optional[str] = ..., name: _Optional[str] = ..., visibility: _Optional[_Union[StorageVisibility, str]] = ..., root_node_id: _Optional[str] = ..., allow_blob_files: _Optional[bool] = ..., allow_indexing: _Optional[bool] = ..., capabilities: _Optional[_Union[StorageCapabilities, _Mapping]] = ...) -> None: ...

class WorkspaceStorage(_message.Message):
    __slots__ = ("workspace_id", "quota_bytes", "used_bytes")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    QUOTA_BYTES_FIELD_NUMBER: _ClassVar[int]
    USED_BYTES_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    quota_bytes: int
    used_bytes: int
    def __init__(self, workspace_id: _Optional[str] = ..., quota_bytes: _Optional[int] = ..., used_bytes: _Optional[int] = ...) -> None: ...

class AccessGrant(_message.Message):
    __slots__ = ("actor", "role")
    ACTOR_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    actor: ActorRef
    role: StorageRole
    def __init__(self, actor: _Optional[_Union[ActorRef, _Mapping]] = ..., role: _Optional[_Union[StorageRole, str]] = ...) -> None: ...

class StorageAccess(_message.Message):
    __slots__ = ("ownership", "grants", "visibility")
    OWNERSHIP_FIELD_NUMBER: _ClassVar[int]
    GRANTS_FIELD_NUMBER: _ClassVar[int]
    VISIBILITY_FIELD_NUMBER: _ClassVar[int]
    ownership: StorageOwnership
    grants: _containers.RepeatedCompositeFieldContainer[AccessGrant]
    visibility: StorageVisibility
    def __init__(self, ownership: _Optional[_Union[StorageOwnership, _Mapping]] = ..., grants: _Optional[_Iterable[_Union[AccessGrant, _Mapping]]] = ..., visibility: _Optional[_Union[StorageVisibility, str]] = ...) -> None: ...

class NodeLocator(_message.Message):
    __slots__ = ("node_id", "path", "root_node_id", "cwd_node_id")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    ROOT_NODE_ID_FIELD_NUMBER: _ClassVar[int]
    CWD_NODE_ID_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    path: str
    root_node_id: str
    cwd_node_id: str
    def __init__(self, node_id: _Optional[str] = ..., path: _Optional[str] = ..., root_node_id: _Optional[str] = ..., cwd_node_id: _Optional[str] = ...) -> None: ...

class FileMetadata(_message.Message):
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

class ProcessingSummary(_message.Message):
    __slots__ = ("stage", "error_code")
    STAGE_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    stage: str
    error_code: str
    def __init__(self, stage: _Optional[str] = ..., error_code: _Optional[str] = ...) -> None: ...

class FileHeader(_message.Message):
    __slots__ = ("type", "version", "size_bytes", "media_type", "metadata", "processing")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    PROCESSING_FIELD_NUMBER: _ClassVar[int]
    type: FileType
    version: int
    size_bytes: int
    media_type: str
    metadata: FileMetadata
    processing: ProcessingSummary
    def __init__(self, type: _Optional[_Union[FileType, str]] = ..., version: _Optional[int] = ..., size_bytes: _Optional[int] = ..., media_type: _Optional[str] = ..., metadata: _Optional[_Union[FileMetadata, _Mapping]] = ..., processing: _Optional[_Union[ProcessingSummary, _Mapping]] = ...) -> None: ...

class Node(_message.Message):
    __slots__ = ("id", "storage_id", "parent_id", "name", "kind", "created_at", "updated_at", "readonly", "file")
    ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    UPDATED_AT_FIELD_NUMBER: _ClassVar[int]
    READONLY_FIELD_NUMBER: _ClassVar[int]
    FILE_FIELD_NUMBER: _ClassVar[int]
    id: str
    storage_id: str
    parent_id: str
    name: str
    kind: NodeKind
    created_at: _timestamp_pb2.Timestamp
    updated_at: _timestamp_pb2.Timestamp
    readonly: bool
    file: FileHeader
    def __init__(self, id: _Optional[str] = ..., storage_id: _Optional[str] = ..., parent_id: _Optional[str] = ..., name: _Optional[str] = ..., kind: _Optional[_Union[NodeKind, str]] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., updated_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., readonly: _Optional[bool] = ..., file: _Optional[_Union[FileHeader, _Mapping]] = ...) -> None: ...

class WorkspaceStorageRequest(_message.Message):
    __slots__ = ("workspace_id",)
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    def __init__(self, workspace_id: _Optional[str] = ...) -> None: ...

class UpdateStorageQuotaRequest(_message.Message):
    __slots__ = ("workspace_id", "quota_bytes")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    QUOTA_BYTES_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    quota_bytes: int
    def __init__(self, workspace_id: _Optional[str] = ..., quota_bytes: _Optional[int] = ...) -> None: ...

class StorageRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ...) -> None: ...

class ListStoragesRequest(_message.Message):
    __slots__ = ("workspace_id", "page_size", "page_token", "visibility", "owned_only")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    VISIBILITY_FIELD_NUMBER: _ClassVar[int]
    OWNED_ONLY_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    page_size: int
    page_token: str
    visibility: StorageVisibility
    owned_only: bool
    def __init__(self, workspace_id: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., visibility: _Optional[_Union[StorageVisibility, str]] = ..., owned_only: _Optional[bool] = ...) -> None: ...

class ListStoragesResponse(_message.Message):
    __slots__ = ("storages", "next_page_token")
    STORAGES_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    storages: _containers.RepeatedCompositeFieldContainer[Storage]
    next_page_token: str
    def __init__(self, storages: _Optional[_Iterable[_Union[Storage, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class UpdateStorageRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "name")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    name: str
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., name: _Optional[str] = ...) -> None: ...

class SetStorageAccessRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "actor", "role")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    ACTOR_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    actor: ActorRef
    role: StorageRole
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., actor: _Optional[_Union[ActorRef, _Mapping]] = ..., role: _Optional[_Union[StorageRole, str]] = ...) -> None: ...

class RevokeStorageAccessRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "actor")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    ACTOR_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    actor: ActorRef
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., actor: _Optional[_Union[ActorRef, _Mapping]] = ...) -> None: ...

class NodeRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "target")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    target: NodeLocator
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., target: _Optional[_Union[NodeLocator, _Mapping]] = ...) -> None: ...

class BatchStatRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "targets")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGETS_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    targets: _containers.RepeatedCompositeFieldContainer[NodeLocator]
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., targets: _Optional[_Iterable[_Union[NodeLocator, _Mapping]]] = ...) -> None: ...

class StatResult(_message.Message):
    __slots__ = ("node", "error")
    NODE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    node: Node
    error: _status_pb2.Status
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ..., error: _Optional[_Union[_status_pb2.Status, _Mapping]] = ...) -> None: ...

class BatchStatResponse(_message.Message):
    __slots__ = ("results",)
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[StatResult]
    def __init__(self, results: _Optional[_Iterable[_Union[StatResult, _Mapping]]] = ...) -> None: ...

class ListNodesRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "parent", "page_size", "page_token")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    parent: NodeLocator
    page_size: int
    page_token: str
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., parent: _Optional[_Union[NodeLocator, _Mapping]] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListNodesResponse(_message.Message):
    __slots__ = ("nodes", "next_page_token")
    NODES_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    nodes: _containers.RepeatedCompositeFieldContainer[Node]
    next_page_token: str
    def __init__(self, nodes: _Optional[_Iterable[_Union[Node, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class ReadTreeRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "root", "max_depth", "max_nodes")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    ROOT_FIELD_NUMBER: _ClassVar[int]
    MAX_DEPTH_FIELD_NUMBER: _ClassVar[int]
    MAX_NODES_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    root: NodeLocator
    max_depth: int
    max_nodes: int
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., root: _Optional[_Union[NodeLocator, _Mapping]] = ..., max_depth: _Optional[int] = ..., max_nodes: _Optional[int] = ...) -> None: ...

class TreeEntry(_message.Message):
    __slots__ = ("node", "path", "depth")
    NODE_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    DEPTH_FIELD_NUMBER: _ClassVar[int]
    node: Node
    path: str
    depth: int
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ..., path: _Optional[str] = ..., depth: _Optional[int] = ...) -> None: ...

class ReadTreeResponse(_message.Message):
    __slots__ = ("entries", "truncated")
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    TRUNCATED_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.RepeatedCompositeFieldContainer[TreeEntry]
    truncated: bool
    def __init__(self, entries: _Optional[_Iterable[_Union[TreeEntry, _Mapping]]] = ..., truncated: _Optional[bool] = ...) -> None: ...

class TextContent(_message.Message):
    __slots__ = ("content", "media_type")
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    content: str
    media_type: str
    def __init__(self, content: _Optional[str] = ..., media_type: _Optional[str] = ...) -> None: ...

class CreateNodeRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "parent", "name", "directory", "text", "request_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    DIRECTORY_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    parent: NodeLocator
    name: str
    directory: _empty_pb2.Empty
    text: TextContent
    request_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., parent: _Optional[_Union[NodeLocator, _Mapping]] = ..., name: _Optional[str] = ..., directory: _Optional[_Union[_empty_pb2.Empty, _Mapping]] = ..., text: _Optional[_Union[TextContent, _Mapping]] = ..., request_id: _Optional[str] = ...) -> None: ...

class CreateDirectoriesRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "base", "path")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    BASE_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    base: NodeLocator
    path: str
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., base: _Optional[_Union[NodeLocator, _Mapping]] = ..., path: _Optional[str] = ...) -> None: ...

class TransferNodeRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "source", "destination_storage_id", "parent", "name", "request_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    DESTINATION_STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    source: NodeLocator
    destination_storage_id: str
    parent: NodeLocator
    name: str
    request_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., source: _Optional[_Union[NodeLocator, _Mapping]] = ..., destination_storage_id: _Optional[str] = ..., parent: _Optional[_Union[NodeLocator, _Mapping]] = ..., name: _Optional[str] = ..., request_id: _Optional[str] = ...) -> None: ...

class ByteRange(_message.Message):
    __slots__ = ("offset", "length")
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    LENGTH_FIELD_NUMBER: _ClassVar[int]
    offset: int
    length: int
    def __init__(self, offset: _Optional[int] = ..., length: _Optional[int] = ...) -> None: ...

class LineRange(_message.Message):
    __slots__ = ("first", "count")
    FIRST_FIELD_NUMBER: _ClassVar[int]
    COUNT_FIELD_NUMBER: _ClassVar[int]
    first: int
    count: int
    def __init__(self, first: _Optional[int] = ..., count: _Optional[int] = ...) -> None: ...

class ReadTextRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "target", "bytes", "lines", "head_lines", "tail_lines", "include_metrics")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    BYTES_FIELD_NUMBER: _ClassVar[int]
    LINES_FIELD_NUMBER: _ClassVar[int]
    HEAD_LINES_FIELD_NUMBER: _ClassVar[int]
    TAIL_LINES_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_METRICS_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    target: NodeLocator
    bytes: ByteRange
    lines: LineRange
    head_lines: int
    tail_lines: int
    include_metrics: bool
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., target: _Optional[_Union[NodeLocator, _Mapping]] = ..., bytes: _Optional[_Union[ByteRange, _Mapping]] = ..., lines: _Optional[_Union[LineRange, _Mapping]] = ..., head_lines: _Optional[int] = ..., tail_lines: _Optional[int] = ..., include_metrics: _Optional[bool] = ...) -> None: ...

class TextMetrics(_message.Message):
    __slots__ = ("bytes", "lines")
    BYTES_FIELD_NUMBER: _ClassVar[int]
    LINES_FIELD_NUMBER: _ClassVar[int]
    bytes: int
    lines: int
    def __init__(self, bytes: _Optional[int] = ..., lines: _Optional[int] = ...) -> None: ...

class ReadTextResponse(_message.Message):
    __slots__ = ("content", "version", "metrics")
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    METRICS_FIELD_NUMBER: _ClassVar[int]
    content: str
    version: int
    metrics: TextMetrics
    def __init__(self, content: _Optional[str] = ..., version: _Optional[int] = ..., metrics: _Optional[_Union[TextMetrics, _Mapping]] = ...) -> None: ...

class TextEdit(_message.Message):
    __slots__ = ("start_byte", "end_byte", "replacement")
    START_BYTE_FIELD_NUMBER: _ClassVar[int]
    END_BYTE_FIELD_NUMBER: _ClassVar[int]
    REPLACEMENT_FIELD_NUMBER: _ClassVar[int]
    start_byte: int
    end_byte: int
    replacement: str
    def __init__(self, start_byte: _Optional[int] = ..., end_byte: _Optional[int] = ..., replacement: _Optional[str] = ...) -> None: ...

class TextPatch(_message.Message):
    __slots__ = ("edits",)
    EDITS_FIELD_NUMBER: _ClassVar[int]
    edits: _containers.RepeatedCompositeFieldContainer[TextEdit]
    def __init__(self, edits: _Optional[_Iterable[_Union[TextEdit, _Mapping]]] = ...) -> None: ...

class TextOverwrite(_message.Message):
    __slots__ = ("offset", "content")
    OFFSET_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    offset: int
    content: str
    def __init__(self, offset: _Optional[int] = ..., content: _Optional[str] = ...) -> None: ...

class TextReplace(_message.Message):
    __slots__ = ("old_text", "new_text", "replace_all")
    OLD_TEXT_FIELD_NUMBER: _ClassVar[int]
    NEW_TEXT_FIELD_NUMBER: _ClassVar[int]
    REPLACE_ALL_FIELD_NUMBER: _ClassVar[int]
    old_text: str
    new_text: str
    replace_all: bool
    def __init__(self, old_text: _Optional[str] = ..., new_text: _Optional[str] = ..., replace_all: _Optional[bool] = ...) -> None: ...

class MutateTextRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "target", "replace", "append", "patch", "truncate_bytes", "overwrite", "literal_replace", "expected_version", "request_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    REPLACE_FIELD_NUMBER: _ClassVar[int]
    APPEND_FIELD_NUMBER: _ClassVar[int]
    PATCH_FIELD_NUMBER: _ClassVar[int]
    TRUNCATE_BYTES_FIELD_NUMBER: _ClassVar[int]
    OVERWRITE_FIELD_NUMBER: _ClassVar[int]
    LITERAL_REPLACE_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_VERSION_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    target: NodeLocator
    replace: str
    append: str
    patch: TextPatch
    truncate_bytes: int
    overwrite: TextOverwrite
    literal_replace: TextReplace
    expected_version: int
    request_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., target: _Optional[_Union[NodeLocator, _Mapping]] = ..., replace: _Optional[str] = ..., append: _Optional[str] = ..., patch: _Optional[_Union[TextPatch, _Mapping]] = ..., truncate_bytes: _Optional[int] = ..., overwrite: _Optional[_Union[TextOverwrite, _Mapping]] = ..., literal_replace: _Optional[_Union[TextReplace, _Mapping]] = ..., expected_version: _Optional[int] = ..., request_id: _Optional[str] = ...) -> None: ...

class ReadImageRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "target", "max_width", "max_height")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    MAX_WIDTH_FIELD_NUMBER: _ClassVar[int]
    MAX_HEIGHT_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    target: NodeLocator
    max_width: int
    max_height: int
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., target: _Optional[_Union[NodeLocator, _Mapping]] = ..., max_width: _Optional[int] = ..., max_height: _Optional[int] = ...) -> None: ...

class SignedDownload(_message.Message):
    __slots__ = ("url", "expires_at")
    URL_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    url: str
    expires_at: _timestamp_pb2.Timestamp
    def __init__(self, url: _Optional[str] = ..., expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class TextDownload(_message.Message):
    __slots__ = ("filename", "media_type", "content")
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    filename: str
    media_type: str
    content: str
    def __init__(self, filename: _Optional[str] = ..., media_type: _Optional[str] = ..., content: _Optional[str] = ...) -> None: ...

class GetDownloadResponse(_message.Message):
    __slots__ = ("blob", "text")
    BLOB_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    blob: SignedDownload
    text: TextDownload
    def __init__(self, blob: _Optional[_Union[SignedDownload, _Mapping]] = ..., text: _Optional[_Union[TextDownload, _Mapping]] = ...) -> None: ...

class DownloadArchiveRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "targets")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGETS_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    targets: _containers.RepeatedCompositeFieldContainer[NodeLocator]
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., targets: _Optional[_Iterable[_Union[NodeLocator, _Mapping]]] = ...) -> None: ...

class SearchFilesRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "root", "query", "page_size", "page_token", "case_sensitive")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    ROOT_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    CASE_SENSITIVE_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    root: NodeLocator
    query: str
    page_size: int
    page_token: str
    case_sensitive: bool
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., root: _Optional[_Union[NodeLocator, _Mapping]] = ..., query: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., case_sensitive: _Optional[bool] = ...) -> None: ...

class SearchFilesResponse(_message.Message):
    __slots__ = ("hits", "next_page_token")
    HITS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    hits: _containers.RepeatedCompositeFieldContainer[Node]
    next_page_token: str
    def __init__(self, hits: _Optional[_Iterable[_Union[Node, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class TextSearchRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "root", "query", "page_size", "page_token", "case_sensitive", "lines_mode")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    ROOT_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    CASE_SENSITIVE_FIELD_NUMBER: _ClassVar[int]
    LINES_MODE_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    root: NodeLocator
    query: str
    page_size: int
    page_token: str
    case_sensitive: bool
    lines_mode: bool
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., root: _Optional[_Union[NodeLocator, _Mapping]] = ..., query: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ..., case_sensitive: _Optional[bool] = ..., lines_mode: _Optional[bool] = ...) -> None: ...

class TextHit(_message.Message):
    __slots__ = ("node", "snippet", "line_number", "path")
    NODE_FIELD_NUMBER: _ClassVar[int]
    SNIPPET_FIELD_NUMBER: _ClassVar[int]
    LINE_NUMBER_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    node: Node
    snippet: str
    line_number: int
    path: str
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ..., snippet: _Optional[str] = ..., line_number: _Optional[int] = ..., path: _Optional[str] = ...) -> None: ...

class TextSearchResponse(_message.Message):
    __slots__ = ("hits", "next_page_token")
    HITS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    hits: _containers.RepeatedCompositeFieldContainer[TextHit]
    next_page_token: str
    def __init__(self, hits: _Optional[_Iterable[_Union[TextHit, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class SemanticSearchRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "root", "query", "top_k")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    ROOT_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    TOP_K_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    root: NodeLocator
    query: str
    top_k: int
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., root: _Optional[_Union[NodeLocator, _Mapping]] = ..., query: _Optional[str] = ..., top_k: _Optional[int] = ...) -> None: ...

class SemanticHit(_message.Message):
    __slots__ = ("node", "snippet", "score", "path")
    NODE_FIELD_NUMBER: _ClassVar[int]
    SNIPPET_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    node: Node
    snippet: str
    score: float
    path: str
    def __init__(self, node: _Optional[_Union[Node, _Mapping]] = ..., snippet: _Optional[str] = ..., score: _Optional[float] = ..., path: _Optional[str] = ...) -> None: ...

class SemanticSearchResponse(_message.Message):
    __slots__ = ("hits",)
    HITS_FIELD_NUMBER: _ClassVar[int]
    hits: _containers.RepeatedCompositeFieldContainer[SemanticHit]
    def __init__(self, hits: _Optional[_Iterable[_Union[SemanticHit, _Mapping]]] = ...) -> None: ...

class TrashNodeRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "target", "request_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    target: NodeLocator
    request_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., target: _Optional[_Union[NodeLocator, _Mapping]] = ..., request_id: _Optional[str] = ...) -> None: ...

class TrashEntry(_message.Message):
    __slots__ = ("id", "node", "original_parent_id", "trashed_by", "trashed_at")
    ID_FIELD_NUMBER: _ClassVar[int]
    NODE_FIELD_NUMBER: _ClassVar[int]
    ORIGINAL_PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    TRASHED_BY_FIELD_NUMBER: _ClassVar[int]
    TRASHED_AT_FIELD_NUMBER: _ClassVar[int]
    id: str
    node: Node
    original_parent_id: str
    trashed_by: ActorRef
    trashed_at: _timestamp_pb2.Timestamp
    def __init__(self, id: _Optional[str] = ..., node: _Optional[_Union[Node, _Mapping]] = ..., original_parent_id: _Optional[str] = ..., trashed_by: _Optional[_Union[ActorRef, _Mapping]] = ..., trashed_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class ListTrashRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "page_size", "page_token")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    page_size: int
    page_token: str
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListTrashResponse(_message.Message):
    __slots__ = ("entries", "next_page_token")
    ENTRIES_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    entries: _containers.RepeatedCompositeFieldContainer[TrashEntry]
    next_page_token: str
    def __init__(self, entries: _Optional[_Iterable[_Union[TrashEntry, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class RestoreTrashRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "trash_id", "parent", "name")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    TRASH_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    trash_id: str
    parent: NodeLocator
    name: str
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., trash_id: _Optional[str] = ..., parent: _Optional[_Union[NodeLocator, _Mapping]] = ..., name: _Optional[str] = ...) -> None: ...

class PurgeTrashRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "trash_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    TRASH_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    trash_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., trash_id: _Optional[str] = ...) -> None: ...

class UploadCreate(_message.Message):
    __slots__ = ("parent", "name")
    PARENT_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    parent: NodeLocator
    name: str
    def __init__(self, parent: _Optional[_Union[NodeLocator, _Mapping]] = ..., name: _Optional[str] = ...) -> None: ...

class UploadReplace(_message.Message):
    __slots__ = ("target", "expected_version")
    TARGET_FIELD_NUMBER: _ClassVar[int]
    EXPECTED_VERSION_FIELD_NUMBER: _ClassVar[int]
    target: NodeLocator
    expected_version: int
    def __init__(self, target: _Optional[_Union[NodeLocator, _Mapping]] = ..., expected_version: _Optional[int] = ...) -> None: ...

class CreateUploadRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "create", "replace", "size_bytes", "media_type", "checksum", "request_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    CREATE_FIELD_NUMBER: _ClassVar[int]
    REPLACE_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    CHECKSUM_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    create: UploadCreate
    replace: UploadReplace
    size_bytes: int
    media_type: str
    checksum: str
    request_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., create: _Optional[_Union[UploadCreate, _Mapping]] = ..., replace: _Optional[_Union[UploadReplace, _Mapping]] = ..., size_bytes: _Optional[int] = ..., media_type: _Optional[str] = ..., checksum: _Optional[str] = ..., request_id: _Optional[str] = ...) -> None: ...

class SignedPart(_message.Message):
    __slots__ = ("part_number", "url", "headers")
    class HeadersEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    PART_NUMBER_FIELD_NUMBER: _ClassVar[int]
    URL_FIELD_NUMBER: _ClassVar[int]
    HEADERS_FIELD_NUMBER: _ClassVar[int]
    part_number: int
    url: str
    headers: _containers.ScalarMap[str, str]
    def __init__(self, part_number: _Optional[int] = ..., url: _Optional[str] = ..., headers: _Optional[_Mapping[str, str]] = ...) -> None: ...

class UploadPart(_message.Message):
    __slots__ = ("part_number", "checksum")
    PART_NUMBER_FIELD_NUMBER: _ClassVar[int]
    CHECKSUM_FIELD_NUMBER: _ClassVar[int]
    part_number: int
    checksum: str
    def __init__(self, part_number: _Optional[int] = ..., checksum: _Optional[str] = ...) -> None: ...

class TransferDescriptor(_message.Message):
    __slots__ = ("put_url", "headers", "multipart", "part_size_bytes")
    class HeadersEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    PUT_URL_FIELD_NUMBER: _ClassVar[int]
    HEADERS_FIELD_NUMBER: _ClassVar[int]
    MULTIPART_FIELD_NUMBER: _ClassVar[int]
    PART_SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    put_url: str
    headers: _containers.ScalarMap[str, str]
    multipart: bool
    part_size_bytes: int
    def __init__(self, put_url: _Optional[str] = ..., headers: _Optional[_Mapping[str, str]] = ..., multipart: _Optional[bool] = ..., part_size_bytes: _Optional[int] = ...) -> None: ...

class Upload(_message.Message):
    __slots__ = ("id", "expires_at", "transfer", "completed")
    ID_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    TRANSFER_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_FIELD_NUMBER: _ClassVar[int]
    id: str
    expires_at: _timestamp_pb2.Timestamp
    transfer: TransferDescriptor
    completed: Node
    def __init__(self, id: _Optional[str] = ..., expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., transfer: _Optional[_Union[TransferDescriptor, _Mapping]] = ..., completed: _Optional[_Union[Node, _Mapping]] = ...) -> None: ...

class UploadRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "upload_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    upload_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., upload_id: _Optional[str] = ...) -> None: ...

class SignPartsRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "upload_id", "parts")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    PARTS_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    upload_id: str
    parts: _containers.RepeatedCompositeFieldContainer[UploadPart]
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., upload_id: _Optional[str] = ..., parts: _Optional[_Iterable[_Union[UploadPart, _Mapping]]] = ...) -> None: ...

class SignPartsResponse(_message.Message):
    __slots__ = ("parts",)
    PARTS_FIELD_NUMBER: _ClassVar[int]
    parts: _containers.RepeatedCompositeFieldContainer[SignedPart]
    def __init__(self, parts: _Optional[_Iterable[_Union[SignedPart, _Mapping]]] = ...) -> None: ...

class CompletedPart(_message.Message):
    __slots__ = ("part_number", "etag", "checksum")
    PART_NUMBER_FIELD_NUMBER: _ClassVar[int]
    ETAG_FIELD_NUMBER: _ClassVar[int]
    CHECKSUM_FIELD_NUMBER: _ClassVar[int]
    part_number: int
    etag: str
    checksum: str
    def __init__(self, part_number: _Optional[int] = ..., etag: _Optional[str] = ..., checksum: _Optional[str] = ...) -> None: ...

class CompleteUploadRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "upload_id", "parts")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    PARTS_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    upload_id: str
    parts: _containers.RepeatedCompositeFieldContainer[CompletedPart]
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., upload_id: _Optional[str] = ..., parts: _Optional[_Iterable[_Union[CompletedPart, _Mapping]]] = ...) -> None: ...
