from dataclasses import dataclass

from openlet.rpc import RpcClient
from openlet_api.workspace.v1 import workspace_pb2 as pb
from openlet_api.workspace.v1.workspace_pb2_grpc import (
    WorkspaceAdministrationServiceStub,
)


@dataclass(frozen=True)
class InitialWorkspace:
    id: str
    completed: bool


class WorkspaceClient:
    def __init__(self, rpc: RpcClient):
        self._rpc = rpc
        self._stub = WorkspaceAdministrationServiceStub(rpc.channel)

    async def ensure_initial_workspace(
        self, actor_id: str, request_key: str, name: str
    ) -> InitialWorkspace:
        response = await self._rpc.invoke(
            self._stub.EnsureInitialWorkspace,
            pb.EnsureInitialWorkspaceRequest(
                actor_id=actor_id, request_key=request_key, name=name
            ),
        )
        if not response.workspace_id:
            raise ValueError("workspace response is missing identity")
        return InitialWorkspace(response.workspace_id, response.completed)
