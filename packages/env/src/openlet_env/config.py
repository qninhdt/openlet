"""Pure configuration and Compose overlay synthesis (zero os.environ mutation)."""

from __future__ import annotations

import copy
import os
import re
import secrets
import shutil
import socket
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NotRequired, TypedDict

import yaml
from dotenv import dotenv_values
from openlet_sdk.config import Config, parse_config
from openlet_sdk.types import is_str_mapping

if TYPE_CHECKING:
    from collections.abc import Mapping

    from openlet_env.models import EnvMode

RUSTFS_IMAGE = "rustfs/rustfs:1.0.6"
WIREMOCK_IMAGE = "wiremock/wiremock:3.13.2@sha256:0d4ecb3e4dc8213fd7a4d37d6a78f6e6b553a6d2e15bd51b0999781282ac61b3"
STUBS_PACKAGE_DIR = Path(__file__).resolve().parent / "wiremock_stubs"

INTERNAL_SECRET_KEYS: tuple[str, ...] = (
    "POSTGRES_ADMIN_PASSWORD",
    "PLATFORM_DB_PASSWORD",
    "CHAT_DB_PASSWORD",
    "LETFS_DB_PASSWORD",
    "LETA_DB_PASSWORD",
    "TEMPORAL_DB_PASSWORD",
    "SPICEDB_DB_PASSWORD",
    "OBSERVABILITY_DB_PASSWORD",
    "SPICEDB_KEY",
    "QDRANT_API_KEY",
    "REDIS_PASSWORD",
    "CENTRIFUGO_API_KEY",
    "CENTRIFUGO_TOKEN_SECRET",
    "LITELLM_MASTER_KEY",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "CLERK_SECRET_KEY",
)


class _ComposeOverride(list[str]):
    """Marker list serialized with Docker Compose's `!override` YAML tag."""


class _ComposeHealthcheck(TypedDict):
    test: NotRequired[list[str]]
    interval: str
    timeout: str
    retries: int


class _ComposeServiceCondition(TypedDict):
    condition: Literal["service_healthy"]


class _ComposeService(TypedDict, total=False):
    image: str
    command: list[str]
    ports: list[str] | _ComposeOverride
    volumes: list[str] | _ComposeOverride
    environment: dict[str, str]
    depends_on: dict[str, _ComposeServiceCondition]
    healthcheck: _ComposeHealthcheck
    stop_grace_period: str


class _ComposeOverlay(TypedDict):
    services: dict[str, _ComposeService]
    volumes: dict[str, dict[str, str]]


class _ComposeDumper(yaml.SafeDumper):
    pass


def _represent_override(
    dumper: yaml.SafeDumper, data: _ComposeOverride
) -> yaml.SequenceNode:
    return dumper.represent_sequence("!override", list(data))


_ComposeDumper.add_representer(_ComposeOverride, _represent_override)


def find_repo_root(start: Path | None = None) -> Path:
    """Locate the Openlet repository root containing infra/compose.yaml."""
    candidates = [
        *([] if start is None else [start.resolve()]),
        Path.cwd().resolve(),
        Path(__file__).resolve(),
    ]
    for base in candidates:
        for parent in (base, *base.parents):
            if (parent / "infra/compose.yaml").is_file():
                return parent
    raise FileNotFoundError(
        "Could not locate Openlet repo root (missing infra/compose.yaml)"
    )


