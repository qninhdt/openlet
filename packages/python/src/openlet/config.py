import os
from pathlib import Path


def secret(key: str) -> str:
    path = os.getenv(f"{key}_FILE")
    if path is not None:
        try:
            return Path(path).read_text().strip()
        except OSError:
            return ""
    return os.getenv(key, "")


def required(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value
