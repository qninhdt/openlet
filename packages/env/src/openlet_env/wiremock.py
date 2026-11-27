"""WireMock admin client for local JWKS, Clerk user stubs, and request assertions."""

from __future__ import annotations

from collections.abc import Mapping
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field

from .models import WireMockRequest


class _WireMockFindResponse(BaseModel):
    requests: list[WireMockRequest] = Field(default_factory=list[WireMockRequest])


class WireMockClient:
    """Thin HTTP client for WireMock's /__admin API."""

    def __init__(self, base_url: str, *, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout

    def register_mapping(self, mapping: Mapping[str, object]) -> None:
        response = httpx.post(
            f"{self.base_url}/__admin/mappings",
            json=mapping,
            timeout=self._timeout,
        )
        response.raise_for_status()

    def register_jwks(self, jwks: Mapping[str, object]) -> None:
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
        metadata: dict[str, str] = {user_id_claim: user_id} if user_id else {}
        profile: dict[str, object] = {
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

    def find_requests(self, criteria: Mapping[str, object]) -> list[WireMockRequest]:
        response = httpx.post(
            f"{self.base_url}/__admin/requests/find",
            json=criteria,
            timeout=self._timeout,
        )
        response.raise_for_status()
        parsed = _WireMockFindResponse.model_validate(response.json())
        return parsed.requests
