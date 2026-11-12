from google.protobuf import empty_pb2 as _empty_pb2
from openlet_api.platform.v1 import platform_pb2 as _platform_pb2
from buf.validate import validate_pb2 as _validate_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class CreateWorkspaceRequest(_message.Message):
    __slots__ = ("owner_user_id", "name", "request_id")
    OWNER_USER_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    owner_user_id: str
    name: str
    request_id: str
    def __init__(self, owner_user_id: _Optional[str] = ..., name: _Optional[str] = ..., request_id: _Optional[str] = ...) -> None: ...

class BatchGetUsersRequest(_message.Message):
    __slots__ = ("user_ids",)
    USER_IDS_FIELD_NUMBER: _ClassVar[int]
    user_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, user_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class BatchGetUsersResponse(_message.Message):
    __slots__ = ("users",)
    USERS_FIELD_NUMBER: _ClassVar[int]
    users: _containers.RepeatedCompositeFieldContainer[_platform_pb2.User]
    def __init__(self, users: _Optional[_Iterable[_Union[_platform_pb2.User, _Mapping]]] = ...) -> None: ...

class CheckWorkspaceActiveRequest(_message.Message):
    __slots__ = ("workspace_id",)
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    def __init__(self, workspace_id: _Optional[str] = ...) -> None: ...
