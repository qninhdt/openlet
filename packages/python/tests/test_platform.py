import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from authzed.api.v1 import (
    CheckBulkPermissionsPair,
    CheckBulkPermissionsResponse,
    CheckBulkPermissionsResponseItem,
    CheckPermissionResponse,
)
from google.rpc import status_pb2

from openlet.authz import Resource, bulk_check, check
from openlet.config import secret
from openlet.errors import AppError
from openlet.httpapi import problem_json
from openlet.identity import GatewayAuthenticationError, authenticate_gateway
from openlet.rpc import Authenticator, Credential
from openlet.temporal import application_error

ACTOR = "019a3b66-0000-7000-8000-000000000001"
METHOD = "/openlet_api.account.v1.AccountService/GetUserSummaries"
TOKEN = "isolated-owner-service-credential-12345"


def test_gateway_identity_and_rpc_delegation_are_separate_trust_boundaries():
    principal = authenticate_gateway(
        {
            "X-Gateway-Token": TOKEN,
            "X-Clerk-Sub": "subject",
            "X-Openlet-User-ID": ACTOR,
        },
        TOKEN,
    )
    assert principal.actor_id == UUID(ACTOR)
    with pytest.raises(GatewayAuthenticationError):
        authenticate_gateway({"X-Clerk-Sub": "subject"}, TOKEN)

    service = Authenticator(
        [Credential("workspace", TOKEN, frozenset({METHOD}), delegate_actor=True)]
    )
    delegated, failure = service.authenticate(
        (("authorization", f"Bearer {TOKEN}"), ("x-openlet-user-id", ACTOR)),
        METHOD,
    )
    assert failure is None
    assert delegated.actor_id == UUID(ACTOR)
    _, failure = Authenticator(
        [Credential("workspace", TOKEN, frozenset({METHOD}))]
    ).authenticate(
        (("authorization", f"Bearer {TOKEN}"), ("x-openlet-user-id", ACTOR)),
        METHOD,
    )
    assert failure is not None


def test_file_secret_precedence_and_problem_details(tmp_path, monkeypatch):
    path = tmp_path / "token"
    path.write_text(" file-value\n")
    monkeypatch.setenv("SERVICE_TOKEN", "environment-value")
    monkeypatch.setenv("SERVICE_TOKEN_FILE", str(path))
    assert secret("SERVICE_TOKEN") == "file-value"
    monkeypatch.setenv("SERVICE_TOKEN_FILE", str(Path(tmp_path) / "missing"))
    assert secret("SERVICE_TOKEN") == ""

    status, headers, body = problem_json(
        AppError(
            "payload is too large",
            reason="REQUEST_LIMIT",
            kind="limit",
            retryable=False,
        ),
        "request-1",
    )
    assert status == 413
    assert headers["content-type"] == "application/problem+json"
    assert body["code"] == "REQUEST_LIMIT"
    assert body["request_id"] == "request-1"
    assert (
        problem_json(
            AppError(
                "outside range",
                reason="OUT_OF_RANGE",
                kind="out_of_range",
                retryable=False,
            )
        )[0]
        == 400
    )


def test_shared_temporal_error_conversion_preserves_retry_policy():
    terminal = application_error(
        AppError(
            "invalid document",
            reason="DOCUMENT_INVALID",
            kind="invalid",
            retryable=False,
        ),
        fallback="PROCESSING_FAILED",
        message="processing failed",
    )
    assert terminal.type == "DOCUMENT_INVALID"
    assert terminal.non_retryable
    transient = application_error(
        RuntimeError("private dependency"),
        fallback="DEPENDENCY_UNAVAILABLE",
        message="processing failed",
    )
    assert transient.type == "DEPENDENCY_UNAVAILABLE"
    assert not transient.non_retryable


async def test_authz_uses_generated_action_resource_contract():
    class API:
        async def CheckPermission(self, request, **options):
            assert options["timeout"] == 2
            assert request.consistency.fully_consistent
            assert request.resource.object_type == "filesystem"
            assert request.permission == "node_read"
            return CheckPermissionResponse(
                permissionship=CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION
            )

    assert await check(API(), ACTOR, "node_read", Resource("filesystem", "drive"))
    with pytest.raises(ValueError, match="invalid authorization check"):
        await check(API(), ACTOR, "node_read", Resource("workspace", "drive"))


async def test_bulk_authz_preserves_order_and_rejects_mismatched_responses():
    resources = [Resource("filesystem", "one"), Resource("filesystem", "two")]

    class API:
        async def CheckBulkPermissions(self, request, **options):
            assert options["timeout"] == 2
            assert request.consistency.fully_consistent
            return CheckBulkPermissionsResponse(
                pairs=[
                    CheckBulkPermissionsPair(
                        request=request.items[1],
                        item=CheckBulkPermissionsResponseItem(
                            permissionship=(
                                CheckPermissionResponse.PERMISSIONSHIP_NO_PERMISSION
                            )
                        ),
                    ),
                    CheckBulkPermissionsPair(
                        request=request.items[0],
                        item=CheckBulkPermissionsResponseItem(
                            permissionship=(
                                CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION
                            )
                        ),
                    ),
                ]
            )

    assert await bulk_check(API(), ACTOR, "node_read", resources) == (True, False)

    class Mismatch:
        async def CheckBulkPermissions(self, request, **options):
            pair = CheckBulkPermissionsPair()
            pair.request.CopyFrom(request.items[0])
            pair.request.resource.object_id = "foreign"
            pair.item.permissionship = (
                CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION
            )
            return CheckBulkPermissionsResponse(pairs=[pair, pair])

    with pytest.raises(ValueError, match="does not match"):
        await bulk_check(Mismatch(), ACTOR, "node_read", resources)


async def test_bulk_authz_item_failure_is_dependency_failure():
    resources = [Resource("filesystem", "one")]

    class API:
        async def CheckBulkPermissions(self, request, **options):
            return CheckBulkPermissionsResponse(
                pairs=[
                    CheckBulkPermissionsPair(
                        request=request.items[0],
                        error=status_pb2.Status(code=13, message="private failure"),
                    )
                ]
            )

    with pytest.raises(AppError) as captured:
        await bulk_check(API(), ACTOR, "node_read", resources)
    assert captured.value.reason == "DEPENDENCY_UNAVAILABLE"
    assert "private" not in str(captured.value)


async def test_authz_does_not_translate_caller_cancellation():
    class API:
        async def CheckPermission(self, request, **options):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await check(API(), ACTOR, "node_read", Resource("filesystem", "drive"))


def test_vector_space_rejects_invalid_remote_index_configuration():
    from openlet.clients.letfs import VectorSpace

    VectorSpace("model", "files", 2).validate()
    for space in (
        VectorSpace(" ", "files", 2),
        VectorSpace("model", "../files", 2),
        VectorSpace("model", "files", 0),
        VectorSpace("model", "files", 65537),
    ):
        with pytest.raises(ValueError):
            space.validate()
