from google.protobuf import empty_pb2 as _empty_pb2
from openlet_api.letfs.v1 import letfs_pb2 as _letfs_pb2
from buf.validate import validate_pb2 as _validate_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ProvisionWorkspaceStorageRequest(_message.Message):
    __slots__ = ("workspace_id", "quota_bytes")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    QUOTA_BYTES_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    quota_bytes: int
    def __init__(self, workspace_id: _Optional[str] = ..., quota_bytes: _Optional[int] = ...) -> None: ...

class CreateStorageRequest(_message.Message):
    __slots__ = ("workspace_id", "storage_id", "root_node_id", "owner", "name", "visibility", "allow_blob_files", "allow_indexing")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    ROOT_NODE_ID_FIELD_NUMBER: _ClassVar[int]
    OWNER_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    VISIBILITY_FIELD_NUMBER: _ClassVar[int]
    ALLOW_BLOB_FILES_FIELD_NUMBER: _ClassVar[int]
    ALLOW_INDEXING_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    storage_id: str
    root_node_id: str
    owner: _letfs_pb2.StorageOwnership
    name: str
    visibility: _letfs_pb2.StorageVisibility
    allow_blob_files: bool
    allow_indexing: bool
    def __init__(self, workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., root_node_id: _Optional[str] = ..., owner: _Optional[_Union[_letfs_pb2.StorageOwnership, _Mapping]] = ..., name: _Optional[str] = ..., visibility: _Optional[_Union[_letfs_pb2.StorageVisibility, str]] = ..., allow_blob_files: _Optional[bool] = ..., allow_indexing: _Optional[bool] = ...) -> None: ...

class BlobRequest(_message.Message):
    __slots__ = ("blob_id",)
    BLOB_ID_FIELD_NUMBER: _ClassVar[int]
    blob_id: str
    def __init__(self, blob_id: _Optional[str] = ...) -> None: ...

class BlobProcessingOutcome(_message.Message):
    __slots__ = ("obsolete", "stage")
    OBSOLETE_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    obsolete: bool
    stage: str
    def __init__(self, obsolete: _Optional[bool] = ..., stage: _Optional[str] = ...) -> None: ...

class BlobArtifact(_message.Message):
    __slots__ = ("id", "blob_id", "path", "parent_path", "kind", "media_type", "size_bytes", "checksum", "object_key", "text_content", "title", "description", "indexable")
    ID_FIELD_NUMBER: _ClassVar[int]
    BLOB_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    PARENT_PATH_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    CHECKSUM_FIELD_NUMBER: _ClassVar[int]
    OBJECT_KEY_FIELD_NUMBER: _ClassVar[int]
    TEXT_CONTENT_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    INDEXABLE_FIELD_NUMBER: _ClassVar[int]
    id: str
    blob_id: str
    path: str
    parent_path: str
    kind: _letfs_pb2.NodeKind
    media_type: str
    size_bytes: int
    checksum: str
    object_key: str
    text_content: str
    title: str
    description: str
    indexable: bool
    def __init__(self, id: _Optional[str] = ..., blob_id: _Optional[str] = ..., path: _Optional[str] = ..., parent_path: _Optional[str] = ..., kind: _Optional[_Union[_letfs_pb2.NodeKind, str]] = ..., media_type: _Optional[str] = ..., size_bytes: _Optional[int] = ..., checksum: _Optional[str] = ..., object_key: _Optional[str] = ..., text_content: _Optional[str] = ..., title: _Optional[str] = ..., description: _Optional[str] = ..., indexable: _Optional[bool] = ...) -> None: ...

