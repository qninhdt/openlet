"""Read seed manifests and storage trees."""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from openlet_sdk.file_types import classify_file

from .api import JSON
from .cache import CACHE_DIR


@dataclass
class Workspace:
    handle: str
    manifest: JSON
    storages: dict[str, Path]


def slug(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", value):
        raise ValueError(f"invalid seed handle: {value}")
    return value


def manifest(root: Path) -> JSON:
    path = root / "manifest.json"
    result: object = json.loads(path.read_text())
    if not isinstance(result, dict):
        raise ValueError(f"expected an object in {path}")
    return cast(JSON, result)


def files(root: Path) -> Iterator[Path]:
    for path in sorted(root.iterdir()):
        if path.is_symlink():
            raise ValueError(f"symlinks are unsupported in seeds: {path}")
        if path.name == CACHE_DIR:
            continue
        if path.is_dir():
            yield path
            yield from files(path)
        elif path.is_file():
            yield path
        else:
            raise ValueError(f"expected a regular file or directory: {path}")


def read_seeds(root: Path, selected: list[str]) -> tuple[JSON, list[Workspace]]:
    users = cast(JSON, manifest(root)["users"])
    for handle, profile in users.items():
        slug(handle)
        if not all(
            isinstance(profile[key], str) for key in ("first_name", "last_name")
        ):
            raise ValueError(f"invalid user profile: {handle}")
    base = root / "workspaces"
    workspaces: list[Workspace] = []
    for handle in dict.fromkeys(
        selected or sorted(p.name for p in base.iterdir() if p.is_dir())
    ):
        directory = base / slug(handle)
        data = manifest(directory)
        members = {data["owner"], *data.get("members", [])}
        agents = cast(JSON, data.get("agents", {}))
        if not members <= users.keys() or agents.keys() & members:
            raise ValueError(f"invalid user or agent references in {handle}")
        allowed = {"shared", *(f"personal/{name}" for name in members | agents.keys())}
        for name, agent in agents.items():
            slug(name)
            if (
                agent.get("owner", data["owner"]) not in members
                or not set(agent.get("operators", [])) <= members
            ):
                raise ValueError(f"unknown agent owner or operator in {handle}/{name}")
        for label, pair in cast(JSON, data.get("conversations", {})).items():
            if (
                pair["agent"] not in agents
                or pair["user"] not in members
                or label != f"{pair['agent']}-{pair['user']}"
            ):
                raise ValueError(f"invalid conversation in {handle}: {label}")
            allowed.add(f"conversation/{label}")
        storages: dict[str, Path] = {}
        storage_dir = directory / "storages"
        for path in storage_dir.iterdir() if storage_dir.exists() else ():
            if (
                path.name in {"personal", "conversation"}
                and path.is_dir()
                and not path.is_symlink()
            ):
                candidates = path.iterdir()
            else:
                candidates = iter([path])
            for storage in candidates:
                key = storage.relative_to(storage_dir).as_posix()
                if key not in allowed or not storage.is_dir() or storage.is_symlink():
                    raise ValueError(f"unknown seed storage: {storage}")
                for entry in files(storage):
                    if (
                        entry.is_file()
                        and classify_file(entry.name)[0] == "unsupported"
                    ):
                        raise ValueError(f"unsupported seed file: {entry}")
                storages[key] = storage
        for grant in data.get("grants", []):
            if (
                grant["storage"] not in allowed
                or grant["storage"].startswith("conversation/")
                or grant["actor"] not in members | agents.keys()
                or grant["role"] not in {"editor", "viewer"}
            ):
                raise ValueError(f"invalid storage grant in {handle}: {grant}")
        workspaces.append(Workspace(handle, data, storages))
    if not workspaces:
        raise ValueError("the seed set contains no workspaces")
    return users, workspaces


def external_id(namespace: str, handle: str) -> str:
    # Keep the generated email local part within its 64-character limit.
    return f"openlet-{namespace[:16]}-{handle}"
