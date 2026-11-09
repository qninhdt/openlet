import asyncio
from dataclasses import dataclass

import grpc
from authzed.api.v1 import (
    CheckBulkPermissionsRequest,
    CheckBulkPermissionsRequestItem,
    CheckPermissionRequest,
    CheckPermissionResponse,
    Client,
    Consistency,
    ObjectReference,
    SubjectReference,
)

from openlet._authz_actions import RESOURCE_ACTIONS
from openlet.errors import AppError
from openlet.rpc import Actor


@dataclass(frozen=True)
class Resource:
    type: str
    id: str


class AuthorizationClient(Client):
    def __init__(self, endpoint: str, token: str, *, allow_plaintext: bool = False):
        if not endpoint or not token:
            raise ValueError("invalid authorization configuration")
        self._openlet_channel = (
            grpc.aio.insecure_channel(endpoint)
            if allow_plaintext
            else grpc.aio.secure_channel(endpoint, grpc.ssl_channel_credentials())
        )
        self._openlet_metadata = (("authorization", f"Bearer {token}"),)
        self.init_stubs(self._openlet_channel)

    async def close(self):
        await self._openlet_channel.close()


def client(
    endpoint: str, token: str, *, allow_plaintext: bool = False
) -> AuthorizationClient:
    if not endpoint or not token:
        raise ValueError("invalid authorization configuration")
    return AuthorizationClient(endpoint, token, allow_plaintext=allow_plaintext)


def _request(actor: Actor, action: str, resource: Resource):
    if (
        not isinstance(actor, Actor)
        or not resource.id
        or action not in RESOURCE_ACTIONS.get(resource.type, ())
    ):
        raise ValueError("invalid authorization check")
    return CheckBulkPermissionsRequestItem(
        resource=ObjectReference(object_type=resource.type, object_id=resource.id),
        permission=action,
        subject=SubjectReference(
            object=ObjectReference(object_type=actor.kind, object_id=str(actor.id))
        ),
    )


def _dependency(error: Exception) -> AppError:
    return AppError(
        "authorization unavailable",
        reason="DEPENDENCY_UNAVAILABLE",
        kind="unavailable",
    )


async def check(api: Client, actor: Actor, action: str, resource: Resource) -> bool:
    item = _request(actor, action, resource)
    try:
        response = await api.CheckPermission(
            CheckPermissionRequest(
                consistency=Consistency(fully_consistent=True),
                resource=item.resource,
                permission=item.permission,
                subject=item.subject,
            ),
            metadata=getattr(api, "_openlet_metadata", ()),
            timeout=2,
        )
    except asyncio.CancelledError:
        raise
    except grpc.aio.AioRpcError as error:
        raise _dependency(error) from None
    return (
        response.permissionship == CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION
    )


async def bulk_check(
    api: Client,
    actor: Actor,
    action: str,
    resources: list[Resource],
) -> tuple[bool, ...]:
    if not resources or len(resources) > 100 or len(set(resources)) != len(resources):
        raise ValueError("invalid authorization check")
    items = tuple(_request(actor, action, resource) for resource in resources)
    indices = {resource: index for index, resource in enumerate(resources)}
    try:
        response = await api.CheckBulkPermissions(
            CheckBulkPermissionsRequest(
                consistency=Consistency(fully_consistent=True), items=items
            ),
            metadata=getattr(api, "_openlet_metadata", ()),
            timeout=2,
        )
    except asyncio.CancelledError:
        raise
    except grpc.aio.AioRpcError as error:
        raise _dependency(error) from None
    if len(response.pairs) != len(items):
        raise ValueError("authorization response does not match request")
    decisions = [False] * len(items)
    remaining = set(resources)
    for pair in response.pairs:
        resource = Resource(
            pair.request.resource.object_type,
            pair.request.resource.object_id,
        )
        index = indices.get(resource)
        if index is None or pair.request != items[index] or resource not in remaining:
            raise ValueError("authorization response does not match request")
        remaining.remove(resource)
        if pair.HasField("error") or not pair.HasField("item"):
            raise _dependency(RuntimeError("authorization item failed"))
        decisions[index] = (
            pair.item.permissionship
            == CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION
        )
    return tuple(decisions)