def validate_project_name(project: str) -> str:
    """Validate and return a Docker Compose project name."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
        raise ValueError(f"invalid Compose project name: {project!r}")
    return project


def deep_merge(
    base: Mapping[str, object], override: Mapping[str, object]
) -> dict[str, object]:
    """Return a deep copy of base merged recursively with override."""
    merged: dict[str, object] = copy.deepcopy(dict(base))
    for key, value in override.items():
        current = merged.get(key)
        if is_str_mapping(current) and is_str_mapping(value):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_dotenv(path: Path) -> dict[str, str]:
    """Parse a .env file without mutating os.environ."""
    if not path.is_file():
        return {}
    return {k: v for k, v in dotenv_values(path).items() if v is not None}


def ensure_secrets(path: Path) -> dict[str, str]:
    """Load or generate per-project internal secrets in `.local/env/<project>/secrets.env`."""
    existing = load_dotenv(path)
    changed = False
    for key in INTERNAL_SECRET_KEYS:
        if not existing.get(key):
            if key == "S3_ACCESS_KEY_ID":
                existing[key] = "openlet-" + secrets.token_hex(8)
            elif key == "CLERK_SECRET_KEY":
                existing[key] = "sk_local_" + secrets.token_hex(16)
            else:
                existing[key] = secrets.token_hex(20)
            changed = True
    if changed or not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{key}={existing[key]}" for key in INTERNAL_SECRET_KEYS]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o600)
    return existing


def pick_free_port(preferred: int | None = None) -> int:
    """Return preferred loopback port if free, otherwise allocate an ephemeral port."""
    if preferred is not None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", preferred))
            except OSError:
                pass
            else:
                return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def resolve_effective_mode(
    requested: EnvMode,
    env_vars: Mapping[str, str],
) -> tuple[EnvMode, bool]:
    """Return (effective_mode, fell_back_to_mock)."""
    if requested == "mock":
        return "mock", False
    if env_vars.get("OPENAI_API_KEY", "").strip():
        return "live", False
    return "mock", True


def build_runtime_env(
    *,
    mode: EnvMode,
    profiles: tuple[str, ...],
    project_secrets: Mapping[str, str],
    user_env: Mapping[str, str],
) -> dict[str, str]:
    """Compose the isolated environment dictionary for scripts/configure.py and Compose."""
    env: dict[str, str] = {
        **project_secrets,
        "COMPOSE_PROFILES": ",".join(profiles),
    }
    if mode == "mock":
        env["OPENAI_API_KEY"] = "sk-mock-openlet"
        env["OPENAI_BASE_URL"] = "http://wiremock:8080/v1"
        env["LANGFUSE_PUBLIC_KEY"] = "pk-lf-mock"
        env["LANGFUSE_SECRET_KEY"] = "sk-lf-mock"  # noqa: S105  # Non-production WireMock stub key.
        env["DATALAB_API_KEY"] = "datalab-test-only"
        env["DATALAB_HOST"] = "http://wiremock:8080"
        return env

    env["OPENAI_API_KEY"] = user_env["OPENAI_API_KEY"]
    env["OPENAI_BASE_URL"] = (
        user_env.get("OPENAI_BASE_URL", "").strip() or "https://api.openai.com/v1"
    )
    lf_pub = user_env.get("LANGFUSE_PUBLIC_KEY", "").strip()
    lf_sec = user_env.get("LANGFUSE_SECRET_KEY", "").strip()
    if lf_pub and lf_sec:
        env["LANGFUSE_PUBLIC_KEY"] = lf_pub
        env["LANGFUSE_SECRET_KEY"] = lf_sec
        if lf_base := user_env.get("LANGFUSE_BASE_URL", "").strip():
            env["LANGFUSE_BASE_URL"] = lf_base
    else:
        env["LANGFUSE_PUBLIC_KEY"] = "pk-lf-mock"
        env["LANGFUSE_SECRET_KEY"] = "sk-lf-mock"  # noqa: S105  # Non-production WireMock stub key.
    if datalab_key := user_env.get("DATALAB_API_KEY", "").strip():
        env["DATALAB_API_KEY"] = datalab_key
    if tinyfish_key := user_env.get("TINYFISH_API_KEY", "").strip():
        env["TINYFISH_API_KEY"] = tinyfish_key
    return env


def uses_mock_langfuse(mode: EnvMode, user_env: Mapping[str, str]) -> bool:
    """Return whether the environment should route Langfuse traffic to WireMock."""
    if mode == "mock":
        return True
    return not (
        user_env.get("LANGFUSE_PUBLIC_KEY", "").strip()
        and user_env.get("LANGFUSE_SECRET_KEY", "").strip()
    )


def build_openlet_config(
    *,
    mode: EnvMode,
    gateway_port: int,
    rustfs_port: int,
    user_env: Mapping[str, str],
    override: Mapping[str, object] | None = None,
    repo_root: Path | None = None,
) -> Config:
    """Load `infra/config/openlet.example.yaml` as base and merge non-production overrides."""
    example_path = find_repo_root(repo_root) / "infra/config/openlet.example.yaml"
    raw_base: object = yaml.safe_load(example_path.read_text(encoding="utf-8"))
    if not is_str_mapping(raw_base):
        raise ValueError(f"expected YAML mapping in {example_path}")
    base: dict[str, object] = dict(raw_base)
    base.pop("observability", None)

    langfuse_base = (
        "http://wiremock:8080"
        if uses_mock_langfuse(mode, user_env)
        else (
            user_env.get("LANGFUSE_BASE_URL", "").strip()
            or "https://cloud.langfuse.com"
        )
    )
    nonprod: dict[str, object] = {
        "runtime": {
            "environment": "test" if mode == "mock" else "development",
            "shutdown_timeout_seconds": 15 if mode == "mock" else 60,
        },
        "telemetry": {"otlp_endpoint": None, "trace_sample_ratio": 0.1},
        "langfuse": {"base_url": langfuse_base},
        "auth": {
            "clerk": {
                "issuer": "http://wiremock:8080",
                "jwks_url": "http://wiremock:8080/.well-known/jwks.json",
                "api_url": "http://wiremock:8080/v1",
            }
        },
        "dependencies": {
            "s3": {
                "endpoint": "http://rustfs:9000",
                "public_endpoint": f"http://127.0.0.1:{rustfs_port}",
            }
        },
        "models": {
            "reranking": {"model": "cohere/rerank-v3.5"} if mode == "mock" else None,
        },
        "services": {
            "gateway": {"public_url": f"http://127.0.0.1:{gateway_port}"},
            **(
                {
                    "letfs": {
                        "multipart_threshold_bytes": 10485760,
                        "processing": {"parse_timeout_seconds": 600},
                    }
                }
                if mode == "mock"
                else {}
            ),
            **(
                {"leta": {"web_search": {"api_key": "${TINYFISH_API_KEY}"}}}
                if mode == "live" and user_env.get("TINYFISH_API_KEY", "").strip()
                else {}
            ),
        },
    }
    merged = deep_merge(base, nonprod)
    if override:
        merged = deep_merge(merged, override)
    return parse_config(merged)


def stage_wiremock_stubs(
    target_dir: Path,
    *,
    mode: EnvMode,
    include_langfuse: bool,
) -> None:
    """Populate the project's WireMock mappings directory for mock or live mode."""
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_dir.chmod(0o755)
    for stub in sorted(STUBS_PACKAGE_DIR.glob("*.json")):
        if mode == "mock" or (include_langfuse and stub.name.startswith("langfuse-")):
            dest = target_dir / stub.name
            shutil.copy2(stub, dest)
            dest.chmod(0o644)


