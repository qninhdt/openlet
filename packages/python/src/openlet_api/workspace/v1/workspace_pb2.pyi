from openlet_api.account.v1 import account_pb2 as _account_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Workspace(_message.Message):
    __slots__ = ("id", "name", "filesystem_id", "shared_scope_id", "status", "role", "personal_scope_id")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SHARED_SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    PERSONAL_SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    filesystem_id: str
    shared_scope_id: str
    status: str
    role: str
    personal_scope_id: str
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., filesystem_id: _Optional[str] = ..., shared_scope_id: _Optional[str] = ..., status: _Optional[str] = ..., role: _Optional[str] = ..., personal_scope_id: _Optional[str] = ...) -> None: ...

class GetWorkspaceRequest(_message.Message):
    __slots__ = ("workspace_id", "cleanup_leta_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CLEANUP_LETA_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    cleanup_leta_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., cleanup_leta_id: _Optional[str] = ...) -> None: ...

class GetWorkspaceResponse(_message.Message):
    __slots__ = ("workspace",)
    WORKSPACE_FIELD_NUMBER: _ClassVar[int]
    workspace: Workspace
    def __init__(self, workspace: _Optional[_Union[Workspace, _Mapping]] = ...) -> None: ...

class ListMembersRequest(_message.Message):
    __slots__ = ("workspace_id", "cursor", "limit")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    cursor: str
    limit: int
    def __init__(self, workspace_id: _Optional[str] = ..., cursor: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class Member(_message.Message):
    __slots__ = ("user", "role", "personal_scope_id")
    USER_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    PERSONAL_SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    user: _account_pb2.UserSummary
    role: str
    personal_scope_id: str
    def __init__(self, user: _Optional[_Union[_account_pb2.UserSummary, _Mapping]] = ..., role: _Optional[str] = ..., personal_scope_id: _Optional[str] = ...) -> None: ...

class ListMembersResponse(_message.Message):
    __slots__ = ("workspace_id", "items", "next_cursor")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    NEXT_CURSOR_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    items: _containers.RepeatedCompositeFieldContainer[Member]
    next_cursor: str
    def __init__(self, workspace_id: _Optional[str] = ..., items: _Optional[_Iterable[_Union[Member, _Mapping]]] = ..., next_cursor: _Optional[str] = ...) -> None: ...

class ListAccessibleScopesRequest(_message.Message):
    __slots__ = ("workspace_id", "leta_id", "cursor", "limit")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    LETA_ID_FIELD_NUMBER: _ClassVar[int]
    CURSOR_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    leta_id: str
    cursor: str
    limit: int
    def __init__(self, workspace_id: _Optional[str] = ..., leta_id: _Optional[str] = ..., cursor: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class ScopeRights(_message.Message):
    __slots__ = ("read_metadata", "read_content", "write")
    READ_METADATA_FIELD_NUMBER: _ClassVar[int]
    READ_CONTENT_FIELD_NUMBER: _ClassVar[int]
    WRITE_FIELD_NUMBER: _ClassVar[int]
    read_metadata: bool
    read_content: bool
    write: bool
    def __init__(self, read_metadata: _Optional[bool] = ..., read_content: _Optional[bool] = ..., write: _Optional[bool] = ...) -> None: ...

class AccessibleScope(_message.Message):
    __slots__ = ("id", "root_id", "kind", "owner", "rights")
    ID_FIELD_NUMBER: _ClassVar[int]
    ROOT_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    OWNER_FIELD_NUMBER: _ClassVar[int]
    RIGHTS_FIELD_NUMBER: _ClassVar[int]
    id: str
    root_id: str
    kind: str
    owner: _account_pb2.UserSummary
    rights: ScopeRights
    def __init__(self, id: _Optional[str] = ..., root_id: _Optional[str] = ..., kind: _Optional[str] = ..., owner: _Optional[_Union[_account_pb2.UserSummary, _Mapping]] = ..., rights: _Optional[_Union[ScopeRights, _Mapping]] = ...) -> None: ...

class ListAccessibleScopesResponse(_message.Message):
    __slots__ = ("workspace_id", "filesystem_id", "subject_kind", "subject_id", "items", "next_cursor")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_KIND_FIELD_NUMBER: _ClassVar[int]
    SUBJECT_ID_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    NEXT_CURSOR_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    filesystem_id: str
    subject_kind: str
    subject_id: str
    items: _containers.RepeatedCompositeFieldContainer[AccessibleScope]
    next_cursor: str
    def __init__(self, workspace_id: _Optional[str] = ..., filesystem_id: _Optional[str] = ..., subject_kind: _Optional[str] = ..., subject_id: _Optional[str] = ..., items: _Optional[_Iterable[_Union[AccessibleScope, _Mapping]]] = ..., next_cursor: _Optional[str] = ...) -> None: ...

class EnsureLetaHomeAccessRequest(_message.Message):
    __slots__ = ("workspace_id", "leta_id", "home_scope_id", "idempotency_key")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    LETA_ID_FIELD_NUMBER: _ClassVar[int]
    HOME_SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    leta_id: str
    home_scope_id: str
    idempotency_key: str
    def __init__(self, workspace_id: _Optional[str] = ..., leta_id: _Optional[str] = ..., home_scope_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ...) -> None: ...

class EnsureLetaHomeAccessResponse(_message.Message):
    __slots__ = ("workspace_id", "filesystem_id", "home_scope_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    HOME_SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    filesystem_id: str
    home_scope_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., filesystem_id: _Optional[str] = ..., home_scope_id: _Optional[str] = ...) -> None: ...

class ResolvePersonalScopeRequest(_message.Message):
    __slots__ = ("workspace_id", "owner_user_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    OWNER_USER_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    owner_user_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., owner_user_id: _Optional[str] = ...) -> None: ...

class ResolvePersonalScopeResponse(_message.Message):
    __slots__ = ("workspace_id", "filesystem_id", "scope_id", "owner_user_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    FILESYSTEM_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    OWNER_USER_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    filesystem_id: str
    scope_id: str
    owner_user_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., filesystem_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., owner_user_id: _Optional[str] = ...) -> None: ...

class ChangeScopeAccessRequest(_message.Message):
    __slots__ = ("workspace_id", "scope_id", "grantee_kind", "grantee_id", "role", "revoke", "idempotency_key", "personal_owner_user_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    GRANTEE_KIND_FIELD_NUMBER: _ClassVar[int]
    GRANTEE_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    REVOKE_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    PERSONAL_OWNER_USER_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    scope_id: str
    grantee_kind: str
    grantee_id: str
    role: str
    revoke: bool
    idempotency_key: str
    personal_owner_user_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., grantee_kind: _Optional[str] = ..., grantee_id: _Optional[str] = ..., role: _Optional[str] = ..., revoke: _Optional[bool] = ..., idempotency_key: _Optional[str] = ..., personal_owner_user_id: _Optional[str] = ...) -> None: ...

class ChangeScopeAccessResponse(_message.Message):
    __slots__ = ("workspace_id", "scope_id", "grantee_kind", "grantee_id", "rights")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    GRANTEE_KIND_FIELD_NUMBER: _ClassVar[int]
    GRANTEE_ID_FIELD_NUMBER: _ClassVar[int]
    RIGHTS_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    scope_id: str
    grantee_kind: str
    grantee_id: str
    rights: ScopeRights
    def __init__(self, workspace_id: _Optional[str] = ..., scope_id: _Optional[str] = ..., grantee_kind: _Optional[str] = ..., grantee_id: _Optional[str] = ..., rights: _Optional[_Union[ScopeRights, _Mapping]] = ...) -> None: ...

class CleanupLetaAccessRequest(_message.Message):
    __slots__ = ("workspace_id", "leta_id", "home_scope_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    LETA_ID_FIELD_NUMBER: _ClassVar[int]
    HOME_SCOPE_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    leta_id: str
    home_scope_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., leta_id: _Optional[str] = ..., home_scope_id: _Optional[str] = ...) -> None: ...

class CleanupLetaAccessResponse(_message.Message):
    __slots__ = ("completed",)
    COMPLETED_FIELD_NUMBER: _ClassVar[int]
    completed: bool
    def __init__(self, completed: _Optional[bool] = ...) -> None: ...
