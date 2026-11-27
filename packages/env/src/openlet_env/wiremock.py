"""WireMock admin client for local JWKS, Clerk user stubs, and request assertions."""

from __future__ import annotations

from typing import TYPE_CHECKING, NotRequired, TypedDict
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

from openlet_env.models import WireMockRequest

if TYPE_CHECKING:
    from openlet_sdk.types import JsonObject

    from openlet_env.auth import Jwks


class ClerkVerification(TypedDict):
    """Clerk email verification status object."""

    status: str


class ClerkEmailAddress(TypedDict):
    """Clerk user email address entry."""

    id: str
    email_address: str
    verification: ClerkVerification


class ClerkUserProfile(TypedDict):
    """Stubbed Clerk ``/v1/users`` response payload."""

    id: str
    first_name: str
    last_name: str
    image_url: str
    email_addresses: list[ClerkEmailAddress]
    public_metadata: dict[str, str]


class WireMockMappingRequest(TypedDict):
    """WireMock stub request matcher."""

    method: str
    urlPath: str


class WireMockMappingResponse(TypedDict):
    """WireMock stub HTTP JSON response definition."""

    status: int
    jsonBody: Jwks | ClerkUserProfile | JsonObject
    headers: dict[str, str]


class WireMockMapping(TypedDict):
    """WireMock ``/__admin/mappings`` registration payload."""

    priority: NotRequired[int]
    request: WireMockMappingRequest
    response: WireMockMappingResponse


class WireMockBodyPattern(TypedDict, total=False):
    """WireMock request body match pattern."""

    contains: str
    equalTo: str
    matches: str
    equalToJson: str


class WireMockRequestCriteria(TypedDict, total=False):
    """WireMock ``/__admin/requests/find`` query criteria."""

    method: str
    urlPath: str
    url: str
    urlPattern: str
    bodyPatterns: list[WireMockBodyPattern]


class _WireMockFindResponse(BaseModel):
    requests: list[WireMockRequest] = Field(default_factory=list[WireMockRequest])


class WireMockClient:
    """Thin HTTP client for WireMock's /__admin API."""

    def __init__(self, base_url: str, *, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout

    def register_mapping(self, mapping: WireMockMapping | JsonObject) -> None:
        """Register a dynamic WireMock stub mapping."""
        response = httpx.post(
            f"{self.base_url}/__admin/mappings",
            json=mapping,
            timeout=self._timeout,
        )
        response.raise_for_status()

    def register_jwks(self, jwks: Jwks | JsonObject) -> None:
        """Register the local JWKS endpoint stub."""
        self.register_mapping(
            {
                "priority": 1,
                "request": {"method": "GET", "urlPath": "/.well-known/jwks.json"},
                "response": {
                    "status": 200,
                    "jsonBody": jwks,
                    "headers": {"Content-Type": "application/json"},
                },
            }
        )

    def register_clerk_user(
        self,
        *,
        subject: str,
        email: str,
        first_name: str,
        last_name: str,
        user_id: str | None = None,
        user_id_claim: str = "openlet_user_id",
    ) -> None:
        """Register Clerk user GET and metadata PATCH stubs for ``subject``."""
        metadata: dict[str, str] = {user_id_claim: user_id} if user_id else {}
        profile: ClerkUserProfile = {
            "id": subject,
            "first_name": first_name,
            "last_name": last_name,
            "image_url": "",
            "email_addresses": [
                {
                    "id": str(uuid4()),
                    "email_address": email,
                    "verification": {"status": "verified"},
                }
            ],
            "public_metadata": metadata,
        }
        for method, path in (
            ("GET", f"/v1/users/{subject}"),
            ("PATCH", f"/v1/users/{subject}/metadata"),
        ):
            self.register_mapping(
                {
                    "priority": 1,
                    "request": {"method": method, "urlPath": path},
                    "response": {
                        "status": 200,
                        "jsonBody": profile,
                        "headers": {"Content-Type": "application/json"},
                    },
                }
            )

    def find_requests(
        self, criteria: WireMockRequestCriteria | JsonObject
    ) -> list[WireMockRequest]:
        """Query WireMock's request journal for matching recorded requests."""
        response = httpx.post(
            f"{self.base_url}/__admin/requests/find",
            json=criteria,
            timeout=self._timeout,
        )
        response.raise_for_status()
        parsed = _WireMockFindResponse.model_validate(response.json())
        return parsed.requests
