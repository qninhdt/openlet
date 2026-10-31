import json
import stat
from pathlib import Path

import pytest
from configure import configure


def settings():
    return {
        "JWT_ISSUER": "https://identity.example.test",
        "JWKS_URL": "https://identity.example.test/jwks",
        "JWT_AUDIENCE": "openlet",
        "S3_ENDPOINT": "https://storage.example.test",
        "CLERK_SECRET_KEY": "test-clerk-secret",
        "S3_ACCESS_KEY_ID": "test-access-key",
        "S3_SECRET_ACCESS_KEY": "test-storage-secret",
        "OPENROUTER_API_KEY": "test-model-secret",
    }


def test_bootstrap_preserves_credentials_and_private_mount_permissions(tmp_path: Path):
    state = tmp_path / "development"
    configure(state, settings())
    original = {p.name: p.read_text() for p in (state / "secrets").iterdir()}
    changed = {**settings(), "CLERK_SECRET_KEY": "different"}
    configure(state, changed)
    assert {p.name: p.read_text() for p in (state / "secrets").iterdir()} == original
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert stat.S_IMODE((state / "secrets").stat().st_mode) == 0o700
    assert stat.S_IMODE((state / "envoy.json").stat().st_mode) == 0o644
    envoy = json.loads((state / "envoy.json").read_text())
    cluster = next(
        c for c in envoy["static_resources"]["clusters"] if c["name"] == "jwks"
    )
    assert cluster["transport_socket"]["typed_config"]["sni"] == "identity.example.test"
    assert original["gateway_token"] in (state / "envoy.json").read_text()


@pytest.mark.parametrize(
    "key,value",
    [
        ("JWKS_URL", "http://identity.example.test/jwks"),
        ("S3_ENDPOINT", "https://user:secret@storage.example.test"),
        ("JWT_ISSUER", "https://identity.example.test?"),
        ("OPENROUTER_URL", "https://models.example.test/#fragment"),
    ],
)
def test_rejects_unsafe_endpoints_before_creating_state(tmp_path: Path, key, value):
    state = tmp_path / "development"
    with pytest.raises(ValueError):
        configure(state, {**settings(), key: value})
    assert not state.exists()


def test_development_bootstrap_refuses_e2e_identity(tmp_path: Path):
    state = tmp_path / "api-e2e"
    state.mkdir()
    (state / "environment.json").write_text('{"project":"openlet-api-e2e"}')
    with pytest.raises(ValueError, match="E2E"):
        configure(state, settings())
    assert not (state / "secrets").exists()
