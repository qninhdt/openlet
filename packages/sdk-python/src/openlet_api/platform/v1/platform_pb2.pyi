import datetime

from google.api import annotations_pb2 as _annotations_pb2
from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from buf.validate import validate_pb2 as _validate_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class WorkspaceRole(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WORKSPACE_ROLE_UNSPECIFIED: _ClassVar[WorkspaceRole]
    WORKSPACE_ROLE_OWNER: _ClassVar[WorkspaceRole]
    WORKSPACE_ROLE_MEMBER: _ClassVar[WorkspaceRole]

class WorkspaceState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    WORKSPACE_STATE_UNSPECIFIED: _ClassVar[WorkspaceState]
    WORKSPACE_STATE_PROVISIONING: _ClassVar[WorkspaceState]
    WORKSPACE_STATE_ACTIVE: _ClassVar[WorkspaceState]
    WORKSPACE_STATE_DELETING: _ClassVar[WorkspaceState]
WORKSPACE_ROLE_UNSPECIFIED: WorkspaceRole
WORKSPACE_ROLE_OWNER: WorkspaceRole
WORKSPACE_ROLE_MEMBER: WorkspaceRole
WORKSPACE_STATE_UNSPECIFIED: WorkspaceState
WORKSPACE_STATE_PROVISIONING: WorkspaceState
WORKSPACE_STATE_ACTIVE: WorkspaceState
WORKSPACE_STATE_DELETING: WorkspaceState

class AvatarAppearance(_message.Message):
    __slots__ = ("shape", "color")
    SHAPE_FIELD_NUMBER: _ClassVar[int]
    COLOR_FIELD_NUMBER: _ClassVar[int]
    shape: str
    color: str
    def __init__(self, shape: _Optional[str] = ..., color: _Optional[str] = ...) -> None: ...

class AccountPreferences(_message.Message):
    __slots__ = ("theme", "send_shortcut", "show_agent_steps", "compact_message_actions", "message_sound")
    THEME_FIELD_NUMBER: _ClassVar[int]
    SEND_SHORTCUT_FIELD_NUMBER: _ClassVar[int]
    SHOW_AGENT_STEPS_FIELD_NUMBER: _ClassVar[int]
    COMPACT_MESSAGE_ACTIONS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_SOUND_FIELD_NUMBER: _ClassVar[int]
    theme: str
    send_shortcut: str
    show_agent_steps: bool
    compact_message_actions: bool
    message_sound: bool
    def __init__(self, theme: _Optional[str] = ..., send_shortcut: _Optional[str] = ..., show_agent_steps: _Optional[bool] = ..., compact_message_actions: _Optional[bool] = ..., message_sound: _Optional[bool] = ...) -> None: ...

class User(_message.Message):
    __slots__ = ("id", "display_name", "avatar_url", "appearance", "preferences", "handle")
    ID_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    AVATAR_URL_FIELD_NUMBER: _ClassVar[int]
    APPEARANCE_FIELD_NUMBER: _ClassVar[int]
    PREFERENCES_FIELD_NUMBER: _ClassVar[int]
    HANDLE_FIELD_NUMBER: _ClassVar[int]
    id: str
    display_name: str
    avatar_url: str
    appearance: AvatarAppearance
    preferences: AccountPreferences
    handle: str
    def __init__(self, id: _Optional[str] = ..., display_name: _Optional[str] = ..., avatar_url: _Optional[str] = ..., appearance: _Optional[_Union[AvatarAppearance, _Mapping]] = ..., preferences: _Optional[_Union[AccountPreferences, _Mapping]] = ..., handle: _Optional[str] = ...) -> None: ...

class Workspace(_message.Message):
    __slots__ = ("id", "name", "state", "created_at", "role")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    state: WorkspaceState
    created_at: _timestamp_pb2.Timestamp
    role: WorkspaceRole
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., state: _Optional[_Union[WorkspaceState, str]] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., role: _Optional[_Union[WorkspaceRole, str]] = ...) -> None: ...

class WorkspaceMember(_message.Message):
    __slots__ = ("user", "role", "workspace_id")
    USER_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    user: User
    role: WorkspaceRole
    workspace_id: str
    def __init__(self, user: _Optional[_Union[User, _Mapping]] = ..., role: _Optional[_Union[WorkspaceRole, str]] = ..., workspace_id: _Optional[str] = ...) -> None: ...

class Invitation(_message.Message):
    __slots__ = ("id", "workspace_id", "email", "expires_at", "accepted_by_user_id")
    ID_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    ACCEPTED_BY_USER_ID_FIELD_NUMBER: _ClassVar[int]
    id: str
    workspace_id: str
    email: str
    expires_at: _timestamp_pb2.Timestamp
    accepted_by_user_id: str
    def __init__(self, id: _Optional[str] = ..., workspace_id: _Optional[str] = ..., email: _Optional[str] = ..., expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., accepted_by_user_id: _Optional[str] = ...) -> None: ...

