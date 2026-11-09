import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from openlet.config import required, secret
from openlet.rpc import validate
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class ModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    model_id: str = Field(min_length=1)
    reasoning_effort: str | None


class ModelDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    model_id: str = Field(min_length=1)
    reasoning_efforts: list[str | None] = Field(min_length=1)
    context_window_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_definition(self):
        if self.model_id.strip() != self.model_id:
            raise ValueError("invalid model_id")
        if len(set(self.reasoning_efforts)) != len(self.reasoning_efforts) or any(
            effort is not None and (not effort or effort.strip() != effort)
            for effort in self.reasoning_efforts
        ):
            raise ValueError("invalid reasoning_efforts")
        if self.max_output_tokens >= self.context_window_tokens:
            raise ValueError("output tokens must be below context window")
        return self


class ModelCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    models: list[ModelDefinition] = Field(min_length=1)
    default: ModelSelection

    @model_validator(mode="after")
    def validate_catalog(self):
        if len({model.model_id for model in self.models}) != len(self.models):
            raise ValueError("duplicate model_id")
        self.resolve(self.default)
        return self

    def resolve(
        self,
        root: ModelSelection | None = None,
        override: ModelSelection | None = None,
    ) -> ModelSelection:
        for choice in (root, override):
            if choice is not None and not any(
                choice.model_id == model.model_id
                and choice.reasoning_effort in model.reasoning_efforts
                for model in self.models
            ):
                raise ValueError("unsupported model_id/reasoning_effort selection")
        return override or root or self.default

    def inherit(
        self, root: ModelSelection, model_id: str | None, reasoning_effort: str | None
    ) -> ModelSelection:
        self.resolve(root)
        return self.resolve(
            ModelSelection(
                model_id=model_id or root.model_id,
                reasoning_effort=(
                    reasoning_effort
                    if reasoning_effort is not None
                    else root.reasoning_effort
                ),
            )
        )

    @classmethod
    def load(cls, path: Path):
        try:
            return cls.model_validate_json(path.read_bytes())
        except OSError, ValidationError:
            raise ValueError("invalid model catalog") from None


def _endpoint(name: str, schemes: set[str], *, plaintext: bool) -> str:
    value = secret(name)
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in schemes
            and parsed.hostname
            and not parsed.fragment
            and not any(ord(char) <= 32 for char in value)
        )
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            valid = False
        if parsed.scheme in {"http", "https"}:
            valid = (
                valid
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
            )
        if not plaintext:
            if parsed.scheme == "postgresql":
                valid = valid and parse_qs(parsed.query).get("sslmode") == [
                    "verify-full"
                ]
            else:
                valid = valid and parsed.scheme in {"https", "rediss"}
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"invalid {name}")
    return value


def _token(name: str) -> str:
    value = secret(name)
    try:
        validate("localhost:1", value)
    except ValueError:
        raise ValueError(f"invalid {name}") from None
    return value


@dataclass(frozen=True)
class Settings:
    listen_addr: str
    rpc_listen_addr: str
    database_url: str = field(repr=False)
    temporal_address: str
    temporal_namespace: str
    redis_url: str = field(repr=False)
    gateway_token: str = field(repr=False)
    service_token: str = field(repr=False)
    workspace_service_token: str = field(repr=False)
    account_rpc_address: str
    workspace_rpc_address: str
    letfs_rpc_address: str
    spicedb_address: str
    spicedb_key: str = field(repr=False)
    allow_plaintext: bool
    provider_endpoint: str = field(repr=False)
    provider_key: str = field(repr=False)
    models: ModelCatalog
    rpc_certificate_path: Path | None = None
    rpc_private_key_path: Path | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls):
        plaintext = os.getenv("ALLOW_PLAINTEXT_RPC", "false")
        if plaintext not in {"true", "false"}:
            raise ValueError("ALLOW_PLAINTEXT_RPC must be true or false")
        allow_plaintext = plaintext == "true"
        service_token = _token("LETA_SERVICE_TOKEN")
        addresses = {
            name: required(name)
            for name in (
                "LISTEN_ADDR",
                "RPC_LISTEN_ADDR",
                "TEMPORAL_ADDRESS",
                "ACCOUNT_RPC_ADDRESS",
                "WORKSPACE_RPC_ADDRESS",
                "LETFS_RPC_ADDRESS",
                "SPICEDB_ADDRESS",
            )
        }
        for name, address in addresses.items():
            try:
                validate(address, service_token)
            except ValueError:
                raise ValueError(f"invalid {name}") from None
        spicedb_key = secret("SPICEDB_GRPC_PRESHARED_KEY")
        provider_key = secret("OPENROUTER_API_KEY")
        if any(
            not key.strip() or "\r" in key or "\n" in key
            for key in (spicedb_key, provider_key)
        ):
            raise ValueError("invalid SpiceDB or provider credentials")
        return cls(
            listen_addr=addresses["LISTEN_ADDR"],
            rpc_listen_addr=addresses["RPC_LISTEN_ADDR"],
            database_url=_endpoint(
                "DATABASE_URL", {"postgresql"}, plaintext=allow_plaintext
            ),
            temporal_address=addresses["TEMPORAL_ADDRESS"],
            temporal_namespace=required("TEMPORAL_NAMESPACE"),
            redis_url=_endpoint(
                "REDIS_URL", {"redis", "rediss"}, plaintext=allow_plaintext
            ),
            gateway_token=_token("GATEWAY_TOKEN"),
            service_token=service_token,
            workspace_service_token=_token("WORKSPACE_SERVICE_TOKEN"),
            account_rpc_address=addresses["ACCOUNT_RPC_ADDRESS"],
            workspace_rpc_address=addresses["WORKSPACE_RPC_ADDRESS"],
            letfs_rpc_address=addresses["LETFS_RPC_ADDRESS"],
            spicedb_address=addresses["SPICEDB_ADDRESS"],
            spicedb_key=spicedb_key,
            allow_plaintext=allow_plaintext,
            provider_endpoint=_endpoint(
                "OPENROUTER_BASE_URL", {"http", "https"}, plaintext=allow_plaintext
            ),
            provider_key=provider_key,
            models=ModelCatalog.load(Path(required("LETA_MODEL_CATALOG_PATH"))),
            rpc_certificate_path=(
                None if allow_plaintext else Path(required("RPC_TLS_CERT_PATH"))
            ),
            rpc_private_key_path=(
                None if allow_plaintext else Path(required("RPC_TLS_KEY_PATH"))
            ),
        )
