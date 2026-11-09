import json

import pytest
from pydantic import ValidationError

from leta.config import ModelCatalog, ModelSelection, Settings


def test_model_inheritance_and_explicit_null(catalog_data):
    catalog = ModelCatalog.model_validate(catalog_data)
    root = ModelSelection(model_id="provider/model", reasoning_effort="high")
    override = ModelSelection(model_id="provider/model", reasoning_effort=None)
    assert catalog.resolve() == catalog.default
    assert catalog.resolve(root) == root
    assert catalog.resolve(root, override).reasoning_effort is None
    with pytest.raises(ValueError, match="unsupported"):
        catalog.resolve(ModelSelection(model_id="unknown", reasoning_effort=None))
    with pytest.raises(ValueError, match="unsupported"):
        catalog.resolve(
            ModelSelection(model_id="provider/model", reasoning_effort="max")
        )


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data["models"].append(data["models"][0]),
        lambda data: data["models"][0].update(reasoning_efforts=[]),
        lambda data: data["models"][0].update(reasoning_efforts=["low", "low"]),
        lambda data: data["models"][0].update(reasoning_efforts=[""]),
        lambda data: data["models"][0].update(
            max_output_tokens=data["models"][0]["context_window_tokens"]
        ),
        lambda data: data["models"][0].update(context_window_tokens=0),
        lambda data: data["models"][0].update(context_window_tokens=True),
        lambda data: data["default"].update(model_id="unknown"),
        lambda data: data["default"].pop("reasoning_effort"),
        lambda data: data.update(extra="invalid"),
    ],
)
def test_invalid_catalog(catalog_data, change):
    change(catalog_data)
    with pytest.raises(ValidationError):
        ModelCatalog.model_validate(catalog_data)


def test_settings_hide_secrets(settings):
    text = repr(settings)
    for value in (
        settings.database_url,
        settings.provider_key,
        settings.spicedb_key,
        settings.service_token,
        settings.gateway_token,
    ):
        assert value not in text


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ALLOW_PLAINTEXT_RPC", "yes"),
        ("DATABASE_URL", "postgresql://secret@"),
        ("REDIS_URL", "http://localhost:6379"),
        ("TEMPORAL_ADDRESS", "https://localhost:7233"),
        ("LISTEN_ADDR", "localhost:99999"),
        ("GATEWAY_TOKEN", "short"),
        ("WORKSPACE_SERVICE_TOKEN", "short"),
        ("OPENROUTER_BASE_URL", "file:///etc/passwd"),
        ("OPENROUTER_BASE_URL", "https://user:password@openrouter.ai/api/v1"),
        ("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1?key=private"),
        ("OPENROUTER_API_KEY", ""),
        ("OPENROUTER_API_KEY", "   "),
        ("OPENROUTER_API_KEY", "provider-key\r\ninvalid"),
        ("SPICEDB_GRPC_PRESHARED_KEY", "   "),
        ("SPICEDB_GRPC_PRESHARED_KEY", "spicedb-key\r\ninvalid"),
    ],
)
def test_invalid_settings(configured_env, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError) as caught:
        Settings.from_env()
    if value:
        assert value not in str(caught.value)


def test_tls_required_outside_explicit_dev(configured_env, monkeypatch):
    monkeypatch.setenv("ALLOW_PLAINTEXT_RPC", "false")
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings.from_env()
    monkeypatch.setenv(
        "DATABASE_URL", configured_env["DATABASE_URL"] + "?sslmode=verify-full"
    )
    with pytest.raises(ValueError, match="REDIS_URL"):
        Settings.from_env()
    monkeypatch.setenv("REDIS_URL", "rediss://localhost:6379/0")
    with pytest.raises(ValueError, match="RPC_TLS_CERT_PATH"):
        Settings.from_env()
    monkeypatch.setenv("RPC_TLS_CERT_PATH", "/run/secrets/rpc.crt")
    with pytest.raises(ValueError, match="RPC_TLS_KEY_PATH"):
        Settings.from_env()
    monkeypatch.setenv("RPC_TLS_KEY_PATH", "/run/secrets/rpc.key")
    assert Settings.from_env().allow_plaintext is False


def test_file_secret_precedence_and_failure(configured_env, monkeypatch, tmp_path):
    path = tmp_path / "token"
    path.write_text("f" * 32 + "\n")
    monkeypatch.setenv("GATEWAY_TOKEN_FILE", str(path))
    assert Settings.from_env().gateway_token == "f" * 32
    path.unlink()
    with pytest.raises(ValueError, match="GATEWAY_TOKEN"):
        Settings.from_env()


def test_catalog_file_errors_are_safe(configured_env, tmp_path, catalog_data):
    path = tmp_path / "private.json"
    with pytest.raises(ValueError, match="^invalid model catalog$"):
        ModelCatalog.load(path)
    catalog_data["default"]["model_id"] = "sensitive-model-input"
    path.write_text(json.dumps(catalog_data))
    with pytest.raises(ValueError, match="^invalid model catalog$"):
        ModelCatalog.load(path)
