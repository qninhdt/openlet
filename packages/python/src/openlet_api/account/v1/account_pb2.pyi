from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AccountSummary(_message.Message):
    __slots__ = ("id", "display_name", "avatar_url")
    ID_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    AVATAR_URL_FIELD_NUMBER: _ClassVar[int]
    id: str
    display_name: str
    avatar_url: str
    def __init__(self, id: _Optional[str] = ..., display_name: _Optional[str] = ..., avatar_url: _Optional[str] = ...) -> None: ...

class GetAccountSummariesRequest(_message.Message):
    __slots__ = ("ids",)
    IDS_FIELD_NUMBER: _ClassVar[int]
    ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, ids: _Optional[_Iterable[str]] = ...) -> None: ...

class GetAccountSummariesResponse(_message.Message):
    __slots__ = ("accounts",)
    ACCOUNTS_FIELD_NUMBER: _ClassVar[int]
    accounts: _containers.RepeatedCompositeFieldContainer[AccountSummary]
    def __init__(self, accounts: _Optional[_Iterable[_Union[AccountSummary, _Mapping]]] = ...) -> None: ...

class GetVerifiedEmailsRequest(_message.Message):
    __slots__ = ("account_id",)
    ACCOUNT_ID_FIELD_NUMBER: _ClassVar[int]
    account_id: str
    def __init__(self, account_id: _Optional[str] = ...) -> None: ...

class GetVerifiedEmailsResponse(_message.Message):
    __slots__ = ("emails",)
    EMAILS_FIELD_NUMBER: _ClassVar[int]
    emails: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, emails: _Optional[_Iterable[str]] = ...) -> None: ...
