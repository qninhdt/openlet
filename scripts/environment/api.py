"""Clerk development accounts for seed actors."""

from typing import Any, cast
from urllib.parse import quote

import httpx
from openlet_sdk.config import secret

type JSON = dict[str, Any]


class APIError(RuntimeError):
    def __init__(self, response: httpx.Response) -> None:
        self.status = response.status_code
        request = response.request
        super().__init__(f"{request.method} {request.url.path}: HTTP {self.status}")


def checked(response: httpx.Response) -> httpx.Response:
    if not response.is_success:
        raise APIError(response)
    return response


class Clerk:
    def __init__(
        self, http: httpx.Client, settings: dict[str, str], template: str
    ) -> None:
        self.http = http
        self.url = settings["api_url"].rstrip("/")
        key = secret(settings["secret_key"])
        if not key.startswith("sk_test_"):
            raise ValueError("seeding requires a Clerk development secret key")
        self.headers = {"Authorization": f"Bearer {key}"}
        self.template = quote(template, safe="")

    def request(
        self,
        method: str,
        path: str,
        *,
        json: JSON | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        return checked(
            self.http.request(
                method, self.url + path, headers=self.headers, json=json, params=params
            )
        )

    def account(self, external_id: str, profile: JSON | None = None) -> JSON:
        users = cast(
            list[JSON],
            self.request("GET", "/users", params={"external_id": external_id}).json(),
        )
        if len(users) > 1 or (users and users[0].get("external_id") != external_id):
            raise RuntimeError("Clerk returned an unexpected seed account")
        if users:
            return users[0]
        if profile is None:
            raise ValueError("seed this user before requesting a token")
        domain = profile.get("email", "seed@example.com").rsplit("@", 1)[-1]
        return cast(
            JSON,
            self.request(
                "POST",
                "/users",
                json={
                    "first_name": profile["first_name"],
                    "last_name": profile["last_name"],
                    "email_address": [f"{external_id}@{domain}"],
                    "external_id": external_id,
                    "skip_password_requirement": True,
                    "skip_legal_checks": True,
                },
            ).json(),
        )

    def session(self, subject: str) -> str:
        return cast(
            str,
            self.request("POST", "/sessions", json={"user_id": subject}).json()["id"],
        )

    def sync_metadata(self, user: JSON, key: str, user_id: str) -> None:
        metadata = cast(JSON, user.get("public_metadata") or {})
        if metadata.get(key) != user_id:
            self.request(
                "PATCH",
                f"/users/{user['id']}/metadata",
                json={"public_metadata": {key: user_id}},
            )

    def token(self, session: str) -> str:
        result: str = self.request(
            "POST", f"/sessions/{session}/tokens/{self.template}", json={}
        ).json()["jwt"]
        return result
