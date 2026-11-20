import json
from pathlib import Path, PurePosixPath
from typing import Literal, cast

type FileKind = Literal["text", "blob", "unsupported"]

_data = Path(__file__).resolve().parents[3] / "contracts" / "file-types.json"
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
