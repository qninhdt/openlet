"""Pure configuration and Compose overlay synthesis (zero os.environ mutation)."""

from __future__ import annotations

import copy
import os
import re
import secrets
import shutil
import socket
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import yaml
from openlet_sdk.config import Config

from .models import EnvMode

RUSTFS_IMAGE = "rustfs/rustfs:1.0.6"
WIREMOCK_IMAGE = "wiremock/wiremock:3.13.2@sha256:0d4ecb3e4dc8213fd7a4d37d6a78f6e6b553a6d2e15bd51b0999781282ac61b3"
STUBS_PACKAGE_DIR = Path(__file__).resolve().parent / "wiremock_stubs"

INTERNAL_SECRET_KEYS: tuple[str, ...] = (
    "POSTGRES_ADMIN_PASSWORD",
    "PLATFORM_DB_PASSWORD",
    "LETFS_DB_PASSWORD",
    "LETA_DB_PASSWORD",
    "TEMPORAL_DB_PASSWORD",
    "SPICEDB_DB_PASSWORD",
    "OBSERVABILITY_DB_PASSWORD",
    "SPICEDB_KEY",
    "QDRANT_API_KEY",
    "REDIS_PASSWORD",
    "LITELLM_MASTER_KEY",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "CLERK_SECRET_KEY",
)


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
        if isinstance(current, dict) and isinstance(value, Mapping):
            merged[key] = deep_merge(
                cast(Mapping[str, object], current),
                cast(Mapping[str, object], value),
            )
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_dotenv(path: Path) -> dict[str, str]:
    """Parse a simple .env file without mutating os.environ."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


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
                return preferred
            except OSError:
                pass
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
        env["LANGFUSE_SECRET_KEY"] = "sk-lf-mock"
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
        env["LANGFUSE_SECRET_KEY"] = "sk-lf-mock"
    if datalab_key := user_env.get("DATALAB_API_KEY", "").strip():
        env["DATALAB_API_KEY"] = datalab_key
    if tinyfish_key := user_env.get("TINYFISH_API_KEY", "").strip():
        env["TINYFISH_API_KEY"] = tinyfish_key
    return env


def uses_mock_langfuse(mode: EnvMode, user_env: Mapping[str, str]) -> bool:
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
) -> Config:
    """Synthesize a self-contained non-production openlet.yaml mapping."""
    mock_langfuse = uses_mock_langfuse(mode, user_env)
    langfuse_base = (
        "http://wiremock:8080"
        if mock_langfuse
        else (
            user_env.get("LANGFUSE_BASE_URL", "").strip()
            or "https://cloud.langfuse.com"
        )
    )
    leta_section: dict[str, object] = {
        "http_listen": "0.0.0.0:8000",
        "http_target": "leta-api:8000",
        "compaction": {
            "trigger_fraction": 0.8,
            "keep_tokens": 8192,
            "summary_max_tokens": 2048,
        },
        "database": {
            "name": "leta",
            "user": "leta",
            "password": "${LETA_DB_PASSWORD}",
        },
    }
    if mode == "live" and user_env.get("TINYFISH_API_KEY", "").strip():
        leta_section["web_search"] = {"api_key": "${TINYFISH_API_KEY}"}

    base: dict[str, object] = {
        "runtime": {
            "environment": "test" if mode == "mock" else "development",
            "log_level": "info",
            "shutdown_timeout_seconds": 15 if mode == "mock" else 60,
        },
        "grpc": {"max_receive_bytes": 16777216},
        "telemetry": {
            "otlp_endpoint": None,
            "trace_sample_ratio": 0.1,
            "metrics_export_interval_seconds": 60,
        },
        "langfuse": {
            "base_url": langfuse_base,
            "public_key": "${LANGFUSE_PUBLIC_KEY}",
            "secret_key": "${LANGFUSE_SECRET_KEY}",
            "prompt_label": "production",
        },
        "auth": {
            "clerk": {
                "issuer": "http://wiremock:8080",
                "jwks_url": "http://wiremock:8080/.well-known/jwks.json",
                "audience": "openlet",
                "user_id_metadata_key": "openlet_user_id",
                "api_url": "http://wiremock:8080/v1",
                "secret_key": "${CLERK_SECRET_KEY}",
            }
        },
        "dependencies": {
            "postgres": {"host": "postgres", "port": 5432, "sslmode": "disable"},
            "temporal": {
                "address": "temporal:7233",
                "namespace": "openlet",
                "tls": False,
                "queues": {
                    "platform": "openlet-platform",
                    "letfs": "openlet-letfs",
                    "ingest_cpu": "openlet-ingest-cpu",
                    "ingest_io": "openlet-ingest-io",
                    "leta": "openlet-leta",
                    "leta_runtime": "openlet-leta-runtime",
                    "leta_bridge": "openlet-leta-bridge",
                },
            },
            "redis": {
                "address": "redis:6379",
                "database": 0,
                "password": "${REDIS_PASSWORD}",
            },
            "spicedb": {
                "address": "spicedb:50051",
                "tls": False,
                "key": "${SPICEDB_KEY}",
            },
            "s3": {
                "endpoint": "http://rustfs:9000",
                "public_endpoint": f"http://127.0.0.1:{rustfs_port}",
                "region": "us-east-1",
                "bucket": "openlet",
                "path_style": True,
                "access_key_id": "${S3_ACCESS_KEY_ID}",
                "secret_access_key": "${S3_SECRET_ACCESS_KEY}",
            },
            "qdrant": {
                "address": "qdrant:6334",
                "tls": False,
                "api_key": "${QDRANT_API_KEY}",
                "collection": "files",
            },
        },
        "models": {
            "gateway": {
                "base_url": "http://litellm:4000",
                "api_key": "${LITELLM_MASTER_KEY}",
                "timeout_seconds": 90,
            },
            "embedding": {
                "model": "openai/text-embedding-3-large",
                "dimensions": 1536,
            },
            "reranking": {"model": "cohere/rerank-v3.5"} if mode == "mock" else None,
            "enrichment": {
                "output_mode": "tools",
                "max_input_characters": 24000,
                "max_image_pixels": 25000000,
                "image_max_side": 1600,
                "image_jpeg_quality": 85,
            },
        },
        "services": {
            "gateway": {
                "http_listen": "0.0.0.0:8080",
                "public_url": f"http://127.0.0.1:{gateway_port}",
            },
            "platform": {
                "grpc_listen": "0.0.0.0:9090",
                "grpc_target": "platform:9090",
                "database": {
                    "name": "platform",
                    "user": "platform",
                    "password": "${PLATFORM_DB_PASSWORD}",
                },
                "max_members": 100,
                "default_quota_bytes": 10737418240,
                "invitation_ttl_seconds": 604800,
                "idempotency_retention_seconds": 86400,
                "maintenance": {"interval_seconds": 300},
            },
            "letfs": {
                "semantic_search": {"candidate_limit": 50, "result_limit": 10},
                "grpc_listen": "0.0.0.0:9090",
                "grpc_target": "letfs:9090",
                "database": {
                    "name": "letfs",
                    "user": "letfs",
                    "password": "${LETFS_DB_PASSWORD}",
                },
                "max_text_bytes": 1048576,
                "max_blob_bytes": 104857600,
                "multipart_threshold_bytes": (10485760 if mode == "mock" else 16777216),
                "multipart_part_bytes": 8388608,
                "upload_url_ttl_seconds": 900,
                "download_url_ttl_seconds": 300,
                "idempotency_retention_seconds": 86400,
                "processing": {
                    "max_artifacts": 512,
                    "max_manifest_text_bytes": 8388608,
                    "max_artifact_blob_bytes": 268435456,
                    "parse_timeout_seconds": 600 if mode == "mock" else 1200,
                    "enrich_index_timeout_seconds": 900,
                },
                "maintenance": {
                    "interval_seconds": 300,
                    "object_gc_grace_seconds": 86400,
                },
            },
            "leta": leta_section,
            "letfs_ingest": {
                "cpu": {
                    "activity_concurrency": 8,
                    "office_concurrency": 2,
                    "split_tokens": 4096,
                    "datalab": {
                        "concurrency": 2,
                        "result_concurrency": 2,
                        "requests_per_minute": 10,
                        "max_response_bytes": 100663296,
                    },
                    "limits": {
                        "max_pages": 50,
                        "max_page_pixels": 25000000,
                        "max_office_expanded_bytes": 536870912,
                        "max_spreadsheet_cells": 1000000,
                        "max_sheets": 100,
                        "max_output_bytes": 268435456,
                    },
                },
                "io": {
                    "activity_concurrency": 12,
                    "model_concurrency": 16,
                    "embedding_batch_size": 256,
                    "chunk_size_tokens": 512,
                    "chunk_overlap_tokens": 64,
                },
            },
        },
        "deployment": {
            "postgres": {
                "admin_user": "openlet_admin",
                "admin_password": "${POSTGRES_ADMIN_PASSWORD}",
            },
            "temporal": {
                "database": {
                    "name": "temporal",
                    "user": "temporal",
                    "password": "${TEMPORAL_DB_PASSWORD}",
                },
                "visibility_database": "temporal_visibility",
                "namespace_retention_hours": 168,
            },
            "spicedb": {
                "database": {
                    "name": "spicedb",
                    "user": "spicedb",
                    "password": "${SPICEDB_DB_PASSWORD}",
                }
            },
        },
    }
    if override:
        base = deep_merge(base, override)
    return cast(Config, base)


def stage_wiremock_stubs(
    target_dir: Path, *, mode: EnvMode, include_langfuse: bool
) -> None:
    """Populate the project's WireMock mappings directory for mock or live mode."""
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_dir.chmod(0o755)
    for stub in sorted(STUBS_PACKAGE_DIR.glob("*.json")):
        if mode == "mock" or (
            include_langfuse and stub.name.startswith(("langfuse-", "leta-prompt-"))
        ):
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
    """Render compose.env.yaml as YAML text (with Compose `!override` where needed)."""
    shared_uv_cache.mkdir(parents=True, exist_ok=True)
    services: dict[str, dict[str, object]] = {
        "postgres": {"ports": ["127.0.0.1::5432"]},
        "spicedb": {
            "ports": ["127.0.0.1::50051"],
            **(
                {
                    "command": [
                        "serve",
                        "--datastore-engine",
                        "postgres",
                        "--http-enabled=false",
                        "--skip-release-check",
                        "--datastore-revision-quantization-interval=100ms",
                    ]
                }
                if mode == "mock"
                else {}
            ),
        },
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
        "litellm": {
            "healthcheck": {"interval": "2s", "timeout": "5s", "retries": 45},
            **(
                {"depends_on": {"wiremock": {"condition": "service_healthy"}}}
                if mode == "mock"
                else {}
            ),
        },
        "envoy": {
            "ports": [f"127.0.0.1:{gateway_port}:8080"],
        },
    }

    if mode == "mock":
        services["ingest-cpu"] = {
            "depends_on": {"wiremock": {"condition": "service_healthy"}},
            "stop_grace_period": "5s",
        }
        services["ingest-io"] = {"stop_grace_period": "5s"}
        services["platform"]["stop_grace_period"] = "5s"
        services["letfs"] = {"stop_grace_period": "5s"}
        services["litellm"]["stop_grace_period"] = "5s"
        if "leta" in profiles:
            services["leta-api"] = {"stop_grace_period": "5s"}
            services["leta-worker"] = {"stop_grace_period": "5s"}

    overlay: dict[str, object] = {
        "services": services,
        "volumes": {"rustfs-data": {}},
    }
    text = yaml.safe_dump(overlay, sort_keys=False).replace("$", "$$")

    # Inject `!override` for envoy ports (replaces configure.py port list) and mock litellm config.
    text = text.replace(
        f"  envoy:\n    ports:\n    - 127.0.0.1:{gateway_port}:8080",
        f"  envoy:\n    ports: !override\n    - 127.0.0.1:{gateway_port}:8080",
    )
    if mode == "mock":
        mock_litellm = STUBS_PACKAGE_DIR / "litellm.yaml"
        text = text.replace(
            "  litellm:\n",
            f"  litellm:\n    volumes: !override\n    - {mock_litellm}:/etc/litellm/config.yaml:ro\n",
        )
    return text


def read_user_env(repo_root: Path, dotenv_path: Path | None = None) -> dict[str, str]:
    """Merge `.env` (lowest priority) with current process `os.environ` (highest priority)."""
    dotenv = repo_root / ".env" if dotenv_path is None else dotenv_path
    merged = load_dotenv(dotenv)
    merged.update(os.environ)
    return merged
