from dataclasses import dataclass

from openlet.rpc import RpcClient
from openlet_api.account.v1 import account_pb2 as pb
from openlet_api.account.v1.account_pb2_grpc import AccountServiceStub


@dataclass(frozen=True)
class AccountSummary:
    id: str
    display_name: str
    avatar_url: str


class AccountClient:
    def __init__(self, rpc: RpcClient):
        self._rpc = rpc
        self._stub = AccountServiceStub(rpc.channel)

    async def get_account_summaries(self, ids: list[str]) -> tuple[AccountSummary, ...]:
        if not ids or len(ids) > 100 or len(set(ids)) != len(ids):
            raise ValueError("invalid user summary request")
        response = await self._rpc.invoke(
            self._stub.GetAccountSummaries, pb.GetAccountSummariesRequest(ids=ids)
        )
        users = tuple(
            AccountSummary(item.id, item.display_name, item.avatar_url)
            for item in response.accounts
        )
        if {item.id for item in users} != set(ids) or len(users) != len(ids):
            raise ValueError("account response does not match request")
        return users

    async def get_verified_emails(self, account_id: str) -> tuple[str, ...]:
        if not account_id:
            raise ValueError("account id is required")
        response = await self._rpc.invoke(
            self._stub.GetVerifiedEmails,
            pb.GetVerifiedEmailsRequest(account_id=account_id),
        )
        return tuple(response.emails)
