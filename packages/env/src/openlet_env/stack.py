"""Docker Compose stack lifecycle, loopback port discovery, and RustFS dev CORS."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import boto3
import yaml
from botocore.config import Config as S3ClientConfig
from openlet_sdk.config import Config

from .config import (
    build_openlet_config,
    build_runtime_env,
    deep_merge,
    ensure_secrets,
    find_repo_root,
    pick_free_port,
    read_user_env,
    render_compose_overlay,
    resolve_effective_mode,
    stage_wiremock_stubs,
    uses_mock_langfuse,
    validate_project_name,
)
from .models import Endpoints, EnvMode, EnvState


class _ConfigureFn(Protocol):
    def __call__(
        self,
        output: Path,
        *,
        config_path: Path | None = None,
        env: Mapping[str, str] | None = None,
        dynamic_gateway_port: bool = False,
    ) -> None: ...


def _load_configure(repo_root: Path) -> _ConfigureFn:
    script_path = repo_root / "scripts/configure.py"
    spec = importlib.util.spec_from_file_location("_openlet_configure", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(_ConfigureFn, module.configure)


class ComposeStack:
    """Manages an isolated non-production Openlet Docker Compose project."""

    def __init__(self, project: str, *, repo_root: Path | None = None) -> None:
        self.project = validate_project_name(project)
        self.repo_root = find_repo_root(repo_root)
        self.directory = self.repo_root / ".local/env" / self.project
        self.config_path = self.directory / "openlet.yaml"
        self.secrets_path = self.directory / "secrets.env"
        self.state_path = self.directory / "state.json"
        self.wiremock_dir = self.directory / "wiremock"
        self.shared_uv_cache = self.repo_root / ".local/uv-cache"

    def load_state(self) -> EnvState:
        raw = cast(dict[str, object], json.loads(self.state_path.read_text("utf-8")))
        return EnvState(
            project=cast(str, raw["project"]),
            mode=cast(EnvMode, raw["mode"]),
            namespace=cast(str, raw["namespace"]),
            profiles=tuple(cast(list[str], raw.get("profiles", []))),
            gateway_port=int(cast(int, raw["gateway_port"])),
            rustfs_port=int(cast(int, raw["rustfs_port"])),
            wiremock_port=int(cast(int, raw["wiremock_port"])),
            seeded_workspaces=dict(
                cast(dict[str, str], raw.get("seeded_workspaces", {}))
            ),
            accounts=dict(cast(dict[str, dict[str, str]], raw.get("accounts", {}))),
        )

    def save_state(self, state: EnvState) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(asdict(state), indent=2) + "\n", encoding="utf-8"
        )
        self.state_path.chmod(0o600)

    def load_config(self) -> Config:
        value: object = yaml.safe_load(self.config_path.read_text("utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"invalid YAML in {self.config_path}")
        return cast(Config, value)

    def load_runtime_env(self, state: EnvState) -> dict[str, str]:
        project_secrets = ensure_secrets(self.secrets_path)
        user_env = read_user_env(self.repo_root)
        return build_runtime_env(
            mode=state.mode,
            profiles=state.profiles,
            project_secrets=project_secrets,
            user_env=user_env,
        )

    def compose(
        self,
        *args: str,
        profiles: tuple[str, ...] | None = None,
        capture: bool = False,
        check: bool = True,
    ) -> str:
        active_profiles = (
            profiles if profiles is not None else self.load_state().profiles
        )
        cmd = [
            "docker",
            "compose",
            "-p",
            self.project,
            "-f",
            str(self.repo_root / "infra/compose.yaml"),
            "-f",
            str(self.directory / "compose.runtime.yaml"),
            "-f",
            str(self.directory / "compose.env.yaml"),
            *args,
        ]
        env = {
            **os.environ,
            "OPENLET_CONFIG": str(self.config_path),
            "OPENLET_GENERATED": str(self.directory),
            "COMPOSE_PROJECT_NAME": self.project,
            "COMPOSE_PROFILES": ",".join(active_profiles),
        }
        result = subprocess.run(
            cmd,
            cwd=self.repo_root,
            env=env,
            check=check,
            text=True,
            stdout=subprocess.PIPE if capture else sys.stderr,
        )
        return result.stdout or ""

    def up(
        self,
        *,
        mode: EnvMode = "mock",
        profiles: tuple[str, ...] = ("leta",),
        gateway_port: int | None = None,
        override_path: Path | None = None,
        config_overrides: Mapping[str, object] | None = None,
        build: bool = False,
        wait_timeout: int = 180,
    ) -> tuple[EnvState, bool]:
        """Prepare config + overlays and boot the Compose stack. Returns (state, fell_back_to_mock)."""
        if not self.state_path.exists():
            existing = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    f"label=com.docker.compose.project={self.project}",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if existing:
                raise RuntimeError(
                    f"Compose project {self.project!r} already exists outside openlet-env"
                )

        os.umask(0o077)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.directory.chmod(0o700)

        user_env = read_user_env(self.repo_root)
        effective_mode, fell_back = resolve_effective_mode(mode, user_env)
        project_secrets = ensure_secrets(self.secrets_path)

        if self.state_path.is_file():
            prev = self.load_state()
            chosen_gateway = (
                gateway_port if gateway_port is not None else prev.gateway_port
            )
            chosen_rustfs = prev.rustfs_port
            chosen_wiremock = prev.wiremock_port
            state = EnvState(
                project=self.project,
                mode=effective_mode,
                namespace=prev.namespace,
                profiles=profiles,
                gateway_port=chosen_gateway,
                rustfs_port=chosen_rustfs,
                wiremock_port=chosen_wiremock,
                seeded_workspaces=prev.seeded_workspaces,
                accounts=prev.accounts,
            )
        else:
            chosen_gateway = (
                gateway_port if gateway_port is not None else pick_free_port()
            )
            chosen_rustfs = pick_free_port()
            chosen_wiremock = pick_free_port()
            state = EnvState(
                project=self.project,
                mode=effective_mode,
                namespace=uuid4().hex,
                profiles=profiles,
                gateway_port=chosen_gateway,
                rustfs_port=chosen_rustfs,
                wiremock_port=chosen_wiremock,
            )

        merged_override: dict[str, object] | None = None
        if override_path is not None:
            raw_override: object = yaml.safe_load(override_path.read_text("utf-8"))
            if not isinstance(raw_override, dict):
                raise ValueError(f"override YAML must be a mapping: {override_path}")
            merged_override = cast(dict[str, object], raw_override)
        if config_overrides is not None:
            merged_override = (
                deep_merge(merged_override, config_overrides)
                if merged_override is not None
                else dict(config_overrides)
            )

        openlet_cfg = build_openlet_config(
            mode=effective_mode,
            gateway_port=state.gateway_port,
            rustfs_port=state.rustfs_port,
            user_env=user_env,
            override=merged_override,
            repo_root=self.repo_root,
        )
        self.config_path.write_text(
            yaml.safe_dump(openlet_cfg, sort_keys=False), encoding="utf-8"
        )
        # Containers run as non-root UIDs and need read access to the mounted file.
        self.config_path.chmod(0o644)

        runtime_env = build_runtime_env(
            mode=effective_mode,
            profiles=profiles,
            project_secrets=project_secrets,
            user_env=user_env,
        )
        configure_fn = _load_configure(self.repo_root)
        configure_fn(
            self.directory,
            config_path=self.config_path,
            env=runtime_env,
            dynamic_gateway_port=False,
        )

        stage_wiremock_stubs(
            self.wiremock_dir,
            mode=effective_mode,
            include_langfuse=uses_mock_langfuse(effective_mode, user_env),
        )
        overlay_yaml = render_compose_overlay(
            mode=effective_mode,
            profiles=profiles,
            runtime_env=runtime_env,
            gateway_port=state.gateway_port,
            rustfs_port=state.rustfs_port,
            wiremock_port=state.wiremock_port,
            wiremock_dir=self.wiremock_dir,
            shared_uv_cache=self.shared_uv_cache,
        )
        overlay_path = self.directory / "compose.env.yaml"
        overlay_path.write_text(overlay_yaml, encoding="utf-8")
        overlay_path.chmod(0o600)

        self.save_state(state)
        self.compose(
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            str(wait_timeout),
            "--remove-orphans",
            *(["--build"] if build else []),
            profiles=profiles,
        )
        self.configure_rustfs_cors(state, runtime_env)
        return state, fell_back

    def configure_rustfs_cors(
        self, state: EnvState, runtime_env: Mapping[str, str]
    ) -> None:
        """Allow browser dev server (localhost:5173 / 127.0.0.1:5173) direct presigned PUT/GET."""
        cfg = self.load_config()["dependencies"]["s3"]
        s3 = boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "s3",
            endpoint_url=f"http://{self.port('rustfs', 9000)}",
            region_name=cfg["region"],
            aws_access_key_id=runtime_env["S3_ACCESS_KEY_ID"],
            aws_secret_access_key=runtime_env["S3_SECRET_ACCESS_KEY"],
            config=S3ClientConfig(s3={"addressing_style": "path"}),
        )
        try:
            s3.put_bucket_cors(
                Bucket=cfg["bucket"],
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedOrigins": [
                                "http://localhost:5173",
                                "http://127.0.0.1:5173",
                                f"http://localhost:{state.gateway_port}",
                                f"http://127.0.0.1:{state.gateway_port}",
                            ],
                            "AllowedMethods": ["GET", "PUT", "HEAD"],
                            "AllowedHeaders": ["*"],
                            "ExposeHeaders": ["ETag"],
                            "MaxAgeSeconds": 3600,
                        }
                    ]
                },
            )
        finally:
            s3.close()

    def port(self, service: str, container_port: int | str) -> str:
        endpoint = self.compose(
            "port", service, str(container_port), capture=True
        ).strip()
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]+", endpoint):
            raise RuntimeError(
                f"service {service!r} port {container_port} is not bound on loopback: {endpoint!r}"
            )
        return endpoint

    def endpoints(self) -> Endpoints:
        envoy = self.port("envoy", 8080)
        rustfs = self.port("rustfs", 9000)
        wiremock = self.port("wiremock", 8080)
        pg = self.port("postgres", 5432)
        spicedb = self.port("spicedb", 50051)
        qdrant = self.port("qdrant", 6334)
        temporal = self.port("temporal", 7233)
        return Endpoints(
            api_url=f"http://{envoy}",
            object_store_url=f"http://{rustfs}",
            wiremock_url=f"http://{wiremock}",
            postgres_port=int(pg.rsplit(":", 1)[1]),
            spicedb_address=spicedb,
            qdrant_port=int(qdrant.rsplit(":", 1)[1]),
            temporal_address=temporal,
        )

    def down(self, *, volumes: bool = False, remove_state: bool = False) -> None:
        if self.state_path.is_file():
            self.compose(
                "down",
                "--remove-orphans",
                *(["-v"] if volumes else []),
                check=False,
            )
        if remove_state and self.directory.exists():
            shutil.rmtree(self.directory, ignore_errors=True)