class GetBlobArtifactsResponse(_message.Message):
    __slots__ = ("outcome", "workspace_id", "blob_id", "object_key", "source_download_url", "media_type", "source_name", "size_bytes", "checksum", "title", "description", "artifacts")
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    BLOB_ID_FIELD_NUMBER: _ClassVar[int]
    OBJECT_KEY_FIELD_NUMBER: _ClassVar[int]
    SOURCE_DOWNLOAD_URL_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    SOURCE_NAME_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    CHECKSUM_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    outcome: BlobProcessingOutcome
    workspace_id: str
    blob_id: str
    object_key: str
    source_download_url: str
    media_type: str
    source_name: str
    size_bytes: int
    checksum: str
    title: str
    description: str
    artifacts: _containers.RepeatedCompositeFieldContainer[BlobArtifact]
    def __init__(self, outcome: _Optional[_Union[BlobProcessingOutcome, _Mapping]] = ..., workspace_id: _Optional[str] = ..., blob_id: _Optional[str] = ..., object_key: _Optional[str] = ..., source_download_url: _Optional[str] = ..., media_type: _Optional[str] = ..., source_name: _Optional[str] = ..., size_bytes: _Optional[int] = ..., checksum: _Optional[str] = ..., title: _Optional[str] = ..., description: _Optional[str] = ..., artifacts: _Optional[_Iterable[_Union[BlobArtifact, _Mapping]]] = ...) -> None: ...

class ParsedArtifactInput(_message.Message):
    __slots__ = ("path", "kind", "media_type", "size_bytes", "checksum", "object_key", "text_content", "title", "description", "indexable")
    PATH_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    CHECKSUM_FIELD_NUMBER: _ClassVar[int]
    OBJECT_KEY_FIELD_NUMBER: _ClassVar[int]
    TEXT_CONTENT_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    INDEXABLE_FIELD_NUMBER: _ClassVar[int]
    path: str
    kind: _letfs_pb2.NodeKind
    media_type: str
    size_bytes: int
    checksum: str
    object_key: str
    text_content: str
    title: str
    description: str
    indexable: bool
    def __init__(self, path: _Optional[str] = ..., kind: _Optional[_Union[_letfs_pb2.NodeKind, str]] = ..., media_type: _Optional[str] = ..., size_bytes: _Optional[int] = ..., checksum: _Optional[str] = ..., object_key: _Optional[str] = ..., text_content: _Optional[str] = ..., title: _Optional[str] = ..., description: _Optional[str] = ..., indexable: _Optional[bool] = ...) -> None: ...

class SaveParsedArtifactsRequest(_message.Message):
    __slots__ = ("blob_id", "artifacts")
    BLOB_ID_FIELD_NUMBER: _ClassVar[int]
    ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    blob_id: str
    artifacts: _containers.RepeatedCompositeFieldContainer[ParsedArtifactInput]
    def __init__(self, blob_id: _Optional[str] = ..., artifacts: _Optional[_Iterable[_Union[ParsedArtifactInput, _Mapping]]] = ...) -> None: ...

class EnrichedArtifactInput(_message.Message):
    __slots__ = ("artifact_id", "path", "text_content", "title", "description")
    ARTIFACT_ID_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    TEXT_CONTENT_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    artifact_id: str
    path: str
    text_content: str
    title: str
    description: str
    def __init__(self, artifact_id: _Optional[str] = ..., path: _Optional[str] = ..., text_content: _Optional[str] = ..., title: _Optional[str] = ..., description: _Optional[str] = ...) -> None: ...

class SaveEnrichedArtifactsRequest(_message.Message):
    __slots__ = ("blob_id", "blob_title", "blob_description", "artifacts")
    BLOB_ID_FIELD_NUMBER: _ClassVar[int]
    BLOB_TITLE_FIELD_NUMBER: _ClassVar[int]
    BLOB_DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    blob_id: str
    blob_title: str
    blob_description: str
    artifacts: _containers.RepeatedCompositeFieldContainer[EnrichedArtifactInput]
    def __init__(self, blob_id: _Optional[str] = ..., blob_title: _Optional[str] = ..., blob_description: _Optional[str] = ..., artifacts: _Optional[_Iterable[_Union[EnrichedArtifactInput, _Mapping]]] = ...) -> None: ...
