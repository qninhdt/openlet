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

class ProcessingRequest(_message.Message):
    __slots__ = ("file_id", "version")
    FILE_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    file_id: str
    version: int
    def __init__(self, file_id: _Optional[str] = ..., version: _Optional[int] = ...) -> None: ...

class ProcessingOutcome(_message.Message):
    __slots__ = ("obsolete", "stage")
    OBSOLETE_FIELD_NUMBER: _ClassVar[int]
    STAGE_FIELD_NUMBER: _ClassVar[int]
    obsolete: bool
    stage: str
    def __init__(self, obsolete: _Optional[bool] = ..., stage: _Optional[str] = ...) -> None: ...

class ProcessingArtifact(_message.Message):
    __slots__ = ("node", "path", "text_content", "download_url")
    NODE_FIELD_NUMBER: _ClassVar[int]
    PATH_FIELD_NUMBER: _ClassVar[int]
    TEXT_CONTENT_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_URL_FIELD_NUMBER: _ClassVar[int]
    node: _letfs_pb2.Node
    path: str
    text_content: str
    download_url: str
    def __init__(self, node: _Optional[_Union[_letfs_pb2.Node, _Mapping]] = ..., path: _Optional[str] = ..., text_content: _Optional[str] = ..., download_url: _Optional[str] = ...) -> None: ...

class ProcessingInput(_message.Message):
    __slots__ = ("outcome", "workspace_id", "storage_id", "source_name", "media_type", "download_url", "allow_indexing", "artifacts", "source_metadata")
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_NAME_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    DOWNLOAD_URL_FIELD_NUMBER: _ClassVar[int]
    ALLOW_INDEXING_FIELD_NUMBER: _ClassVar[int]
    ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    SOURCE_METADATA_FIELD_NUMBER: _ClassVar[int]
    outcome: ProcessingOutcome
    workspace_id: str
    storage_id: str
    source_name: str
    media_type: str
    download_url: str
    allow_indexing: bool
    artifacts: _containers.RepeatedCompositeFieldContainer[ProcessingArtifact]
    source_metadata: _letfs_pb2.FileMetadata
    def __init__(self, outcome: _Optional[_Union[ProcessingOutcome, _Mapping]] = ..., workspace_id: _Optional[str] = ..., storage_id: _Optional[str] = ..., source_name: _Optional[str] = ..., media_type: _Optional[str] = ..., download_url: _Optional[str] = ..., allow_indexing: _Optional[bool] = ..., artifacts: _Optional[_Iterable[_Union[ProcessingArtifact, _Mapping]]] = ..., source_metadata: _Optional[_Union[_letfs_pb2.FileMetadata, _Mapping]] = ...) -> None: ...

class ArtifactUploadSpec(_message.Message):
    __slots__ = ("path", "size_bytes", "media_type", "checksum")
    PATH_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    CHECKSUM_FIELD_NUMBER: _ClassVar[int]
    path: str
    size_bytes: int
    media_type: str
    checksum: str
    def __init__(self, path: _Optional[str] = ..., size_bytes: _Optional[int] = ..., media_type: _Optional[str] = ..., checksum: _Optional[str] = ...) -> None: ...

class PrepareArtifactUploadsRequest(_message.Message):
    __slots__ = ("file_id", "version", "outputs")
    FILE_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    OUTPUTS_FIELD_NUMBER: _ClassVar[int]
    file_id: str
    version: int
    outputs: _containers.RepeatedCompositeFieldContainer[ArtifactUploadSpec]
    def __init__(self, file_id: _Optional[str] = ..., version: _Optional[int] = ..., outputs: _Optional[_Iterable[_Union[ArtifactUploadSpec, _Mapping]]] = ...) -> None: ...

class ArtifactUpload(_message.Message):
    __slots__ = ("path", "upload_id", "put_url", "headers")
    class HeadersEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    PATH_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    PUT_URL_FIELD_NUMBER: _ClassVar[int]
    HEADERS_FIELD_NUMBER: _ClassVar[int]
    path: str
    upload_id: str
    put_url: str
    headers: _containers.ScalarMap[str, str]
    def __init__(self, path: _Optional[str] = ..., upload_id: _Optional[str] = ..., put_url: _Optional[str] = ..., headers: _Optional[_Mapping[str, str]] = ...) -> None: ...

class PrepareArtifactUploadsResponse(_message.Message):
    __slots__ = ("outcome", "uploads")
    OUTCOME_FIELD_NUMBER: _ClassVar[int]
    UPLOADS_FIELD_NUMBER: _ClassVar[int]
    outcome: ProcessingOutcome
    uploads: _containers.RepeatedCompositeFieldContainer[ArtifactUpload]
    def __init__(self, outcome: _Optional[_Union[ProcessingOutcome, _Mapping]] = ..., uploads: _Optional[_Iterable[_Union[ArtifactUpload, _Mapping]]] = ...) -> None: ...

class Artifact(_message.Message):
    __slots__ = ("path", "directory", "text", "upload_id")
    PATH_FIELD_NUMBER: _ClassVar[int]
    DIRECTORY_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    UPLOAD_ID_FIELD_NUMBER: _ClassVar[int]
    path: str
    directory: _empty_pb2.Empty
    text: _letfs_pb2.TextContent
    upload_id: str
    def __init__(self, path: _Optional[str] = ..., directory: _Optional[_Union[_empty_pb2.Empty, _Mapping]] = ..., text: _Optional[_Union[_letfs_pb2.TextContent, _Mapping]] = ..., upload_id: _Optional[str] = ...) -> None: ...

class CommitParseRequest(_message.Message):
    __slots__ = ("file_id", "version", "artifacts")
    FILE_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    file_id: str
    version: int
    artifacts: _containers.RepeatedCompositeFieldContainer[Artifact]
    def __init__(self, file_id: _Optional[str] = ..., version: _Optional[int] = ..., artifacts: _Optional[_Iterable[_Union[Artifact, _Mapping]]] = ...) -> None: ...

class EnrichedArtifact(_message.Message):
    __slots__ = ("node_id", "text_content", "metadata")
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    TEXT_CONTENT_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    node_id: str
    text_content: str
    metadata: _letfs_pb2.FileMetadata
    def __init__(self, node_id: _Optional[str] = ..., text_content: _Optional[str] = ..., metadata: _Optional[_Union[_letfs_pb2.FileMetadata, _Mapping]] = ...) -> None: ...

class CommitEnrichmentRequest(_message.Message):
    __slots__ = ("file_id", "version", "artifacts", "source_metadata")
    FILE_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    ARTIFACTS_FIELD_NUMBER: _ClassVar[int]
    SOURCE_METADATA_FIELD_NUMBER: _ClassVar[int]
    file_id: str
    version: int
    artifacts: _containers.RepeatedCompositeFieldContainer[EnrichedArtifact]
    source_metadata: _letfs_pb2.FileMetadata
    def __init__(self, file_id: _Optional[str] = ..., version: _Optional[int] = ..., artifacts: _Optional[_Iterable[_Union[EnrichedArtifact, _Mapping]]] = ..., source_metadata: _Optional[_Union[_letfs_pb2.FileMetadata, _Mapping]] = ...) -> None: ...

class FailProcessingRequest(_message.Message):
    __slots__ = ("file_id", "version", "error_code")
    FILE_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODE_FIELD_NUMBER: _ClassVar[int]
    file_id: str
    version: int
    error_code: str
    def __init__(self, file_id: _Optional[str] = ..., version: _Optional[int] = ..., error_code: _Optional[str] = ...) -> None: ...
