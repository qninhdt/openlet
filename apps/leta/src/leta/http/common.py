import asyncio
import base64
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from openlet.authz import AuthorizationClient, Resource, check
from openlet.clients.workspace import WorkspaceClient
from openlet.rpc import Actor
from pydantic import TypeAdapter
from temporalio.client import Client, WorkflowUpdateRPCTimeoutOrCancelledError
from temporalio.service import RPCError, RPCStatusCode

from leta.config import ModelCatalog
from leta.domain import ID, Input, TimeCursor, fault
from leta.store import Store

JSON = TypeAdapter(dict)
Limit = Annotated[int, Query(ge=1, le=100)]


def cursor_scope(*values):
    return hashlib.sha256(
        json.dumps(values, sort_keys=True, default=str).encode()
    ).hexdigest()


def read_cursor(cursor, scope, value_type=ID):
    if cursor is None:
        return None
    if len(cursor) > 4096:
        raise fault("VALIDATION", "invalid cursor", "invalid")
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if (
            not isinstance(value, dict)
            or set(value) != {"scope", "position"}
            or value["scope"] != scope
        ):
            raise ValueError("cursor belongs to another query")
        return TypeAdapter(value_type).validate_python(value["position"])
    except (ValueError, TypeError, UnicodeError) as error:
        raise fault(
            "VALIDATION", "cursor is invalid or belongs to another query", "invalid"
        ) from error


def write_cursor(position, scope):
    return (
        base64.urlsafe_b64encode(
            json.dumps(
                {"scope": scope, "position": position},
                default=str,
                separators=(",", ":"),
            ).encode()
        )
        .decode()
        .rstrip("=")
    )


def page(items, limit, scope, position):
    return {
        "items": items[:limit],
        "next_cursor": write_cursor(position(items[limit - 1]), scope)
        if len(items) > limit
        else None,
    }


@dataclass
class Context:
    request: Request
    store: Store
    scopes: WorkspaceClient
    temporal: Client
    authz: AuthorizationClient
    actor: Actor
    models: ModelCatalog

    async def root(self, leta_id: UUID, *, manage=False):
        root = await self.store.get_agent(leta_id, leta_id)
        if root["kind"] != "leta" or root["created_by_user_id"] != self.actor.id:
            raise fault("NOT_FOUND", "Leta not found", "missing")
        # leta.read/manage includes current Workspace membership in SpiceDB.
        if not await check(
            self.authz,
            self.actor,
            "manage" if manage else "read",
            Resource("leta", str(leta_id)),
        ):
            raise fault("FORBIDDEN", "Leta access denied", "forbidden")
        return root

    async def command(
        self,
        body: Input | None = None,
        *,
        resource_id: UUID | None = None,
        validate: Callable[[datetime], None] | None = None,
    ):
        keys = self.request.headers.getlist("idempotency-key")
        try:
            if len(keys) != 1:
                raise ValueError("exactly one Idempotency-Key is required")
            key = TypeAdapter(ID).validate_python(keys[0])
        except ValueError as error:
            raise fault(
                "VALIDATION", "one nonzero UUID Idempotency-Key is required", "invalid"
            ) from error
        payload = json.dumps(
            [
                self.request.method,
                self.request.url.path,
                body.model_dump(mode="json") if body is not None else None,
            ],
            sort_keys=True,
            separators=(",", ":"),
        )
        saved = await self.store.reserve_api_request(
            self.actor.id,
            key,
            hashlib.sha256(payload.encode()).hexdigest(),
            resource_id=resource_id,
            validate=validate,
        )
        return key, saved

    async def execute(self, call, *, resource_id: UUID, key: UUID | None = None):
        try:
            async with asyncio.timeout(20):
                result = await call
                if key is not None:
                    await self.store.complete_api_request(self.actor.id, key)
                return result
        except (
            TimeoutError,
            WorkflowUpdateRPCTimeoutOrCancelledError,
            RPCError,
        ) as error:
            if isinstance(error, RPCError) and error.status not in {
                RPCStatusCode.UNAVAILABLE,
                RPCStatusCode.DEADLINE_EXCEEDED,
            }:
                raise
            return JSONResponse(
                {
                    "status": "pending",
                    "resource_id": str(resource_id),
                    "idempotency_key": str(key) if key else None,
                    "detail": "Outcome is not yet known; look up the resource or "
                    "retry the same request.",
                },
                status_code=202,
            )


def api(request: Request) -> Context:
    resources = request.app.state.resources
    settings = request.app.state.settings
    return Context(
        request,
        Store(resources.database, settings.models),
        WorkspaceClient(resources.workspace),
        resources.temporal,
        resources.authz,
        request.state.principal.actor,
        settings.models,
    )


API = Annotated[Context, Depends(api)]


def time_position(row):
    return TimeCursor(at=row["created_at"], id=row["id"]).model_dump(mode="json")
