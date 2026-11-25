import json
from pathlib import Path, PurePosixPath
from typing import Literal, cast

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


_data = _locate_file_types()
_types = cast(dict[str, dict[str, str]], json.loads(_data.read_text(encoding="utf-8")))


def classify_extension(extension: str) -> tuple[FileKind, str]:
    extension = extension.removeprefix(".").lower()
    if media := _types["text"].get(extension):
        return "text", media
    if media := _types["blob"].get(extension):
        return "blob", media
    return "unsupported", ""


def classify_file(name: str) -> tuple[FileKind, str]:
    return classify_extension(PurePosixPath(name).suffix)
