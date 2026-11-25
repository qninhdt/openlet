"""High-level Environment façade and context manager for local dev, E2E, and evaluation."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from types import TracebackType
from typing import cast
from uuid import uuid4

import httpx
import psycopg

from .auth import LocalAuth
from .dataset import ensure_dataset, read_seed_specs
from .loader import (
    ServiceConnections,
    prepare_workspace_cache,
    reset_all_data,
    seed_workspaces,
    unseed_workspace,
)
from .models import Account, Endpoints, EnvMode, EnvState, SeedResult
from .stack import ComposeStack
from .wiremock import WireMockClient

DEV_TOKEN_TTL_SECONDS = 7 * 24 * 3600


class Environment:
    """Lifecycle and data controller for an isolated non-production Openlet instance."""

    def __init__(
        self,
        project: str = "dev",
        *,
        mode: EnvMode = "mock",
        profiles: Sequence[str] = ("leta",),
        gateway_port: int | None = None,
        override_path: Path | None = None,
        config_overrides: Mapping[str, object] | None = None,
        repo_root: Path | None = None,
        teardown_on_exit: bool = True,
        teardown_volumes: bool = True,
    ) -> None:
        self.stack = ComposeStack(project, repo_root=repo_root)
        self.requested_mode: EnvMode = mode
        self.profiles = tuple(profiles)
        self.gateway_port = gateway_port
        self.override_path = override_path
        self.config_overrides = config_overrides
        self.teardown_on_exit = teardown_on_exit
        self.teardown_volumes = teardown_volumes
        self._state: EnvState | None = None
        self._endpoints: Endpoints | None = None
        self._auth: LocalAuth | None = None
        self._wiremock: WireMockClient | None = None

    @property
    def project(self) -> str:
        return self.stack.project

    @property
    def state(self) -> EnvState:
        if self._state is None:
            self._state = self.stack.load_state()
        return self._state

    @property
    def endpoints(self) -> Endpoints:
        if self._endpoints is None:
            self._endpoints = self.stack.endpoints()
        return self._endpoints

    @property
    def auth(self) -> LocalAuth:
        if self._auth is None:
            self._auth = LocalAuth.load_or_create(self.stack.directory)
        return self._auth

    @property
    def wiremock(self) -> WireMockClient:
        if self._wiremock is None:
            self._wiremock = WireMockClient(self.endpoints.wiremock_url)
        return self._wiremock

    def up(self, *, build: bool = False, wait_timeout: int = 180) -> Endpoints:
        state, fell_back = self.stack.up(
            mode=self.requested_mode,
            profiles=self.profiles,
            gateway_port=self.gateway_port,
            override_path=self.override_path,
            config_overrides=self.config_overrides,
            build=build,
            wait_timeout=wait_timeout,
        )
        if fell_back:
            print(
                "[openlet-env] OPENAI_API_KEY not set — falling back to offline mock mode.",
                file=sys.stderr,
            )
        self._state = state
        self._endpoints = self.stack.endpoints()
        self._auth = LocalAuth.load_or_create(self.stack.directory)
        self._wiremock = WireMockClient(self._endpoints.wiremock_url)
        self.sync_wiremock_auth()
        self._write_dev_accounts()
        return self._endpoints

    def sync_wiremock_auth(self) -> None:
        self.wiremock.register_jwks(self.auth.jwks())
        claim_key = self.stack.load_config()["auth"]["clerk"].get(
            "user_id_metadata_key", "openlet_user_id"
        )
        for info in self.state.accounts.values():
            self.wiremock.register_clerk_user(
                subject=info["clerk_user_id"],
                email=info["email"],
                first_name=info["first_name"],
                last_name=info["last_name"],
                user_id=info["user_id"],
                user_id_claim=claim_key,
            )

    def _write_dev_accounts(self) -> None:
        dev_file = self.stack.directory / "dev-accounts.json"
        entries: list[dict[str, str]] = []
        for handle, info in sorted(self.state.accounts.items()):
            token = self.auth.sign(
                info["clerk_user_id"],
                info["user_id"],
                ttl_seconds=DEV_TOKEN_TTL_SECONDS,
            )
            entries.append(
                {
                    "handle": handle,
                    "user_id": info["user_id"],
                    "clerk_user_id": info["clerk_user_id"],
                    "email": info["email"],
                    "name": f"{info['first_name']} {info['last_name']}".strip()
                    or handle,
                    "token": token,
                }
            )
        dev_file.write_text(
            json.dumps({"project": self.project, "accounts": entries}, indent=2) + "\n",
            encoding="utf-8",
        )
        dev_file.chmod(0o600)

    def _connect(self, scope: ExitStack) -> ServiceConnections:
        state = self.state
        return ServiceConnections(
            scope,
            config=self.stack.load_config(),
            env=self.stack.load_runtime_env(state),
            endpoints=self.endpoints,
            has_leta="leta" in state.profiles,
        )

    def seed(
        self,
        *,
        dataset_dir: Path | None = None,
        workspaces: Sequence[str] = (),
        idempotent: bool = False,
    ) -> SeedResult:
        """Seed one or more workspaces from a local dataset or partial HF download."""
        target_dir = (
            dataset_dir
            if dataset_dir is not None
            else ensure_dataset(
                self.stack.repo_root / "datasets", workspaces=workspaces
            )
        )
        profiles, specs = read_seed_specs(target_dir, workspaces)
        self.sync_wiremock_auth()

        if idempotent:
            existing_ids = self._existing_workspace_ids(
                [
                    wid
                    for spec in specs
                    if (wid := self.state.seeded_workspaces.get(spec.handle))
                ]
            )
            missing_specs = [
                spec
                for spec in specs
                if self.state.seeded_workspaces.get(spec.handle) not in existing_ids
            ]
            if not missing_specs:
                self._write_dev_accounts()
                return SeedResult(
                    api_url=self.endpoints.api_url,
                    object_store_url=self.endpoints.object_store_url,
                    zed_token="",
                    users=self._persisted_accounts(),
                    workspaces={},
                )
            specs = missing_specs

        with ExitStack() as scope:
            services = self._connect(scope)
            result = seed_workspaces(
                services,
                auth=self.auth,
                wiremock=self.wiremock,
                namespace=self.state.namespace,
                profiles=profiles,
                specs=specs,
                token_ttl_seconds=DEV_TOKEN_TTL_SECONDS,
            )

        state = self.state
        for handle, ws in result.workspaces.items():
            state.seeded_workspaces[handle] = ws.workspace_id
        for handle, acct in result.users.items():
            state.accounts[handle] = {
                "user_id": acct.user_id,
                "clerk_user_id": acct.clerk_user_id,
                "email": acct.email,
                "first_name": acct.first_name,
                "last_name": acct.last_name,
            }
        self.stack.save_state(state)
        self._write_dev_accounts()
        return result

    def _existing_workspace_ids(self, workspace_ids: Sequence[str]) -> set[str]:
        if not workspace_ids:
            return set()
        cfg = self.stack.load_config()
        env = self.stack.load_runtime_env(self.state)
        pg = cfg["dependencies"]["postgres"]
        db = cfg["services"]["platform"]["database"]
        password = env[db["password"][2:-1]]
        with psycopg.connect(
            host="127.0.0.1",
            port=self.endpoints.postgres_port,
            dbname=db["name"],
            user=db["user"],
            password=password,
            sslmode=pg["sslmode"],
            autocommit=True,
            connect_timeout=10,
        ) as conn:
            rows = conn.execute(
                "SELECT id::text FROM workspaces WHERE id = ANY(%s::uuid[])",
                (list(workspace_ids),),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def _persisted_accounts(self) -> dict[str, Account]:
        out: dict[str, Account] = {}
        for handle, info in self.state.accounts.items():
            out[handle] = Account(
                handle=handle,
                user_id=info["user_id"],
                clerk_user_id=info["clerk_user_id"],
                email=info["email"],
                first_name=info["first_name"],
                last_name=info["last_name"],
                token=self.auth.sign(
                    info["clerk_user_id"],
                    info["user_id"],
                    ttl_seconds=DEV_TOKEN_TTL_SECONDS,
                ),
            )
        return out

    def prepare_cache(
        self, *, dataset_dir: Path, workspaces: Sequence[str] = ()
    ) -> dict[str, object]:
        """Run LetFS ingestion for uncached files in dataset_dir and save `.letfs-cache/`."""
        _, specs = read_seed_specs(dataset_dir, workspaces)
        with ExitStack() as scope:
            services = self._connect(scope)
            return prepare_workspace_cache(services, specs=specs)

    def unseed(self, workspace_id: str) -> None:
        """Delete one workspace (by UUID or seeded handle) across all stores."""
        state = self.state
        resolved = state.seeded_workspaces.get(workspace_id, workspace_id)
        with ExitStack() as scope:
            services = self._connect(scope)
            unseed_workspace(services, resolved)
        for handle, wid in list(state.seeded_workspaces.items()):
            if wid == resolved:
                del state.seeded_workspaces[handle]
        self.stack.save_state(state)

    def reset(self) -> None:
        """Wipe all database, SpiceDB, Qdrant, and RustFS data without restarting containers."""
        with ExitStack() as scope:
            services = self._connect(scope)
            reset_all_data(services)
        state = self.state
        state.seeded_workspaces.clear()
        state.accounts.clear()
        self.stack.save_state(state)
        self._write_dev_accounts()

    def create_account(
        self,
        *,
        first_name: str = "Test",
        last_name: str = "Member",
        email: str | None = None,
        create_workspace: bool = False,
    ) -> tuple[Account, dict[str, str]]:
        """Onboard a fresh local user via /v1/me:onboard (and optionally create a workspace)."""
        subject = f"user_{uuid4()}"
        acct_email = email or f"{uuid4()}@example.test"
        self.wiremock.register_clerk_user(
            subject=subject,
            email=acct_email,
            first_name=first_name,
            last_name=last_name,
        )
        bootstrap_token = self.auth.sign(subject)
        with httpx.Client(base_url=self.endpoints.api_url, timeout=30.0) as client:
            resp = client.post(
                "/v1/me:onboard",
                headers={"Authorization": f"Bearer {bootstrap_token}"},
                json={},
            )
            resp.raise_for_status()
            user = cast(dict[str, str], resp.json())
            user_id = user["id"]
            token = self.auth.sign(subject, user_id)

            extra: dict[str, str] = {}
            if create_workspace:
                created = client.post(
                    "/v1/workspaces",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"name": "Test workspace", "requestId": str(uuid4())},
                )
                created.raise_for_status()
                ws = cast(dict[str, str], created.json())
                zed = created.headers.get("x-openlet-zed-token", "")
                extra = {"workspace_id": ws["id"], "zed_token": zed}

        account = Account(
            handle=subject,
            user_id=user_id,
            clerk_user_id=subject,
            email=acct_email,
            first_name=first_name,
            last_name=last_name,
            token=token,
        )
        return account, extra

    def token(self, user_handle: str, *, ttl_seconds: int = 3600) -> str:
        """Issue a fresh RS256 Bearer token for a seeded user handle."""
        info = self.state.accounts.get(user_handle)
        if info is None:
            available = ", ".join(sorted(self.state.accounts)) or "(none)"
            raise KeyError(
                f"unknown user handle {user_handle!r}; seeded users: {available}"
            )
        return self.auth.sign(
            info["clerk_user_id"], info["user_id"], ttl_seconds=ttl_seconds
        )

    def status(self) -> dict[str, object]:
        state = self.state
        ep = self.endpoints
        return {
            "project": state.project,
            "mode": state.mode,
            "profiles": list(state.profiles),
            "api_url": ep.api_url,
            "object_store_url": ep.object_store_url,
            "wiremock_url": ep.wiremock_url,
            "seeded_workspaces": state.seeded_workspaces,
            "users": sorted(state.accounts),
        }

    def logs(self, *services: str, tail: int = 100, follow: bool = False) -> str:
        args = ["logs", "--tail", str(tail)]
        if follow:
            args.append("--follow")
        args.extend(services)
        return self.stack.compose(*args, capture=not follow)

    def down(self, *, volumes: bool = False, remove_state: bool = False) -> None:
        self.stack.down(volumes=volumes, remove_state=remove_state)

    def __enter__(self) -> Environment:
        self.up()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self.teardown_on_exit:
            self.down(volumes=self.teardown_volumes, remove_state=self.teardown_volumes)
