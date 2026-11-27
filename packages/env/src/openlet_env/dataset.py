"""Dataset resolution, partial HuggingFace download, and seed manifest parsing."""

from __future__ import annotations

import fcntl
import re
import subprocess
from collections.abc import Iterator, Sequence
from pathlib import Path

from openlet_sdk.file_types import classify_file
from pydantic import ValidationError

from .cache import CACHE_DIR
from .models import (
    RootManifest,
    SyncMarker,
    UserProfile,
    WorkspaceManifest,
    WorkspaceSpec,
)

DEFAULT_HF_REPO = "qninhdt/openlet-datasets"
DEFAULT_HF_REVISION = "main"
SYNC_MARKER = ".openlet-sync.json"
LEGACY_MARKER = ".openlet-dataset-revision"


def validate_slug(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", value):
        raise ValueError(f"invalid seed handle: {value}")
    return value


def iter_seed_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.iterdir()):
        if path.is_symlink():
            raise ValueError(f"symlinks are unsupported in seeds: {path}")
        if path.name == CACHE_DIR:
            continue
        if path.is_dir():
            yield path
            yield from iter_seed_files(path)
        elif path.is_file():
            yield path
        else:
            raise ValueError(f"expected a regular file or directory: {path}")


def read_seed_specs(
    root: Path, selected: Sequence[str] = ()
) -> tuple[dict[str, UserProfile], list[WorkspaceSpec]]:
    """Validate and load user profiles + selected workspace specifications."""
    manifest_path = root / "manifest.json"
    try:
        root_manifest = RootManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except ValidationError as exc:
        raise ValueError(f"invalid root manifest in {manifest_path}: {exc}") from exc

    users = root_manifest.users
    for handle in users:
        validate_slug(handle)

    base = root / "workspaces"
    handles = list(
        dict.fromkeys(
            selected
            if selected
            else sorted(p.name for p in base.iterdir() if p.is_dir())
        )
    )
    workspaces: list[WorkspaceSpec] = []
    for handle in handles:
        directory = base / validate_slug(handle)
        ws_manifest_path = directory / "manifest.json"
        try:
            data = WorkspaceManifest.model_validate_json(
                ws_manifest_path.read_text(encoding="utf-8")
            )
        except ValidationError as exc:
            raise ValueError(
                f"invalid workspace manifest in {ws_manifest_path}: {exc}"
            ) from exc

        owner = data.owner
        members = {owner, *data.members}
        agents = data.agents
        if not members <= users.keys() or agents.keys() & members:
            raise ValueError(f"invalid user or agent references in {handle}")
        allowed = {"shared", *(f"personal/{name}" for name in members | agents.keys())}
        for name, agent in agents.items():
            validate_slug(name)
            agent_owner = agent.owner or owner
            operators = set(agent.operators)
            if agent_owner not in members or not operators <= members:
                raise ValueError(f"unknown agent owner or operator in {handle}/{name}")
        for label, pair in data.conversations.items():
            if (
                pair.agent not in agents
                or pair.user not in members
                or label != f"{pair.agent}-{pair.user}"
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
                candidates = list(path.iterdir())
            else:
                candidates = [path]
            for storage in candidates:
                key = storage.relative_to(storage_dir).as_posix()
                if key not in allowed or not storage.is_dir() or storage.is_symlink():
                    raise ValueError(f"unknown seed storage: {storage}")
                for entry in iter_seed_files(storage):
                    if (
                        entry.is_file()
                        and classify_file(entry.name)[0] == "unsupported"
                    ):
                        raise ValueError(f"unsupported seed file: {entry}")
                storages[key] = storage
        for grant in data.grants:
            if (
                grant.storage not in allowed
                or grant.storage.startswith("conversation/")
                or grant.actor not in members | agents.keys()
            ):
                raise ValueError(f"invalid storage grant in {handle}: {grant}")
        workspaces.append(
            WorkspaceSpec(handle=handle, manifest=data, storages=storages)
        )
    if not workspaces:
        raise ValueError("the seed set contains no workspaces")
    return users, workspaces


def referenced_users(workspaces: Sequence[WorkspaceSpec]) -> set[str]:
    """Return only the user handles referenced by the selected workspaces."""
    needed: set[str] = set()
    for spec in workspaces:
        needed.add(spec.manifest.owner)
        needed.update(spec.manifest.members)
    return needed


def ensure_dataset(
    directory: Path,
    *,
    workspaces: Sequence[str] = (),
    repo_id: str = DEFAULT_HF_REPO,
    revision: str = DEFAULT_HF_REVISION,
) -> Path:
    """Ensure requested workspaces exist locally, using partial HF download when needed."""
    requested = [validate_slug(w) for w in dict.fromkeys(workspaces)]
    if _already_present(directory, requested):
        return directory

    scratch = directory.parent / ".local"
    scratch.mkdir(parents=True, exist_ok=True)
    with (scratch / "dataset.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if _already_present(directory, requested):
            return directory

        directory.mkdir(parents=True, exist_ok=True)
        cmd = [
            "hf",
            "download",
            repo_id,
            "--repo-type",
            "dataset",
            "--revision",
            revision,
            "--local-dir",
            str(directory),
            "--quiet",
        ]
        if requested:
            cmd.extend(["--include", "manifest.json"])
            for handle in requested:
                cmd.extend(["--include", f"workspaces/{handle}/**"])
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)

        sync_path = directory / SYNC_MARKER
        existing = (
            SyncMarker.model_validate_json(sync_path.read_text("utf-8"))
            if sync_path.is_file()
            else SyncMarker()
        )
        synced = set(existing.workspaces)
        if requested:
            synced.update(requested)
        else:
            ws_dir = directory / "workspaces"
            if ws_dir.is_dir():
                synced.update(p.name for p in ws_dir.iterdir() if p.is_dir())
        updated = SyncMarker(
            repo_id=repo_id,
            revision=revision,
            full=not requested or existing.full,
            workspaces=sorted(synced),
        )
        sync_path.write_text(updated.model_dump_json(indent=2) + "\n", encoding="utf-8")
        read_seed_specs(directory, requested)
    return directory


def _already_present(directory: Path, requested: Sequence[str]) -> bool:
    if not (directory / "manifest.json").is_file():
        return False
    ws_dir = directory / "workspaces"
    if not ws_dir.is_dir():
        return False
    if requested:
        return all(
            (ws_dir / handle / "manifest.json").is_file() for handle in requested
        )
    # Full dataset request: satisfied if sync marker says full or legacy marker exists.
    sync_path = directory / SYNC_MARKER
    if sync_path.is_file():
        record = SyncMarker.model_validate_json(sync_path.read_text("utf-8"))
        if record.full:
            return True
    return (directory / LEGACY_MARKER).is_file()
