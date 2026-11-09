from dataclasses import dataclass

from openlet.rpc import RpcClient
from openlet_api.account.v1 import account_pb2 as pb
from openlet_api.account.v1.account_pb2_grpc import AccountServiceStub


@dataclass(frozen=True)
class UserSummary:
    id: str
    display_name: str
    avatar_url: str


class UserClient:
    def __init__(self, rpc: RpcClient):
        self._rpc = rpc
        self._stub = AccountServiceStub(rpc.channel)

    async def get_user_summaries(self, ids: list[str]) -> tuple[UserSummary, ...]:
        if not ids or len(ids) > 100 or len(set(ids)) != len(ids):
            raise ValueError("invalid user summary request")
        response = await self._rpc.invoke(
            self._stub.GetUserSummaries, pb.GetUserSummariesRequest(ids=ids)
        )
        users = tuple(
            UserSummary(item.id, item.display_name, item.avatar_url)
            for item in response.users
        )
        if {item.id for item in users} != set(ids) or len(users) != len(ids):
            raise ValueError("user response does not match request")
        return users

    async def get_verified_emails(self, user_id: str) -> tuple[str, ...]:
        if not user_id:
            raise ValueError("user id is required")
        response = await self._rpc.invoke(
            self._stub.GetVerifiedEmails,
            pb.GetVerifiedEmailsRequest(user_id=user_id),
        )
        return tuple(response.emails)
