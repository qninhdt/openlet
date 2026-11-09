from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class GetLetaBindingRequest(_message.Message):
    __slots__ = ("leta_id",)
    LETA_ID_FIELD_NUMBER: _ClassVar[int]
    leta_id: str
    def __init__(self, leta_id: _Optional[str] = ...) -> None: ...

class GetLetaBindingResponse(_message.Message):
    __slots__ = ("leta_id", "kind", "workspace_id", "created_by_user_id", "home_scope_id", "status")
    LETA_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_USER_ID_FIELD_NUMBER: _ClassVar[int]
    HOME_SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    leta_id: str
    kind: str
    workspace_id: str
    created_by_user_id: str
    home_scope_id: str
    status: str
    def __init__(self, leta_id: _Optional[str] = ..., kind: _Optional[str] = ..., workspace_id: _Optional[str] = ..., created_by_user_id: _Optional[str] = ..., home_scope_id: _Optional[str] = ..., status: _Optional[str] = ...) -> None: ...

class ListWorkspaceLetaRequest(_message.Message):
    __slots__ = ("workspace_id", "cursor", "limit")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    cursor: str
    limit: int
    def __init__(self, workspace_id: _Optional[str] = ..., cursor: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class ListWorkspaceLetaResponse(_message.Message):
    __slots__ = ("workspace_id", "leta_ids", "next_cursor")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    LETA_IDS_FIELD_NUMBER: _ClassVar[int]
    NEXT_CURSOR_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    leta_ids: _containers.RepeatedScalarFieldContainer[str]
    next_cursor: str
    def __init__(self, workspace_id: _Optional[str] = ..., leta_ids: _Optional[_Iterable[str]] = ..., next_cursor: _Optional[str] = ...) -> None: ...

class StopLetaForWorkspaceDeletionRequest(_message.Message):
    __slots__ = ("workspace_id", "leta_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    LETA_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    leta_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., leta_id: _Optional[str] = ...) -> None: ...

class StopLetaForWorkspaceDeletionResponse(_message.Message):
    __slots__ = ("workspace_id", "leta_id", "status")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    LETA_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    leta_id: str
    status: str
    def __init__(self, workspace_id: _Optional[str] = ..., leta_id: _Optional[str] = ..., status: _Optional[str] = ...) -> None: ...
