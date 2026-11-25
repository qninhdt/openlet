"""Session-scoped shared openlet_env fixture supporting pytest-xdist parallel workers."""

from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from openlet_env import Environment

DATASET_DIR = Path(__file__).resolve().parent / "dataset"
SAMPLE_FILES_DIR = DATASET_DIR / "workspaces/acme-review/storages/shared"


def poll[T](
    fn: Callable[[], T],
    *,
    timeout: float = 30.0,
    interval: float = 0.25,
    desc: str = "condition",
) -> T:
    """Poll until fn() returns a truthy value or raise AssertionError on timeout."""
    deadline = time.monotonic() + timeout
    last_error: BaseException | None = None
    last_value: object = None
    while True:
        try:
            value = fn()
            if value:
                return value
            last_value = value
        except AssertionError as exc:
            last_error = exc
        if time.monotonic() >= deadline:
            detail = (
                f"last error: {last_error}"
                if last_error is not None
                else f"last value: {last_value!r}"
            )
            raise AssertionError(
                f"Timed out waiting for {desc} after {timeout}s ({detail})"
            )
        time.sleep(interval)


@dataclass(slots=True)
class AccountFixture:
    api: httpx.Client
    id: str
    workspace_id: str
    storage_id: str
    root_id: str
    email: str
    subject: str
    token: str


class AccountFactory:
    def __init__(self, env: Environment) -> None:
        self.env = env
        self._clients: list[httpx.Client] = []

    def sign(self, subject: str, user_id: str | None = None) -> str:
        return self.env.auth.sign(subject, user_id)

    def create(self) -> AccountFixture:
        acct, extra = self.env.create_account(create_workspace=True)
        workspace_id = extra["workspace_id"]
        zed_token = extra["zed_token"]
        assert zed_token, "workspace creation must return x-openlet-zed-token"

        client = httpx.Client(
            base_url=self.env.endpoints.api_url,
            headers={
                "Authorization": f"Bearer {acct.token}",
                "x-openlet-zed-token": zed_token,
            },
            timeout=30.0,
        )
        self._clients.append(client)

        def find_private_storage() -> dict[str, Any] | None:
            resp = client.get(f"/v1/workspaces/{workspace_id}/storages?owned_only=true")
            if resp.status_code != 200:
                return None
            storages = cast(list[dict[str, Any]], resp.json().get("storages", []))
            for item in storages:
                if item.get("visibility") == "STORAGE_VISIBILITY_PRIVATE":
                    return item
            return None

        storage = poll(
            find_private_storage, timeout=30.0, desc="private storage provisioning"
        )
        assert storage is not None
        return AccountFixture(
            api=client,
            id=acct.user_id,
            workspace_id=workspace_id,
            storage_id=str(storage["id"]),
            root_id=str(storage["rootNodeId"]),
            email=acct.email,
            subject=acct.clerk_user_id,
            token=acct.token,
        )

    def close(self) -> None:
        for client in self._clients:
            client.close()


def _is_gateway_healthy(env: Environment) -> bool:
    if not env.stack.state_path.is_file():
        return False
    try:
        resp = httpx.get(f"{env.endpoints.api_url}/v1/workspaces", timeout=2.0)
        return resp.status_code == 401
    except Exception:
        return False


@pytest.fixture(scope="session")
def openlet_env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Environment]:
    """Start one shared mock Openlet stack across all xdist workers."""
    keep = os.environ.get("OPENLET_E2E_KEEP", "") == "1"
    build = os.environ.get("OPENLET_E2E_BUILD", "") == "1"
    project = os.environ.get("OPENLET_E2E_PROJECT", "e2e")

    coord_dir = tmp_path_factory.getbasetemp().parent
    lock_file = coord_dir / "openlet-e2e.lock"
    meta_file = coord_dir / "openlet-e2e.json"

    env = Environment(
        project=project,
        mode="mock",
        profiles=("leta",),
        config_overrides={"services": {"platform": {"max_members": 2}}},
        teardown_on_exit=False,
    )

    with lock_file.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if meta_file.is_file():
            meta = cast(dict[str, Any], json.loads(meta_file.read_text("utf-8")))
            meta["workers"] = int(meta["workers"]) + 1
            meta_file.write_text(json.dumps(meta), encoding="utf-8")
        else:
            if keep and _is_gateway_healthy(env):
                env.sync_wiremock_auth()
            else:
                env.up(build=build)
            meta_file.write_text(
                json.dumps({"project": project, "workers": 1}),
                encoding="utf-8",
            )

    try:
        yield env
    finally:
        with lock_file.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if meta_file.is_file():
                meta = cast(dict[str, Any], json.loads(meta_file.read_text("utf-8")))
                remaining = int(meta["workers"]) - 1
                if remaining <= 0:
                    meta_file.unlink(missing_ok=True)
                    if not keep:
                        env.down(volumes=True, remove_state=True)
                else:
                    meta["workers"] = remaining
                    meta_file.write_text(json.dumps(meta), encoding="utf-8")


@pytest.fixture(scope="module")
def accounts(openlet_env: Environment) -> Iterator[AccountFactory]:
    factory = AccountFactory(openlet_env)
    try:
        yield factory
    finally:
        factory.close()


@pytest.fixture()
def account(accounts: AccountFactory) -> AccountFixture:
    return accounts.create()


@pytest.fixture()
def raw_client(openlet_env: Environment) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=openlet_env.endpoints.api_url, timeout=30.0) as client:
        yield client


def new_uuid() -> str:
    return str(uuid4())
