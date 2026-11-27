"""Unit tests for openlet_env pure logic (config, auth, cache, dataset)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import jwt
import numpy as np
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from openlet_env import cache, config, dataset
from openlet_env.auth import LocalAuth

if TYPE_CHECKING:
    from pathlib import Path

    from openlet_sdk.types import MutableJsonObject


def test_deep_merge_is_pure_and_recursive() -> None:
    base: MutableJsonObject = {"a": {"x": 1, "y": 2}, "b": 3}
    override: MutableJsonObject = {"a": {"y": 99, "z": 4}}
    merged = config.deep_merge(base, override)
    assert merged == {"a": {"x": 1, "y": 99, "z": 4}, "b": 3}
    assert base == {"a": {"x": 1, "y": 2}, "b": 3}


def test_ensure_secrets_generates_and_reuses(tmp_path: Path) -> None:
    secret_file = tmp_path / "secrets.env"
    first = config.ensure_secrets(secret_file)
    assert secret_file.is_file()
    assert all(first[k] for k in config.INTERNAL_SECRET_KEYS)
    assert first["S3_ACCESS_KEY_ID"].startswith("openlet-")
    second = config.ensure_secrets(secret_file)
    assert second == first


def test_resolve_effective_mode_auto_fallback() -> None:
    assert config.resolve_effective_mode("mock", {}) == ("mock", False)
    assert config.resolve_effective_mode("live", {}) == ("mock", True)
    assert config.resolve_effective_mode("live", {"OPENAI_API_KEY": "sk-test"}) == (
        "live",
        False,
    )


def test_build_openlet_config_sets_public_endpoint_and_override() -> None:
    cfg = config.build_openlet_config(
        mode="mock",
        gateway_port=8080,
        rustfs_port=9123,
        user_env={},
        override={"services": {"platform": {"max_members": 12}}},
    )
    assert cfg["dependencies"]["s3"]["endpoint"] == "http://rustfs:9000"
    assert cfg["dependencies"]["s3"].get("public_endpoint") == "http://127.0.0.1:9123"
    assert cfg["services"]["platform"]["max_members"] == 12
    assert cfg["auth"]["clerk"]["issuer"] == "http://wiremock:8080"
    assert "observability" not in cfg
    assert cfg["models"].get("reranking") == {"model": "cohere/rerank-v3.5"}


def test_render_compose_overlay_emits_override_tags(tmp_path: Path) -> None:
    overlay = config.render_compose_overlay(
        mode="mock",
        profiles=("leta",),
        runtime_env={
            "S3_ACCESS_KEY_ID": "openlet-abc",
            "S3_SECRET_ACCESS_KEY": "sec$ret",
        },
        gateway_port=18080,
        rustfs_port=19000,
        wiremock_port=18081,
        wiremock_dir=tmp_path / "wiremock",
        shared_uv_cache=tmp_path / "uv-cache",
    )
    assert "ports: !override\n    - 127.0.0.1:18080:8080" in overlay
    assert "volumes: !override\n" in overlay
    assert "sec$$ret" in overlay


def test_local_auth_roundtrip_jwt_with_jwks(tmp_path: Path) -> None:
    auth = LocalAuth.load_or_create(tmp_path)
    token = auth.sign("user_alice", "11111111-1111-1111-1111-111111111111")
    jwks = auth.jwks()
    keys = jwks["keys"]
    assert len(keys) == 1
    pub = RSAAlgorithm.from_jwk(json.dumps(keys[0]))
    assert isinstance(pub, rsa.RSAPublicKey)
    decoded = jwt.decode(
        token,
        pub,
        algorithms=["RS256"],
        audience="openlet",
        issuer="http://wiremock:8080",
    )
    assert decoded["sub"] == "user_alice"
    assert decoded["public_metadata"] == {
        "openlet_user_id": "11111111-1111-1111-1111-111111111111"
    }
    reloaded = LocalAuth.load_or_create(tmp_path)
    assert reloaded.kid == auth.kid


def test_cache_fingerprint_ignores_concurrency_and_reads_format6(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "report.pdf"
    sample.write_bytes(b"%PDF-1.4\nhello\n")

    cfg1 = config.build_openlet_config(
        mode="live", gateway_port=8080, rustfs_port=9000, user_env={}
    )
    cfg2 = config.build_openlet_config(
        mode="live",
        gateway_port=8080,
        rustfs_port=9000,
        user_env={},
        override={
            "services": {
                "letfs_ingest": {
                    "cpu": {
                        "activity_concurrency": 32,
                        "office_concurrency": 16,
                        "datalab": {"concurrency": 20, "requests_per_minute": 500},
                    }
                }
            }
        },
    )
    assert cache.fingerprint(sample, cfg1) == cache.fingerprint(sample, cfg2)

    # Verify backward compatibility with format 6 metadata (from HF openlet-datasets).
    fp = cache.fingerprint(sample, cfg1)
    folder = tmp_path / cache.CACHE_DIR / sample.name
    (folder / "artifacts").mkdir(parents=True)
    (folder / "artifacts/README.md").write_text("# Report\n", encoding="utf-8")
    format6_input = {
        "format": 6,
        "source": fp.source,
        "sha256": fp.sha256,
        "embedding": fp.embedding,
        "enrichment": fp.enrichment,
        "prompt_label": fp.prompt_label,
        "parser": {
            "activity_concurrency": 99,
            "split_tokens": fp.split_tokens,
            "limits": fp.limits,
        },
        "chunk_size_tokens": fp.chunk_size_tokens,
        "chunk_overlap_tokens": fp.chunk_overlap_tokens,
    }
    (folder / "metadata.json").write_text(
        json.dumps(
            {"input": format6_input, "files": {".": ["Title", "Desc"]}, "points": []}
        ),
        encoding="utf-8",
    )
    vec = np.zeros((1, 1536), dtype=np.float32)
    vec[0, 0] = 1.0
    np.savez(
        folder / "embeddings.npz",
        text_sha256=np.asarray([list(cache.text_key("hello"))], dtype=np.uint8),
        vectors=vec,
    )
    loaded = cache.read_cache(sample, cfg2)
    assert loaded is not None
    assert loaded.metadata.files == {".": ["Title", "Desc"]}


def test_read_seed_specs_and_referenced_users(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "users": {
                    "alice": {"first_name": "Alice", "last_name": "Ng"},
                    "bob": {"first_name": "Bob", "last_name": "Le"},
                    "unused": {"first_name": "Unused", "last_name": "User"},
                }
            }
        ),
        encoding="utf-8",
    )
    ws = tmp_path / "workspaces/demo"
    (ws / "storages/shared").mkdir(parents=True)
    (ws / "storages/shared/readme.md").write_text("hi\n", encoding="utf-8")
    (ws / "manifest.json").write_text(
        json.dumps({"name": "Demo", "owner": "alice", "members": ["bob"]}),
        encoding="utf-8",
    )
    users, specs = dataset.read_seed_specs(tmp_path, ["demo"])
    assert len(users) == 3
    assert dataset.referenced_users(specs) == {"alice", "bob"}
    assert "shared" in specs[0].storages

    with pytest.raises(ValueError, match="invalid seed handle"):
        dataset.validate_slug("Bad_Handle")
