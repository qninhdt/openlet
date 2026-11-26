from buf.validate import validate_pb2 as _validate_pb2
from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class DeleteWorkspaceDataRequest(_message.Message):
    __slots__ = ("workspace_id",)
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    def __init__(self, workspace_id: _Optional[str] = ...) -> None: ...

class RemoveAgentRequest(_message.Message):
    __slots__ = ("workspace_id", "agent_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    agent_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., agent_id: _Optional[str] = ...) -> None: ...
