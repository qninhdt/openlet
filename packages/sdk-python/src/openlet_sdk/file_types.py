"""File extension classification backed by the shared file-types contract."""

import json
from pathlib import Path, PurePosixPath
from typing import Literal

from openlet_sdk.types import is_str_mapping

type FileKind = Literal["text", "blob", "unsupported"]


def _locate_file_types() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        *(
            parent / "contracts" / "file-types.json"
            for parent in here.parents
            if parent.name == "packages"
        ),
        Path.cwd() / "packages" / "contracts" / "file-types.json",
        Path("/app/packages/contracts/file-types.json"),
        Path("/packages/contracts/file-types.json"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Could not locate packages/contracts/file-types.json")


def _load_file_types(path: Path) -> dict[str, dict[str, str]]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not is_str_mapping(raw):
        raise ValueError(f"Expected JSON object in {path}")
    result: dict[str, dict[str, str]] = {}
    for kind, entries in raw.items():
        if not is_str_mapping(entries):
            raise ValueError(f"Expected mapping for {kind!r} in {path}")
        result[kind] = {ext: str(media) for ext, media in entries.items()}
    return result


_data = _locate_file_types()
_types = _load_file_types(_data)


def classify_extension(extension: str) -> tuple[FileKind, str]:
    """Classify a file extension into its ingest kind and media type."""
    extension = extension.removeprefix(".").lower()
    if media := _types["text"].get(extension):
        return "text", media
    if media := _types["blob"].get(extension):
        return "blob", media
    return "unsupported", ""


def classify_file(name: str) -> tuple[FileKind, str]:
    """Classify a filename into its ingest kind and media type."""
    return classify_extension(PurePosixPath(name).suffix)
