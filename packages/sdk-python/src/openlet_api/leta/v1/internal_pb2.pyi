from buf.validate import validate_pb2 as _validate_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ActorRef(_message.Message):
    __slots__ = ("type", "id", "name", "handle")
    TYPE_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    HANDLE_FIELD_NUMBER: _ClassVar[int]
    type: str
    id: str
    name: str
    handle: str
    def __init__(self, type: _Optional[str] = ..., id: _Optional[str] = ..., name: _Optional[str] = ..., handle: _Optional[str] = ...) -> None: ...

class ChatAttachment(_message.Message):
    __slots__ = ("storage_id", "node_id", "name", "media_type")
    STORAGE_ID_FIELD_NUMBER: _ClassVar[int]
    NODE_ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    MEDIA_TYPE_FIELD_NUMBER: _ClassVar[int]
    storage_id: str
    node_id: str
    name: str
    media_type: str
    def __init__(self, storage_id: _Optional[str] = ..., node_id: _Optional[str] = ..., name: _Optional[str] = ..., media_type: _Optional[str] = ...) -> None: ...

class ChatMention(_message.Message):
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

class ChatMessageEvent(_message.Message):
    __slots__ = ("workspace_id", "conversation_id", "conversation_type", "title", "handle", "message_id", "seq", "sender", "content", "reply_to_message_id", "attachments", "mentions", "metadata_json")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_TYPE_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    HANDLE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    SENDER_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    REPLY_TO_MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    ATTACHMENTS_FIELD_NUMBER: _ClassVar[int]
    MENTIONS_FIELD_NUMBER: _ClassVar[int]
    METADATA_JSON_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    conversation_id: str
    conversation_type: str
    title: str
    handle: str
    message_id: str
    seq: int
    sender: ActorRef
    content: str
    reply_to_message_id: str
    attachments: _containers.RepeatedCompositeFieldContainer[ChatAttachment]
    mentions: _containers.RepeatedCompositeFieldContainer[ChatMention]
    metadata_json: bytes
    def __init__(self, workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., conversation_type: _Optional[str] = ..., title: _Optional[str] = ..., handle: _Optional[str] = ..., message_id: _Optional[str] = ..., seq: _Optional[int] = ..., sender: _Optional[_Union[ActorRef, _Mapping]] = ..., content: _Optional[str] = ..., reply_to_message_id: _Optional[str] = ..., attachments: _Optional[_Iterable[_Union[ChatAttachment, _Mapping]]] = ..., mentions: _Optional[_Iterable[_Union[ChatMention, _Mapping]]] = ..., metadata_json: _Optional[bytes] = ...) -> None: ...

class ChatReactionEvent(_message.Message):
    __slots__ = ("workspace_id", "conversation_id", "message_id", "actor", "emoji", "action")
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    CONVERSATION_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_ID_FIELD_NUMBER: _ClassVar[int]
    ACTOR_FIELD_NUMBER: _ClassVar[int]
    EMOJI_FIELD_NUMBER: _ClassVar[int]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    conversation_id: str
    message_id: str
    actor: ActorRef
    emoji: str
    action: str
    def __init__(self, workspace_id: _Optional[str] = ..., conversation_id: _Optional[str] = ..., message_id: _Optional[str] = ..., actor: _Optional[_Union[ActorRef, _Mapping]] = ..., emoji: _Optional[str] = ..., action: _Optional[str] = ...) -> None: ...

class DeliverInboxRequest(_message.Message):
    __slots__ = ("agent_id", "idempotency_key", "chat_message", "chat_reaction")
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    CHAT_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    CHAT_REACTION_FIELD_NUMBER: _ClassVar[int]
    agent_id: str
    idempotency_key: str
    chat_message: ChatMessageEvent
    chat_reaction: ChatReactionEvent
    def __init__(self, agent_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., chat_message: _Optional[_Union[ChatMessageEvent, _Mapping]] = ..., chat_reaction: _Optional[_Union[ChatReactionEvent, _Mapping]] = ...) -> None: ...

class DeliverInboxResponse(_message.Message):
    __slots__ = ("delivered", "skipped", "seq")
    DELIVERED_FIELD_NUMBER: _ClassVar[int]
    SKIPPED_FIELD_NUMBER: _ClassVar[int]
    SEQ_FIELD_NUMBER: _ClassVar[int]
    delivered: bool
    skipped: bool
    seq: int
    def __init__(self, delivered: _Optional[bool] = ..., skipped: _Optional[bool] = ..., seq: _Optional[int] = ...) -> None: ...

class DeleteWorkspaceAgentsRequest(_message.Message):
    __slots__ = ("workspace_id",)
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    def __init__(self, workspace_id: _Optional[str] = ...) -> None: ...

class DeleteWorkspaceAgentsResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
