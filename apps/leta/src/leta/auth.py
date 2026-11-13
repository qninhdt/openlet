from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

import grpc
from authzed.api.v1 import (
    CheckPermissionRequest,
    CheckPermissionResponse,
    Consistency,
    Cursor,
    ObjectReference,
    ReadRelationshipsRequest,
    ReadRelationshipsResponse,
    Relationship,
    RelationshipFilter,
    RelationshipUpdate,
    SubjectFilter,
    SubjectReference,
    WriteRelationshipsRequest,
    WriteRelationshipsResponse,
)
from authzed.api.v1.permission_service_pb2_grpc import PermissionsServiceStub
from fastapi import HTTPException, Request
from openlet_api.platform.v1 import internal_pb2 as platform
from openlet_api.platform.v1.internal_pb2_grpc import PlatformInternalServiceStub
from openlet_sdk.config import JSON, Config, secret
from openlet_sdk.rpc import channel


@dataclass(frozen=True)
class Actor:
    kind: Literal["user", "agent"]
    id: UUID

    @property
    def metadata(self) -> tuple[tuple[str, str], ...]:
        return ((f"x-openlet-{self.kind}-id", str(self.id)),)

    def __str__(self) -> str:
        return f"{self.kind}:{self.id}"


def human(request: Request) -> Actor:
    users = request.headers.getlist("x-openlet-user-id")
    if len(users) != 1 or request.headers.get("x-openlet-agent-id"):
        raise HTTPException(401, "verified user identity required")
    try:
        return Actor("user", UUID(users[0]))
    except ValueError:
        raise HTTPException(401, "invalid user identity") from None


class Authorization:
    def __init__(self, config: Config) -> None:
        settings = config["dependencies"]["spicedb"]
        self.channel: grpc.aio.Channel = channel(
            settings["address"],
            tls=settings["tls"],
            max_bytes=config["grpc"]["max_receive_bytes"],
        )
        self.stub = PermissionsServiceStub(self.channel)
        self.metadata = (("authorization", "Bearer " + secret(settings["key"])),)

    async def allowed(self, actor: Actor, kind: str, id: UUID, permission: str) -> bool:
        result: CheckPermissionResponse = await cast(
            Awaitable[CheckPermissionResponse],
            self.stub.CheckPermission(
                CheckPermissionRequest(
                    resource=ObjectReference(object_type=kind, object_id=str(id)),
                    permission=permission,
                    subject=SubjectReference(
                        object=ObjectReference(
                            object_type=actor.kind, object_id=str(actor.id)
                        )
                    ),
                    consistency=Consistency(fully_consistent=True),
                ),
                metadata=self.metadata,
                timeout=10,
            ),
        )
        return (
            result.permissionship
            == CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION
        )

    async def require(self, actor: Actor, kind: str, id: UUID, permission: str) -> None:
        if not await self.allowed(actor, kind, id, permission):
            raise HTTPException(403, "permission denied")

    async def write(
        self, relationships: list[Relationship], *, delete: bool = False
    ) -> None:
        await cast(
            Awaitable[WriteRelationshipsResponse],
            self.stub.WriteRelationships(
                WriteRelationshipsRequest(
                    updates=[
                        RelationshipUpdate(
                            operation=RelationshipUpdate.OPERATION_DELETE
                            if delete
                            else RelationshipUpdate.OPERATION_TOUCH,
                            relationship=item,
                        )
                        for item in relationships
                    ]
                ),
                metadata=self.metadata,
                timeout=10,
            ),
        )

    async def members(
        self,
        platform_client: PlatformInternalServiceStub,
        workspace: UUID,
        cursor: str = "",
    ) -> dict[str, JSON]:
        stream = cast(
            AsyncIterator[ReadRelationshipsResponse],
            self.stub.ReadRelationships(
                ReadRelationshipsRequest(
                    relationship_filter=RelationshipFilter(
                        resource_type="workspace",
                        optional_resource_id=str(workspace),
                        optional_subject_filter=SubjectFilter(subject_type="user"),
                    ),
                    consistency=Consistency(fully_consistent=True),
                    optional_limit=20,
                    optional_cursor=Cursor(token=cursor) if cursor else None,
                ),
                metadata=self.metadata,
                timeout=10,
            ),
        )
        roles: dict[str, str] = {}
        next_cursor = ""
        async for result in stream:
            roles[result.relationship.subject.object.object_id] = (
                result.relationship.relation
            )
            next_cursor = result.after_result_cursor.token
        users: platform.BatchGetUsersResponse = await platform_client.BatchGetUsers(
            platform.BatchGetUsersRequest(user_ids=roles), timeout=15
        )
        return {
            "items": [
                {"user_id": user.id, "name": user.display_name, "role": roles[user.id]}
                for user in users.users
            ],
            "next_cursor": next_cursor if len(roles) == 20 else None,
        }


def relationship(
    kind: str, id: UUID, relation: str, subject_kind: str, subject_id: UUID
) -> Relationship:
    return Relationship(
        resource=ObjectReference(object_type=kind, object_id=str(id)),
        relation=relation,
        subject=SubjectReference(
            object=ObjectReference(object_type=subject_kind, object_id=str(subject_id))
        ),
    )
