"""SpiceDB authorization client and relationship helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, cast, override

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

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable
    from uuid import UUID


@dataclass(frozen=True, slots=True)
class Actor:
    """Authenticated principal performing a permission-checked operation."""

    type: Literal["user", "agent"]
    id: UUID

    @property
    def metadata(self) -> tuple[tuple[str, str], ...]:
        """Return gRPC metadata headers identifying this actor."""
        key = "x-openlet-user-id" if self.type == "user" else "x-openlet-agent-id"
        return ((key, str(self.id)),)

    @override
    def __str__(self) -> str:
        return f"{self.type}:{self.id}"


def obj_ref(kind: str, object_id: UUID | str) -> ObjectReference:
    """Build a SpiceDB ObjectReference."""
    return ObjectReference(object_type=kind, object_id=str(object_id))


def subj_ref(kind: str, object_id: UUID | str, relation: str = "") -> SubjectReference:
    """Build a SpiceDB SubjectReference."""
    return SubjectReference(object=obj_ref(kind, object_id), optional_relation=relation)


def relation(
    resource_type: str,
    resource_id: UUID | str,
    rel: str,
    subject_type: str,
    subject_id: UUID | str,
    *,
    subject_relation: str = "",
) -> Relationship:
    """Build a SpiceDB Relationship tuple."""
    return Relationship(
        resource=obj_ref(resource_type, resource_id),
        relation=rel,
        subject=subj_ref(subject_type, subject_id, subject_relation),
    )


def touch(rel: Relationship) -> RelationshipUpdate:
    """Create an idempotent TOUCH update for a SpiceDB relationship."""
    return RelationshipUpdate(
        operation=RelationshipUpdate.Operation.OPERATION_TOUCH,
        relationship=rel,
    )


def delete_rel(rel: Relationship) -> RelationshipUpdate:
    """Create a DELETE update for a SpiceDB relationship."""
    return RelationshipUpdate(
        operation=RelationshipUpdate.Operation.OPERATION_DELETE,
        relationship=rel,
    )


def consistency_for(zed_token: str | None) -> Consistency:
    """Return SpiceDB Consistency using a ZedToken when provided or minimize_latency."""
    if zed_token:
        return Consistency(at_least_as_fresh=ZedToken(token=zed_token))
    return Consistency(minimize_latency=True)


class _AsyncPermissionsStub(Protocol):
    """Async view of authzed PermissionsServiceStub (upstream generates sync-only stubs)."""

    def CheckPermission(  # noqa: N802  # Matches upstream authzed gRPC stub method name
        self,
        request: CheckPermissionRequest,
        *,
        metadata: tuple[tuple[str, str], ...],
        timeout: float,
    ) -> Awaitable[CheckPermissionResponse]: ...

    def WriteRelationships(  # noqa: N802  # Matches upstream authzed gRPC stub method name
        self,
        request: WriteRelationshipsRequest,
        *,
        metadata: tuple[tuple[str, str], ...],
        timeout: float,
    ) -> Awaitable[WriteRelationshipsResponse]: ...

    def DeleteRelationships(  # noqa: N802  # Matches upstream authzed gRPC stub method name
        self,
        request: DeleteRelationshipsRequest,
        *,
        metadata: tuple[tuple[str, str], ...],
        timeout: float,
    ) -> Awaitable[DeleteRelationshipsResponse]: ...

    def ReadRelationships(  # noqa: N802  # Matches upstream authzed gRPC stub method name
        self,
        request: ReadRelationshipsRequest,
        *,
        metadata: tuple[tuple[str, str], ...],
        timeout: float,
    ) -> AsyncIterator[ReadRelationshipsResponse]: ...

    def LookupResources(  # noqa: N802  # Matches upstream authzed gRPC stub method name
        self,
        request: LookupResourcesRequest,
        *,
        metadata: tuple[tuple[str, str], ...],
        timeout: float,
    ) -> AsyncIterator[LookupResourcesResponse]: ...


class Authorization:
    """Async SpiceDB authorization client for checking and mutating relationships."""

    def __init__(self, channel: grpc.aio.Channel, token: str) -> None:
        self._channel = channel
        # authzed's generated PermissionsServiceStub types RPCs synchronously even on grpc.aio.Channel.
        self._stub: _AsyncPermissionsStub = cast(
            "_AsyncPermissionsStub", PermissionsServiceStub(channel)
        )
        self._headers = (("authorization", f"Bearer {token}"),)

    @classmethod
    def from_config(cls, cfg: Config) -> Authorization:
        """Create an Authorization client from Openlet SpiceDB dependency config."""
        s = cfg["dependencies"]["spicedb"]
        channel = (
            grpc.aio.secure_channel(s["address"], grpc.ssl_channel_credentials())
            if s["tls"]
            else grpc.aio.insecure_channel(s["address"])
        )
        return cls(channel, secret(s["key"]))

    async def close(self) -> None:
        """Close the underlying gRPC channel."""
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
        """Return whether actor holds permission on the target resource."""
        resp = await self._stub.CheckPermission(
            CheckPermissionRequest(
                resource=obj_ref(resource_type, resource_id),
                permission=permission,
                subject=subj_ref(actor.type, actor.id),
                consistency=consistency_for(zed_token),
            ),
            metadata=self._headers,
            timeout=15,
        )
        if resp.permissionship != CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION:
            resp = await self._stub.CheckPermission(
                CheckPermissionRequest(
                    resource=obj_ref(resource_type, resource_id),
                    permission=permission,
                    subject=subj_ref(actor.type, actor.id),
                    consistency=Consistency(fully_consistent=True),
                ),
                metadata=self._headers,
                timeout=15,
            )
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
        """Raise PermissionError if actor lacks permission on the resource."""
        if not await self.allowed(
            actor, resource_type, resource_id, permission, zed_token=zed_token
        ):
            raise PermissionError(f"{resource_type}#{permission} denied")

    async def write(self, *updates: RelationshipUpdate) -> str:
        """Write relationship updates to SpiceDB and return the resulting ZedToken."""
        if not updates:
            return ""
        resp = await self._stub.WriteRelationships(
            WriteRelationshipsRequest(updates=list(updates)),
            metadata=self._headers,
            timeout=15,
        )
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
        """Delete SpiceDB relationships matching the provided filter criteria."""
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
        await self._stub.DeleteRelationships(
            DeleteRelationshipsRequest(relationship_filter=flt),
            metadata=self._headers,
            timeout=15,
        )

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
        """Read SpiceDB relationships matching the provided filter criteria."""
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
        stream = self._stub.ReadRelationships(
            ReadRelationshipsRequest(
                relationship_filter=flt,
                consistency=consistency_for(zed_token),
            ),
            metadata=self._headers,
            timeout=15,
        )
        return [item.relationship async for item in stream]

    async def lookup_resources(
        self,
        actor: Actor,
        resource_type: str,
        permission: str,
        *,
        zed_token: str | None = None,
    ) -> list[str]:
        """List resource IDs of resource_type for which actor has permission."""
        stream = self._stub.LookupResources(
            LookupResourcesRequest(
                resource_object_type=resource_type,
                permission=permission,
                subject=subj_ref(actor.type, actor.id),
                consistency=consistency_for(zed_token),
            ),
            metadata=self._headers,
            timeout=15,
        )
        return [str(item.resource_object_id) async for item in stream]
