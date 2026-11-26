from buf.validate import validate_pb2 as _validate_pb2
from google.protobuf import empty_pb2 as _empty_pb2
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class SenderRef(_message.Message):
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

class DeliverInboxRequest(_message.Message):
    __slots__ = ("agent_id", "idempotency_key", "kind", "channel", "reply_address", "sender", "content", "attachments_json", "metadata_json", "silent")
    AGENT_ID_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    REPLY_ADDRESS_FIELD_NUMBER: _ClassVar[int]
    SENDER_FIELD_NUMBER: _ClassVar[int]
    CONTENT_FIELD_NUMBER: _ClassVar[int]
    ATTACHMENTS_JSON_FIELD_NUMBER: _ClassVar[int]
    METADATA_JSON_FIELD_NUMBER: _ClassVar[int]
    SILENT_FIELD_NUMBER: _ClassVar[int]
    agent_id: str
    idempotency_key: str
    kind: str
    channel: str
    reply_address: str
    sender: SenderRef
    content: str
    attachments_json: bytes
    metadata_json: bytes
    silent: bool
    def __init__(self, agent_id: _Optional[str] = ..., idempotency_key: _Optional[str] = ..., kind: _Optional[str] = ..., channel: _Optional[str] = ..., reply_address: _Optional[str] = ..., sender: _Optional[_Union[SenderRef, _Mapping]] = ..., content: _Optional[str] = ..., attachments_json: _Optional[bytes] = ..., metadata_json: _Optional[bytes] = ..., silent: _Optional[bool] = ...) -> None: ...

class DeleteWorkspaceAgentsRequest(_message.Message):
    __slots__ = ("workspace_id",)
    WORKSPACE_ID_FIELD_NUMBER: _ClassVar[int]
    workspace_id: str
    def __init__(self, workspace_id: _Optional[str] = ...) -> None: ...
