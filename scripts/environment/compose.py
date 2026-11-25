"""Run an isolated Openlet Compose project."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import cast
from uuid import uuid4

import yaml
from openlet_sdk.config import load, secret

from scripts.configure import ROOT, configure


class Stack:
    def __init__(self, project: str) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
            raise ValueError("invalid Compose project name")
        self.project = project
        self.directory = ROOT / ".local/environment" / project
        self.config = self.directory / "openlet.yaml"
        self.state = self.directory / "stack.json"

    def run(self, *args: str, capture: bool = False) -> str:
        state = cast(dict[str, str], json.loads(self.state.read_text()))
        return (
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "-p",
                    self.project,
                    "-f",
                    str(ROOT / "infra/compose.yaml"),
                    "-f",
                    str(self.directory / "compose.runtime.yaml"),
                    "-f",
                    str(self.directory / "compose.environment.yaml"),
                    *args,
                ],
                cwd=ROOT,
                env={
                    **os.environ,
                    "OPENLET_CONFIG": str(self.config),
                    "OPENLET_GENERATED": str(self.directory),
                    "OPENLET_BACKUPS": str(self.directory / "backups"),
                    "COMPOSE_PROJECT_NAME": self.project,
                    "COMPOSE_PROFILES": state["profiles"],
                },
                check=True,
                text=True,
                stdout=subprocess.PIPE if capture else sys.stderr,
            ).stdout
            or ""
        )

    def up(self, config_path: Path, *, build: bool) -> None:
        if not self.state.exists():
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
            ).stdout
            if existing:
                raise ValueError(
                    f"Compose project {self.project} already exists outside the harness"
                )
        os.umask(0o077)
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "backups").mkdir(exist_ok=True)
        state = (
            cast(dict[str, str], json.loads(self.state.read_text()))
            if self.state.exists()
            else {
                "namespace": uuid4().hex,
                "profiles": os.environ.get("COMPOSE_PROFILES", ""),
            }
        )
        os.environ["COMPOSE_PROFILES"] = state["profiles"]
        os.environ["OPENLET_CONFIG"] = str(config_path.resolve())
        config = load()
        if config["runtime"]["environment"].lower() in {"production", "prod"}:
            raise ValueError("use a non-production Openlet configuration")
        dependencies = config["dependencies"]
        for service, address in {
            "postgres": dependencies["postgres"]["host"],
            "temporal": dependencies["temporal"]["address"],
            "spicedb": dependencies["spicedb"]["address"],
            "qdrant": dependencies["qdrant"]["address"],
            "redis": dependencies["redis"]["address"],
        }.items():
            if address.split(":", 1)[0] != service:
                raise ValueError(
                    f"harness configuration must use the Compose {service} service"
                )
        s3 = dependencies["s3"]
        s3.update(endpoint="http://rustfs:9000", region="us-east-1", path_style=True)
        s3.pop("processing_download_endpoint", None)
        self.config.write_text(yaml.safe_dump(config, sort_keys=False))
        # Container UIDs read the mounted file. The host directory stays private.
        self.config.chmod(0o644)
        os.environ["OPENLET_CONFIG"] = str(self.config)
        configure(self.directory, dynamic_gateway_port=True)
        overlay: dict[str, object] = {
            "services": {
                **{
                    name: {"ports": [f"127.0.0.1::{port}"]}
                    for name, port in {
                        "postgres": dependencies["postgres"]["port"],
                        "spicedb": dependencies["spicedb"]["address"].rsplit(":", 1)[1],
                        "qdrant": dependencies["qdrant"]["address"].rsplit(":", 1)[1],
                        "temporal": dependencies["temporal"]["address"].rsplit(":", 1)[
                            1
                        ],
                    }.items()
                },
                "rustfs": {
                    "image": "rustfs/rustfs:1.0.6",
                    "environment": {
                        "RUSTFS_ACCESS_KEY": secret(s3["access_key_id"]),
                        "RUSTFS_SECRET_KEY": secret(s3["secret_access_key"]),
                        "RUSTFS_CONSOLE_ENABLE": "false",
                    },
                    "ports": ["127.0.0.1::9000"],
                    "volumes": ["rustfs-data:/data"],
                    "healthcheck": {
                        "test": ["CMD", "curl", "-fsS", "http://127.0.0.1:9000/health"],
                        "interval": "3s",
                        "timeout": "3s",
                        "retries": 30,
                    },
                },
                "resources": {
                    "depends_on": {"rustfs": {"condition": "service_healthy"}}
                },
            },
            "volumes": {"rustfs-data": {}},
        }
        (self.directory / "compose.environment.yaml").write_text(
            yaml.safe_dump(overlay, sort_keys=False).replace("$", "$$")
        )
        self.state.write_text(json.dumps(state))
        self.run(
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "180",
            *(["--build"] if build else []),
        )

    def settings(self) -> tuple[str, str, dict[str, str]]:
        os.environ["OPENLET_CONFIG"] = str(self.config)
        port = load()["services"]["gateway"]["http_listen"].rsplit(":", 1)[1]
        api = self.port("envoy", port)
        rustfs = self.port("rustfs", 9000)
        return (
            f"http://{api}",
            rustfs,
            cast(dict[str, str], json.loads(self.state.read_text())),
        )

    def port(self, service: str, container_port: int | str) -> str:
        endpoint = self.run("port", service, str(container_port), capture=True).strip()
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]+", endpoint):
            raise RuntimeError(f"{service} must use a published loopback port")
        return endpoint