class UpdateMeRequest(_message.Message):
    __slots__ = ("display_name", "avatar_url", "appearance", "preferences")
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    AVATAR_URL_FIELD_NUMBER: _ClassVar[int]
    APPEARANCE_FIELD_NUMBER: _ClassVar[int]
    PREFERENCES_FIELD_NUMBER: _ClassVar[int]
    display_name: str
    avatar_url: str
    appearance: AvatarAppearance
    preferences: AccountPreferences
    def __init__(self, display_name: _Optional[str] = ..., avatar_url: _Optional[str] = ..., appearance: _Optional[_Union[AvatarAppearance, _Mapping]] = ..., preferences: _Optional[_Union[AccountPreferences, _Mapping]] = ...) -> None: ...

class ListWorkspacesRequest(_message.Message):
    __slots__ = ("page_size", "page_token")
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    page_size: int
    page_token: str
    def __init__(self, page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListWorkspacesResponse(_message.Message):
    __slots__ = ("workspaces", "next_page_token")
    WORKSPACES_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    workspaces: _containers.RepeatedCompositeFieldContainer[Workspace]
    next_page_token: str
    def __init__(self, workspaces: _Optional[_Iterable[_Union[Workspace, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class CreateMyWorkspaceRequest(_message.Message):
    __slots__ = ("name", "request_id")
    NAME_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    name: str
    request_id: str
    def __init__(self, name: _Optional[str] = ..., request_id: _Optional[str] = ...) -> None: ...

class WorkspaceRequest(_message.Message):
    __slots__ = ("workspace_id",)
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    def __init__(self, workspace_id: _Optional[str] = ...) -> None: ...

class UpdateWorkspaceRequest(_message.Message):
    __slots__ = ("workspace_id", "name")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    name: str
    def __init__(self, workspace_id: _Optional[str] = ..., name: _Optional[str] = ...) -> None: ...

class TransferWorkspaceOwnershipRequest(_message.Message):
    __slots__ = ("workspace_id", "new_owner_user_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    NEW_OWNER_USER_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    new_owner_user_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., new_owner_user_id: _Optional[str] = ...) -> None: ...

class ListMembersRequest(_message.Message):
    __slots__ = ("workspace_id", "page_size", "page_token")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    page_size: int
    page_token: str
    def __init__(self, workspace_id: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListMembersResponse(_message.Message):
    __slots__ = ("members", "next_page_token")
    MEMBERS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    members: _containers.RepeatedCompositeFieldContainer[WorkspaceMember]
    next_page_token: str
    def __init__(self, members: _Optional[_Iterable[_Union[WorkspaceMember, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class AddMemberRequest(_message.Message):
    __slots__ = ("workspace_id", "user_id", "request_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    user_id: str
    request_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., user_id: _Optional[str] = ..., request_id: _Optional[str] = ...) -> None: ...

class RemoveMemberRequest(_message.Message):
    __slots__ = ("workspace_id", "user_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    user_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., user_id: _Optional[str] = ...) -> None: ...

class CreateInvitationRequest(_message.Message):
    __slots__ = ("workspace_id", "email", "request_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    EMAIL_FIELD_NUMBER: _ClassVar[int]
    REQUEST_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    email: str
    request_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., email: _Optional[str] = ..., request_id: _Optional[str] = ...) -> None: ...

class CreateInvitationResponse(_message.Message):
    __slots__ = ("invitation", "token")
    INVITATION_FIELD_NUMBER: _ClassVar[int]
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    invitation: Invitation
    token: str
    def __init__(self, invitation: _Optional[_Union[Invitation, _Mapping]] = ..., token: _Optional[str] = ...) -> None: ...

class ListInvitationsRequest(_message.Message):
    __slots__ = ("workspace_id", "page_size", "page_token")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    page_size: int
    page_token: str
    def __init__(self, workspace_id: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListInvitationsResponse(_message.Message):
    __slots__ = ("invitations", "next_page_token")
    INVITATIONS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    invitations: _containers.RepeatedCompositeFieldContainer[Invitation]
    next_page_token: str
    def __init__(self, invitations: _Optional[_Iterable[_Union[Invitation, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class RevokeInvitationRequest(_message.Message):
    __slots__ = ("workspace_id", "invitation_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    INVITATION_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    invitation_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., invitation_id: _Optional[str] = ...) -> None: ...

class AcceptInvitationRequest(_message.Message):
    __slots__ = ("token",)
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    token: str
    def __init__(self, token: _Optional[str] = ...) -> None: ...

class RealtimeConnectToken(_message.Message):
    __slots__ = ("token", "expires_at", "user_id")
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    token: str
    expires_at: _timestamp_pb2.Timestamp
    user_id: str
    def __init__(self, token: _Optional[str] = ..., expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., user_id: _Optional[str] = ...) -> None: ...
