import datetime

from buf.validate import validate_pb2 as _validate_pb2
from google.api import annotations_pb2 as _annotations_pb2
from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ChatActor(_message.Message):
    __slots__ = ("type", "id")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    type: str
    id: str
    def __init__(self, type: _Optional[str] = ..., id: _Optional[str] = ...) -> None: ...

class ConversationMember(_message.Message):
    __slots__ = ("actor_type", "actor_id", "role", "last_read_seq", "muted", "joined_at")
    ACTOR_TYPE_FIELD_NUMBER: _ClassVar[int]
    ACTOR_ID_FIELD_NUMBER: _ClassVar[int]
    ROLE_FIELD_NUMBER: _ClassVar[int]
    LAST_READ_SEQ_FIELD_NUMBER: _ClassVar[int]
    MUTED_FIELD_NUMBER: _ClassVar[int]
    JOINED_AT_FIELD_NUMBER: _ClassVar[int]
    actor_type: str
    actor_id: str
    role: str
    last_read_seq: int
    muted: bool
    joined_at: _timestamp_pb2.Timestamp
    def __init__(self, actor_type: _Optional[str] = ..., actor_id: _Optional[str] = ..., role: _Optional[str] = ..., last_read_seq: _Optional[int] = ..., muted: _Optional[bool] = ..., joined_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class MessagePreview(_message.Message):
    __slots__ = ("id", "seq", "sender_type", "sender_id", "snippet", "has_attachments")
    ID_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    SENDER_TYPE_FIELD_NUMBER: _ClassVar[int]
    SENDER_ID_FIELD_NUMBER: _ClassVar[int]
    SNIPPET_FIELD_NUMBER: _ClassVar[int]
    HAS_ATTACHMENTS_FIELD_NUMBER: _ClassVar[int]
    id: str
    seq: int
    sender_type: str
    sender_id: str
    snippet: str
    has_attachments: bool
    def __init__(self, id: _Optional[str] = ..., seq: _Optional[int] = ..., sender_type: _Optional[str] = ..., sender_id: _Optional[str] = ..., snippet: _Optional[str] = ..., has_attachments: _Optional[bool] = ...) -> None: ...

class Conversation(_message.Message):
    __slots__ = ("id", "workspace_id", "type", "handle", "title", "storage_id", "storage_ready", "last_seq", "last_msg_at", "last_message_preview", "unread_count", "created_by", "created_at", "members")
    ID_FIELD_NUMBER: _ClassVar[int]
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    TYPE_FIELD_NUMBER: _ClassVar[int]
    HANDLE_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_READY_FIELD_NUMBER: _ClassVar[int]
    LAST_SEQ_FIELD_NUMBER: _ClassVar[int]
    LAST_MSG_AT_FIELD_NUMBER: _ClassVar[int]
    LAST_MESSAGE_PREVIEW_FIELD_NUMBER: _ClassVar[int]
    UNREAD_COUNT_FIELD_NUMBER: _ClassVar[int]
    CREATED_BY_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    MEMBERS_FIELD_NUMBER: _ClassVar[int]
    id: str
    workspace_id: str
    type: str
    handle: str
    title: str
    storage_id: str
    storage_ready: bool
    last_seq: int
    last_msg_at: _timestamp_pb2.Timestamp
    last_message_preview: MessagePreview
    unread_count: int
    created_by: str
    created_at: _timestamp_pb2.Timestamp
    members: _containers.RepeatedCompositeFieldContainer[ConversationMember]
    def __init__(self, id: _Optional[str] = ..., workspace_id: _Optional[str] = ..., type: _Optional[str] = ..., handle: _Optional[str] = ..., title: _Optional[str] = ..., storage_id: _Optional[str] = ..., storage_ready: _Optional[bool] = ..., last_seq: _Optional[int] = ..., last_msg_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., last_message_preview: _Optional[_Union[MessagePreview, _Mapping]] = ..., unread_count: _Optional[int] = ..., created_by: _Optional[str] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., members: _Optional[_Iterable[_Union[ConversationMember, _Mapping]]] = ...) -> None: ...

class MessageAttachment(_message.Message):
    __slots__ = ("storage_id", "node_id", "kind", "name", "media_type", "size_bytes")
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    SIZE_BYTES_FIELD_NUMBER: _ClassVar[int]
    storage_id: str
    node_id: str
    kind: str
    name: str
    media_type: str
    size_bytes: int
    def __init__(self, storage_id: _Optional[str] = ..., node_id: _Optional[str] = ..., kind: _Optional[str] = ..., name: _Optional[str] = ..., media_type: _Optional[str] = ..., size_bytes: _Optional[int] = ...) -> None: ...

class MessageMention(_message.Message):
    __slots__ = ("kind", "id", "storage_id", "node_id", "label")
    KIND_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    LABEL_FIELD_NUMBER: _ClassVar[int]
    kind: str
    id: str
    storage_id: str
    node_id: str
    label: str
    def __init__(self, kind: _Optional[str] = ..., id: _Optional[str] = ..., storage_id: _Optional[str] = ..., node_id: _Optional[str] = ..., label: _Optional[str] = ...) -> None: ...

class MessageReaction(_message.Message):
    __slots__ = ("actor_type", "actor_id", "emoji", "created_at")
    ACTOR_TYPE_FIELD_NUMBER: _ClassVar[int]
    ACTOR_ID_FIELD_NUMBER: _ClassVar[int]
    EMOJI_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    actor_type: str
    actor_id: str
    emoji: str
    created_at: _timestamp_pb2.Timestamp
    def __init__(self, actor_type: _Optional[str] = ..., actor_id: _Optional[str] = ..., emoji: _Optional[str] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class Message(_message.Message):
    __slots__ = ("id", "conversation_id", "seq", "idempotency_key", "sender_type", "sender_id", "content", "reply_to_id", "attachments", "mentions", "metadata", "reactions", "created_at", "edited_at", "deleted_at")
    ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    SENDER_TYPE_FIELD_NUMBER: _ClassVar[int]
    SENDER_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    REPLY_TO_ID_FIELD_NUMBER: _ClassVar[int]
    ATTACHMENTS_FIELD_NUMBER: _ClassVar[int]
    MENTIONS_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    REACTIONS_FIELD_NUMBER: _ClassVar[int]
    CREATED_AT_FIELD_NUMBER: _ClassVar[int]
    EDITED_AT_FIELD_NUMBER: _ClassVar[int]
    DELETED_AT_FIELD_NUMBER: _ClassVar[int]
    id: str
    conversation_id: str
    seq: int
    idempotency_key: str
    sender_type: str
    sender_id: str
    content: str
    reply_to_id: str
    attachments: _containers.RepeatedCompositeFieldContainer[MessageAttachment]
    mentions: _containers.RepeatedCompositeFieldContainer[MessageMention]
    metadata: _struct_pb2.Struct
    reactions: _containers.RepeatedCompositeFieldContainer[MessageReaction]
    created_at: _timestamp_pb2.Timestamp
    edited_at: _timestamp_pb2.Timestamp
    deleted_at: _timestamp_pb2.Timestamp
    def __init__(self, id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., seq: _Optional[int] = ..., idempotency_key: _Optional[str] = ..., sender_type: _Optional[str] = ..., sender_id: _Optional[str] = ..., content: _Optional[str] = ..., reply_to_id: _Optional[str] = ..., attachments: _Optional[_Iterable[_Union[MessageAttachment, _Mapping]]] = ..., mentions: _Optional[_Iterable[_Union[MessageMention, _Mapping]]] = ..., metadata: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., reactions: _Optional[_Iterable[_Union[MessageReaction, _Mapping]]] = ..., created_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., edited_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., deleted_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class CreateOrGetDMRequest(_message.Message):
    __slots__ = ("workspace_id", "target")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    TARGET_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    target: ChatActor
    def __init__(self, workspace_id: _Optional[str] = ..., target: _Optional[_Union[ChatActor, _Mapping]] = ...) -> None: ...

class CreateGroupRequest(_message.Message):
    __slots__ = ("workspace_id", "title", "members", "handle")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    MEMBERS_FIELD_NUMBER: _ClassVar[int]
    HANDLE_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    title: str
    members: _containers.RepeatedCompositeFieldContainer[ChatActor]
    handle: str
    def __init__(self, workspace_id: _Optional[str] = ..., title: _Optional[str] = ..., members: _Optional[_Iterable[_Union[ChatActor, _Mapping]]] = ..., handle: _Optional[str] = ...) -> None: ...

class ListConversationsRequest(_message.Message):
    __slots__ = ("workspace_id", "page_size", "page_token")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    page_size: int
    page_token: str
    def __init__(self, workspace_id: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListAgentConversationsRequest(_message.Message):
    __slots__ = ("workspace_id", "agent_id", "page_size", "page_token")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_SIZE_FIELD_NUMBER: _ClassVar[int]
    PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    agent_id: str
    page_size: int
    page_token: str
    def __init__(self, workspace_id: _Optional[str] = ..., agent_id: _Optional[str] = ..., page_size: _Optional[int] = ..., page_token: _Optional[str] = ...) -> None: ...

class ListConversationsResponse(_message.Message):
    __slots__ = ("conversations", "next_page_token")
    CONVERSATIONS_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_TOKEN_FIELD_NUMBER: _ClassVar[int]
    conversations: _containers.RepeatedCompositeFieldContainer[Conversation]
    next_page_token: str
    def __init__(self, conversations: _Optional[_Iterable[_Union[Conversation, _Mapping]]] = ..., next_page_token: _Optional[str] = ...) -> None: ...

class ConversationRequest(_message.Message):
    __slots__ = ("workspace_id", "conversation_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    conversation_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ...) -> None: ...

class UpdateGroupRequest(_message.Message):
    __slots__ = ("workspace_id", "conversation_id", "title", "handle")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    HANDLE_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    conversation_id: str
    title: str
    handle: str
    def __init__(self, workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., title: _Optional[str] = ..., handle: _Optional[str] = ...) -> None: ...

class AddMembersRequest(_message.Message):
    __slots__ = ("workspace_id", "conversation_id", "members")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    MEMBERS_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    conversation_id: str
    members: _containers.RepeatedCompositeFieldContainer[ChatActor]
    def __init__(self, workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., members: _Optional[_Iterable[_Union[ChatActor, _Mapping]]] = ...) -> None: ...

class RemoveMemberRequest(_message.Message):
    __slots__ = ("workspace_id", "conversation_id", "actor_type", "actor_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    ACTOR_TYPE_FIELD_NUMBER: _ClassVar[int]
    ACTOR_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    conversation_id: str
    actor_type: str
    actor_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., actor_type: _Optional[str] = ..., actor_id: _Optional[str] = ...) -> None: ...

class EnsureConversationStorageResponse(_message.Message):
    __slots__ = ("storage_id", "root_node_id")
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    ROOT_NODE_ID_FIELD_NUMBER: _ClassVar[int]
    storage_id: str
    root_node_id: str
    def __init__(self, storage_id: _Optional[str] = ..., root_node_id: _Optional[str] = ...) -> None: ...

class SendMessageRequest(_message.Message):
    __slots__ = ("workspace_id", "conversation_id", "idempotency_key", "content", "reply_to_id", "attachments", "mentions", "metadata")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    REPLY_TO_ID_FIELD_NUMBER: _ClassVar[int]
    ATTACHMENTS_FIELD_NUMBER: _ClassVar[int]
    MENTIONS_FIELD_NUMBER: _ClassVar[int]
    METADATA_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    conversation_id: str
    idempotency_key: str
    content: str
    reply_to_id: str
    attachments: _containers.RepeatedCompositeFieldContainer[MessageAttachment]
    mentions: _containers.RepeatedCompositeFieldContainer[MessageMention]
    metadata: _struct_pb2.Struct
    def __init__(self, workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., content: _Optional[str] = ..., reply_to_id: _Optional[str] = ..., attachments: _Optional[_Iterable[_Union[MessageAttachment, _Mapping]]] = ..., mentions: _Optional[_Iterable[_Union[MessageMention, _Mapping]]] = ..., metadata: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class ListMessagesRequest(_message.Message):
    __slots__ = ("workspace_id", "conversation_id", "before_seq", "after_seq", "around_seq", "around_message_id", "limit", "query")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    BEFORE_SEQ_FIELD_NUMBER: _ClassVar[int]
    AFTER_SEQ_FIELD_NUMBER: _ClassVar[int]
    AROUND_SEQ_FIELD_NUMBER: _ClassVar[int]
    AROUND_MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    QUERY_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    conversation_id: str
    before_seq: int
    after_seq: int
    around_seq: int
    around_message_id: str
    limit: int
    query: str
    def __init__(self, workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., before_seq: _Optional[int] = ..., after_seq: _Optional[int] = ..., around_seq: _Optional[int] = ..., around_message_id: _Optional[str] = ..., limit: _Optional[int] = ..., query: _Optional[str] = ...) -> None: ...

class ListMessagesResponse(_message.Message):
    __slots__ = ("messages", "has_before", "has_after")
    MESSAGES_FIELD_NUMBER: _ClassVar[int]
    HAS_BEFORE_FIELD_NUMBER: _ClassVar[int]
    HAS_AFTER_FIELD_NUMBER: _ClassVar[int]
    messages: _containers.RepeatedCompositeFieldContainer[Message]
    has_before: bool
    has_after: bool
    def __init__(self, messages: _Optional[_Iterable[_Union[Message, _Mapping]]] = ..., has_before: _Optional[bool] = ..., has_after: _Optional[bool] = ...) -> None: ...

class EditMessageRequest(_message.Message):
    __slots__ = ("workspace_id", "conversation_id", "message_id", "content", "mentions")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    MENTIONS_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    conversation_id: str
    message_id: str
    content: str
    mentions: _containers.RepeatedCompositeFieldContainer[MessageMention]
    def __init__(self, workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., message_id: _Optional[str] = ..., content: _Optional[str] = ..., mentions: _Optional[_Iterable[_Union[MessageMention, _Mapping]]] = ...) -> None: ...

class DeleteMessageRequest(_message.Message):
    __slots__ = ("workspace_id", "conversation_id", "message_id")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    conversation_id: str
    message_id: str
    def __init__(self, workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., message_id: _Optional[str] = ...) -> None: ...

class ReactionRequest(_message.Message):
    __slots__ = ("workspace_id", "conversation_id", "message_id", "emoji")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    EMOJI_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    conversation_id: str
    message_id: str
    emoji: str
    def __init__(self, workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., message_id: _Optional[str] = ..., emoji: _Optional[str] = ...) -> None: ...

class MarkReadRequest(_message.Message):
    __slots__ = ("workspace_id", "conversation_id", "seq")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    conversation_id: str
    seq: int
    def __init__(self, workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., seq: _Optional[int] = ...) -> None: ...

class MarkReadResponse(_message.Message):
    __slots__ = ("last_read_seq",)
    LAST_READ_SEQ_FIELD_NUMBER: _ClassVar[int]
    last_read_seq: int
    def __init__(self, last_read_seq: _Optional[int] = ...) -> None: ...

class SetTypingRequest(_message.Message):
    __slots__ = ("workspace_id", "conversation_id", "active")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    conversation_id: str
    active: bool
    def __init__(self, workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., active: _Optional[bool] = ...) -> None: ...

class SidebarFolder(_message.Message):
    __slots__ = ("id", "name", "parent_id", "order")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    PARENT_ID_FIELD_NUMBER: _ClassVar[int]
    ORDER_FIELD_NUMBER: _ClassVar[int]
    id: str
    name: str
    parent_id: str
    order: int
    def __init__(self, id: _Optional[str] = ..., name: _Optional[str] = ..., parent_id: _Optional[str] = ..., order: _Optional[int] = ...) -> None: ...

class SidebarLayout(_message.Message):
    __slots__ = ("folders", "assignments", "pins", "order", "collapsed")
    class AssignmentsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    FOLDERS_FIELD_NUMBER: _ClassVar[int]
    ASSIGNMENTS_FIELD_NUMBER: _ClassVar[int]
    PINS_FIELD_NUMBER: _ClassVar[int]
    ORDER_FIELD_NUMBER: _ClassVar[int]
    COLLAPSED_FIELD_NUMBER: _ClassVar[int]
    folders: _containers.RepeatedCompositeFieldContainer[SidebarFolder]
    assignments: _containers.ScalarMap[str, str]
    pins: _containers.RepeatedScalarFieldContainer[str]
    order: _containers.RepeatedScalarFieldContainer[str]
    collapsed: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, folders: _Optional[_Iterable[_Union[SidebarFolder, _Mapping]]] = ..., assignments: _Optional[_Mapping[str, str]] = ..., pins: _Optional[_Iterable[str]] = ..., order: _Optional[_Iterable[str]] = ..., collapsed: _Optional[_Iterable[str]] = ...) -> None: ...

class GetSidebarRequest(_message.Message):
    __slots__ = ("workspace_id",)
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    def __init__(self, workspace_id: _Optional[str] = ...) -> None: ...

class UpdateSidebarRequest(_message.Message):
    __slots__ = ("workspace_id", "revision", "layout")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    REVISION_FIELD_NUMBER: _ClassVar[int]
    LAYOUT_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    revision: int
    layout: SidebarLayout
    def __init__(self, workspace_id: _Optional[str] = ..., revision: _Optional[int] = ..., layout: _Optional[_Union[SidebarLayout, _Mapping]] = ...) -> None: ...

class SidebarState(_message.Message):
    __slots__ = ("revision", "layout")
    REVISION_FIELD_NUMBER: _ClassVar[int]
    LAYOUT_FIELD_NUMBER: _ClassVar[int]
    revision: int
    layout: SidebarLayout
    def __init__(self, revision: _Optional[int] = ..., layout: _Optional[_Union[SidebarLayout, _Mapping]] = ...) -> None: ...

class GetRealtimeTokenRequest(_message.Message):
    __slots__ = ("workspace_id", "channel")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    channel: str
    def __init__(self, workspace_id: _Optional[str] = ..., channel: _Optional[str] = ...) -> None: ...

class RealtimeTokenResponse(_message.Message):
    __slots__ = ("token", "expires_at", "channel")
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    EXPIRES_AT_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    token: str
    expires_at: _timestamp_pb2.Timestamp
    channel: str
    def __init__(self, token: _Optional[str] = ..., expires_at: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., channel: _Optional[str] = ...) -> None: ...