def render_compose_overlay(
    *,
    mode: EnvMode,
    profiles: tuple[str, ...],
    runtime_env: Mapping[str, str],
    gateway_port: int,
    rustfs_port: int,
    wiremock_port: int,
    wiremock_dir: Path,
    shared_uv_cache: Path,
) -> str:
    """Render compose.env.yaml as YAML text (with Compose `!override` tags)."""
    shared_uv_cache.mkdir(parents=True, exist_ok=True)
    spicedb_service: _ComposeService = {"ports": ["127.0.0.1::50051"]}
    if mode == "mock":
        spicedb_service["command"] = [
            "serve",
            "--datastore-engine",
            "postgres",
            "--http-enabled=false",
            "--skip-release-check",
            "--datastore-revision-quantization-interval=100ms",
        ]
    litellm_service: _ComposeService = {
        "healthcheck": {"interval": "2s", "timeout": "5s", "retries": 45},
    }
    if mode == "mock":
        litellm_service["depends_on"] = {"wiremock": {"condition": "service_healthy"}}
        litellm_service["volumes"] = _ComposeOverride(
            [f"{STUBS_PACKAGE_DIR / 'litellm.yaml'}:/etc/litellm/config.yaml:ro"]
        )
    services: dict[str, _ComposeService] = {
        "postgres": {"ports": ["127.0.0.1::5432"]},
        "spicedb": spicedb_service,
        "qdrant": {"ports": ["127.0.0.1::6334"]},
        "temporal": {"ports": ["127.0.0.1::7233"]},
        "wiremock": {
            "image": WIREMOCK_IMAGE,
            "command": ["--global-response-templating", "--disable-gzip"],
            "ports": [f"127.0.0.1:{wiremock_port}:8080"],
            "volumes": [f"{wiremock_dir}:/home/wiremock/mappings:ro"],
            "healthcheck": {
                "test": ["CMD", "curl", "-fsS", "http://127.0.0.1:8080/__admin/health"],
                "interval": "2s",
                "timeout": "3s",
                "retries": 30,
            },
        },
        "rustfs": {
            "image": RUSTFS_IMAGE,
            "environment": {
                "RUSTFS_ACCESS_KEY": runtime_env["S3_ACCESS_KEY_ID"],
                "RUSTFS_SECRET_KEY": runtime_env["S3_SECRET_ACCESS_KEY"],
                "RUSTFS_CONSOLE_ENABLE": "false",
                "RUSTFS_OBS_LOG_DIRECTORY": "",
            },
            "ports": [f"127.0.0.1:{rustfs_port}:9000"],
            "volumes": ["rustfs-data:/data"],
            "stop_grace_period": "10s",
            "healthcheck": {
                "test": ["CMD", "curl", "-fsS", "http://127.0.0.1:9000/health"],
                "interval": "2s",
                "timeout": "3s",
                "retries": 30,
            },
        },
        "resources": {
            "depends_on": {
                "rustfs": {"condition": "service_healthy"},
                "wiremock": {"condition": "service_healthy"},
            },
            "volumes": [f"{shared_uv_cache}:/root/.cache/uv"],
        },
        "databases": {
            "volumes": [f"{shared_uv_cache}:/root/.cache/uv"],
        },
        "platform": {
            "depends_on": {"wiremock": {"condition": "service_healthy"}},
        },
        "litellm": litellm_service,
        "envoy": {
            "ports": _ComposeOverride([f"127.0.0.1:{gateway_port}:8080"]),
        },
    }

    if mode == "mock":
        services["ingest-cpu"] = {
            "depends_on": {"wiremock": {"condition": "service_healthy"}},
            "stop_grace_period": "5s",
        }
        services["ingest-io"] = {"stop_grace_period": "5s"}
        services["platform"]["stop_grace_period"] = "5s"
        services["chat"] = {"stop_grace_period": "5s"}
        services["letfs"] = {"stop_grace_period": "5s"}
        services["litellm"]["stop_grace_period"] = "5s"
        if "leta" in profiles:
            services["leta-api"] = {"stop_grace_period": "5s"}
            services["leta-worker"] = {"stop_grace_period": "5s"}

    overlay: _ComposeOverlay = {
        "services": services,
        "volumes": {"rustfs-data": {}},
    }
    return yaml.dump(overlay, Dumper=_ComposeDumper, sort_keys=False).replace("$", "$$")


def read_user_env(repo_root: Path, dotenv_path: Path | None = None) -> dict[str, str]:
    """Merge `.env` (lowest priority) with current process `os.environ` (highest priority)."""
    dotenv = repo_root / ".env" if dotenv_path is None else dotenv_path
    merged = load_dotenv(dotenv)
    merged.update(os.environ)
    return merged
