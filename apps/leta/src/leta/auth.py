from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass
from typing import Literal, cast
from uuid import UUID

import grpc.aio
from authzed.api.v1 import (
    CheckPermissionRequest,
    CheckPermissionResponse,
    Consistency,
    DeleteRelationshipsRequest,
    DeleteRelationshipsResponse,
    LookupResourcesRequest,
    LookupResourcesResponse,
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
    ZedToken,
)
from authzed.api.v1.permission_service_pb2_grpc import PermissionsServiceStub
from openlet_sdk.config import Config, secret


@dataclass(frozen=True, slots=True)
class Actor:
    type: Literal["user", "agent"]
    id: UUID

    @property
    def metadata(self) -> tuple[tuple[str, str], ...]:
        key = "x-openlet-user-id" if self.type == "user" else "x-openlet-agent-id"
        return ((key, str(self.id)),)

    def __str__(self) -> str:
        return f"{self.type}:{self.id}"


def obj_ref(kind: str, object_id: UUID | str) -> ObjectReference:
    return ObjectReference(object_type=kind, object_id=str(object_id))


def subj_ref(kind: str, object_id: UUID | str, relation: str = "") -> SubjectReference:
    return SubjectReference(object=obj_ref(kind, object_id), optional_relation=relation)


def relation(
    resource_type: str,
    resource_id: UUID | str,
    rel: str,
    subject_type: str,
    subject_id: UUID | str,
    subject_relation: str = "",
) -> Relationship:
    return Relationship(
        resource=obj_ref(resource_type, resource_id),
        relation=rel,
        subject=subj_ref(subject_type, subject_id, subject_relation),
    )


def touch(rel: Relationship) -> RelationshipUpdate:
    return RelationshipUpdate(
        operation=RelationshipUpdate.Operation.OPERATION_TOUCH,
        relationship=rel,
    )


def delete_rel(rel: Relationship) -> RelationshipUpdate:
    return RelationshipUpdate(
        operation=RelationshipUpdate.Operation.OPERATION_DELETE,
        relationship=rel,
    )


def consistency_for(zed_token: str | None) -> Consistency:
    if zed_token:
        return Consistency(at_least_as_fresh=ZedToken(token=zed_token))
    return Consistency(minimize_latency=True)


class Authorization:
    def __init__(self, channel: grpc.aio.Channel, token: str) -> None:
        self._channel = channel
        self._stub = PermissionsServiceStub(channel)
        self._headers = (("authorization", f"Bearer {token}"),)

    @classmethod
    def from_config(cls, cfg: Config) -> Authorization:
        s = cfg["dependencies"]["spicedb"]
        channel = (
            grpc.aio.secure_channel(s["address"], grpc.ssl_channel_credentials())
            if s["tls"]
            else grpc.aio.insecure_channel(s["address"])
        )
        return cls(channel, secret(s["key"]))

    async def close(self) -> None:
        await self._channel.close()

    async def allowed(
        self,
        actor: Actor,
        resource_type: str,
        resource_id: UUID | str,
        permission: str,
        *,
        zed_token: str | None = None,
    ) -> bool:
        call = cast(
            Awaitable[CheckPermissionResponse],
            self._stub.CheckPermission(
                CheckPermissionRequest(
                    resource=obj_ref(resource_type, resource_id),
                    permission=permission,
                    subject=subj_ref(actor.type, actor.id),
                    consistency=consistency_for(zed_token),
                ),
                metadata=self._headers,
                timeout=15,
            ),
        )
        resp = await call
        if resp.permissionship != CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION:
            retry_call = cast(
                Awaitable[CheckPermissionResponse],
                self._stub.CheckPermission(
                    CheckPermissionRequest(
                        resource=obj_ref(resource_type, resource_id),
                        permission=permission,
                        subject=subj_ref(actor.type, actor.id),
                        consistency=Consistency(fully_consistent=True),
                    ),
                    metadata=self._headers,
                    timeout=15,
                ),
            )
            resp = await retry_call
        return (
            resp.permissionship == CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION
        )

    async def require(
        self,
        actor: Actor,
        resource_type: str,
        resource_id: UUID | str,
        permission: str,
        *,
        zed_token: str | None = None,
    ) -> None:
        if not await self.allowed(
            actor, resource_type, resource_id, permission, zed_token=zed_token
        ):
            raise PermissionError(f"{resource_type}#{permission} denied")

    async def write(self, *updates: RelationshipUpdate) -> str:
        if not updates:
            return ""
        call = cast(
            Awaitable[WriteRelationshipsResponse],
            self._stub.WriteRelationships(
                WriteRelationshipsRequest(updates=list(updates)),
                metadata=self._headers,
                timeout=15,
            ),
        )
        resp = await call
        return str(resp.written_at.token)

    async def delete_filter(
        self,
        resource_type: str,
        resource_id: UUID | str | None = None,
        *,
        relation_name: str | None = None,
        subject_type: str | None = None,
        subject_id: UUID | str | None = None,
    ) -> None:
        flt = RelationshipFilter(
            resource_type=resource_type,
            optional_resource_id=str(resource_id) if resource_id is not None else "",
            optional_relation=relation_name or "",
        )
        if subject_type is not None:
            flt.optional_subject_filter.CopyFrom(
                SubjectFilter(
                    subject_type=subject_type,
                    optional_subject_id=str(subject_id) if subject_id else "",
                )
            )
        call = cast(
            Awaitable[DeleteRelationshipsResponse],
            self._stub.DeleteRelationships(
                DeleteRelationshipsRequest(relationship_filter=flt),
                metadata=self._headers,
                timeout=15,
            ),
        )
        await call

    async def read_relationships(
        self,
        resource_type: str,
        resource_id: UUID | str | None = None,
        *,
        relation_name: str | None = None,
        subject_type: str | None = None,
        subject_id: UUID | str | None = None,
        zed_token: str | None = None,
    ) -> list[Relationship]:
        flt = RelationshipFilter(
            resource_type=resource_type,
            optional_resource_id=str(resource_id) if resource_id is not None else "",
            optional_relation=relation_name or "",
        )
        if subject_type is not None:
            flt.optional_subject_filter.CopyFrom(
                SubjectFilter(
                    subject_type=subject_type,
                    optional_subject_id=str(subject_id) if subject_id else "",
                )
            )
        stream = cast(
            AsyncIterator[ReadRelationshipsResponse],
            self._stub.ReadRelationships(
                ReadRelationshipsRequest(
                    relationship_filter=flt,
                    consistency=consistency_for(zed_token),
                ),
                metadata=self._headers,
                timeout=15,
            ),
        )
        out: list[Relationship] = []
        async for item in stream:
            out.append(item.relationship)
        return out

    async def lookup_resources(
        self,
        actor: Actor,
        resource_type: str,
        permission: str,
        *,
        zed_token: str | None = None,
    ) -> list[str]:
        stream = cast(
            AsyncIterator[LookupResourcesResponse],
            self._stub.LookupResources(
                LookupResourcesRequest(
                    resource_object_type=resource_type,
                    permission=permission,
                    subject=subj_ref(actor.type, actor.id),
                    consistency=consistency_for(zed_token),
                ),
                metadata=self._headers,
                timeout=15,
            ),
        )
        out: list[str] = []
        async for item in stream:
            out.append(str(item.resource_object_id))
        return out
