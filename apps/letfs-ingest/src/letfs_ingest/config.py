import os
from dataclasses import dataclass
from pathlib import Path

from openlet.config import required, secret
from openlet.rpc import validate


@dataclass(frozen=True)
class WorkerConfig:
    role: str
    temporal_address: str
    temporal_namespace: str
    rpc_address: str
    rpc_token: str
    allow_plaintext: bool
    models: Path | None

    @classmethod
    def from_env(cls, role: str):
        if role not in {"cpu", "io"}:
            raise ValueError("worker role must be cpu or io")
        plaintext = os.getenv("ALLOW_PLAINTEXT_RPC", "false")
        if plaintext not in {"true", "false"}:
            raise ValueError("ALLOW_PLAINTEXT_RPC must be true or false")
        rpc_address = required("LETFS_RPC_ADDRESS")
        rpc_token = secret("INGEST_SERVICE_TOKEN")
        validate(rpc_address, rpc_token)
        models = Path(required("DOCLING_MODELS_PATH")) if role == "cpu" else None
        return cls(
            role,
            required("TEMPORAL_ADDRESS"),
            required("TEMPORAL_NAMESPACE"),
            rpc_address,
            rpc_token,
            plaintext == "true",
            models,
        )
