from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class EnsureInitialWorkspaceRequest(_message.Message):
    __slots__ = ("actor_id", "request_key", "name")
    ACTOR_ID_FIELD_NUMBER: _ClassVar[int]
    REQUEST_KEY_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    actor_id: str
    request_key: str
    name: str
    def __init__(self, actor_id: _Optional[str] = ..., request_key: _Optional[str] = ..., name: _Optional[str] = ...) -> None: ...

class EnsureInitialWorkspaceResponse(_message.Message):
    __slots__ = ("workspace_id", "completed")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    COMPLETED_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    completed: bool
    def __init__(self, workspace_id: _Optional[str] = ..., completed: _Optional[bool] = ...) -> None: ...
