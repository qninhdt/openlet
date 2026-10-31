"""Coordinate private local backups and fenced restores using native tools."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
DATABASES = ("account", "workspace", "letfs", "temporal", "temporal_visibility")
POSTGRES_IMAGE = "postgres:18.6-trixie@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336"
CONFIGURATION = ("init.sql", "temporal.json", "envoy.json", "storage.json")
WRITERS = (
    "envoy",
    "account",
    "workspace",
    "letfs",
    "processor-cpu",
    "processor-io",
    "temporal",
    "boundary",
    "storage",
    "qdrant",
)


def native(arguments, *, stdin=None, stdout=subprocess.PIPE):
    result = subprocess.run(
        arguments,
        stdin=stdin,
        stdout=stdout,
        stderr=subprocess.PIPE,
        timeout=240,
        check=False,
    )
    if result.returncode:
        step = next(
            (
                value
                for value in reversed(arguments)
                if value
                in {"config", "up", "create", "pg_dump", "pg_restore", "psql", "tar"}
            ),
            arguments[0],
        )
        detail = ""
        if step in {"pg_dump", "pg_restore", "psql"}:
            detail = next(
                (
                    line
                    for line in result.stderr.decode(errors="replace").splitlines()
                    if line.startswith(f"{step}: error:")
                ),
                "",
            )
        if step in {"up", "create"}:
            message = result.stderr.decode(errors="replace").lower()
            detail = next(
                (
                    label
                    for marker, label in (
                        ("port is already allocated", "port already allocated"),
                        ("address already in use", "address already in use"),
                        ("unhealthy", "container unhealthy"),
                        ("pull access denied", "image unavailable"),
                        ("failed to solve", "image build failed"),
                    )
                    if marker in message
                ),
                "inspect Compose status and service logs",
            )
        # SQL payload/context lines and connection credentials stay out of diagnostics.
        raise RuntimeError(
            f"{step} failed (exit {result.returncode}); {detail}; inspect deployment state"
        )
    return result.stdout


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def owned_worktree(value) -> bool:
    return (
        isinstance(value, str)
        and Path(value).is_absolute()
        and Path(value).resolve() == ROOT
    )


class Recovery:
    def __init__(self, args):
        self.args = args
        self.state = args.state.absolute()
        self.compose = args.compose.resolve(strict=True)
        self.prefix = [
            "docker",
            "compose",
            "--project-name",
            args.project,
            "--file",
            str(self.compose),
        ]
        os.environ["OPENLET_STATE_DIR"] = str(self.state)
        os.environ["OPENLET_E2E_STATE"] = str(self.state)
        self.configuration = json.loads(
            native([*self.prefix, "config", "--format", "json"])
        )

    def command(self, *arguments, **kwargs):
        return native([*self.prefix, *arguments], **kwargs)

    def resources(self, kind):
        args = [
            "docker",
            kind,
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={self.args.project}",
        ]
        if kind == "container":
            args.append("--all")
        return native(args).decode().split()

    def verify_owner(self):
        marker = self.state / "environment.json"
        restored = self.state / "restore.json"
        e2e_identity = json.loads(marker.read_text()) if marker.exists() else None
        if e2e_identity is not None and not isinstance(e2e_identity, dict):
            raise ValueError("invalid E2E ownership marker")
        if restored.exists():
            data = json.loads(restored.read_text())
            if not isinstance(data, dict):
                raise ValueError("invalid restore ownership marker")
            if data.get("project") != self.args.project or not owned_worktree(
                data.get("worktree")
            ):
                raise ValueError("restore ownership mismatch")
        elif e2e_identity is not None:
            if e2e_identity.get("project") != self.args.project or not owned_worktree(
                e2e_identity.get("root")
            ):
                raise ValueError("E2E ownership mismatch")
        elif self.args.project != "openlet" or json.loads(
            (self.state / "runtime.json").read_text()
        ) != {"kind": "development", "worktree": str(ROOT)}:
            raise ValueError("development ownership mismatch")
        ids = self.resources("container")
        if not ids:
            raise ValueError("no existing owned deployment")
        for item in json.loads(native(["docker", "container", "inspect", *ids])):
            labels = item["Config"]["Labels"] or {}
            if str(self.compose) not in labels.get(
                "com.docker.compose.project.config_files", ""
            ).split(","):
                raise ValueError("Compose file ownership mismatch")
            if e2e_identity is not None and (
                labels.get("openlet.e2e.run") != e2e_identity.get("run")
                or not owned_worktree(labels.get("openlet.e2e.worktree"))
            ):
                raise ValueError("E2E container ownership mismatch")

    def volume(self, service, destination):
        service_config = self.configuration["services"].get(service, {})
        for mount in service_config.get("volumes", []):
            if mount["type"] == "volume" and mount["target"] == destination:
                volume = self.configuration["volumes"][mount["source"]]["name"]
                details = json.loads(native(["docker", "volume", "inspect", volume]))[0]
                if (details.get("Labels") or {}).get(
                    "com.docker.compose.project"
                ) != self.args.project:
                    raise ValueError("volume belongs to another deployment")
                return volume
        raise ValueError("managed volume required for coordinated recovery")

    def backup(self):
        self.verify_owner()
        storage = self.configuration["services"].get("storage", {})
        if not storage.get("image", "").startswith("chrislusf/seaweedfs:"):
            raise ValueError(
                "external object recovery is not configured; coordinated backup requires managed SeaweedFS"
            )
        volumes = {
            "storage": self.volume("storage", "/data"),
            "qdrant": self.volume("qdrant", "/qdrant/storage"),
        }
        output = self.args.output.absolute()
        output.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.command("stop", "--timeout", "150", "envoy")
        self.command(
            "stop",
            "--timeout",
            "150",
            *(
                s
                for s in WRITERS
                if s != "envoy" and s in self.configuration["services"]
            ),
        )
        unfinished = (
            self.command(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-XAt",
                "--set",
                "ON_ERROR_STOP=1",
                "-U",
                "openlet_admin",
                "-d",
                "openlet_letfs",
                "-c",
                "SELECT count(*) FROM uploads WHERE state IN ('open','completing') OR (state='aborted' AND write_expires_at>now())",
            )
            .decode()
            .strip()
        )
        if unfinished != "0":
            raise ValueError(
                "unfinished storage capabilities must be drained before backup; writers remain fenced"
            )
        for database in DATABASES:
            path = output / f"{database}.dump"
            with path.open("xb") as destination:
                self.command(
                    "exec",
                    "-T",
                    "postgres",
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                    "-U",
                    "openlet_admin",
                    "-d",
                    f"openlet_{database}",
                    stdout=destination,
                )
            with path.open("rb") as source:
                self.command(
                    "exec", "-T", "postgres", "pg_restore", "--list", stdin=source
                )
        for service, volume in volumes.items():
            native(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--mount",
                    f"type=volume,source={volume},target=/data,readonly",
                    "--mount",
                    f"type=bind,source={output},target=/snapshot",
                    POSTGRES_IMAGE,
                    "tar",
                    "--create",
                    "--gzip",
                    f"--file=/snapshot/{service}.tar.gz",
                    "--directory=/data",
                    ".",
                ]
            )
        configuration = output / "configuration"
        configuration.mkdir(mode=0o700)
        if any(p.is_symlink() for p in (self.state / "secrets").iterdir()):
            raise ValueError("refusing symlinked snapshot secrets")
        shutil.copytree(self.state / "secrets", configuration / "secrets")
        for name in CONFIGURATION:
            if (self.state / name).is_symlink():
                raise ValueError("refusing symlinked configuration")
            shutil.copyfile(self.state / name, configuration / name)
        files = {
            str(p.relative_to(output)): digest(p)
            for p in output.rglob("*")
            if p.is_file()
        }
        manifest = {
            "version": 1,
            "coordinated": True,
            "source_project": self.args.project,
            "databases": list(DATABASES),
            "compose": str(self.compose),
            "files": files,
        }
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
        print(
            "Coordinated snapshot verified. Writers remain stopped; resume explicitly."
        )

    def restore(self):
        snapshot = self.args.snapshot.resolve(strict=True)
        manifest_path = snapshot / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("snapshot integrity verification failed")
        manifest = json.loads(manifest_path.read_text())
        if (
            not isinstance(manifest, dict)
            or manifest.get("version") != 1
            or manifest.get("coordinated") is not True
            or manifest.get("databases") != list(DATABASES)
        ):
            raise ValueError("unsupported/incomplete coordinated snapshot")
        if (
            manifest.get("compose") != str(self.compose)
            or manifest.get("source_project") == self.args.project
        ):
            raise ValueError(
                "restore requires the same Compose definition and a different, isolated project"
            )
        entries = list(snapshot.rglob("*"))
        if any(path.is_symlink() for path in entries):
            raise ValueError("snapshot integrity verification failed")
        files = {
            str(path.relative_to(snapshot)): digest(path)
            for path in entries
            if path.is_file() and path != manifest_path
        }
        if manifest.get("files") != files:
            raise ValueError("snapshot integrity verification failed")
        for service in ("storage", "qdrant"):
            with tarfile.open(snapshot / f"{service}.tar.gz") as archive:
                for member in archive:
                    path = PurePosixPath(member.name)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or not (member.isdir() or member.isfile())
                    ):
                        raise ValueError("unsafe archive member")
        if (
            any(self.resources(kind) for kind in ("container", "volume", "network"))
            or self.state.exists()
        ):
            raise ValueError(
                "restore requires an empty isolated target; inspect and back up before any reset"
            )
        self.state.mkdir(parents=True, mode=0o700)
        shutil.copytree(snapshot / "configuration", self.state, dirs_exist_ok=True)
        # The private parent protects host access; mounted files serve nonroot containers.
        for name in CONFIGURATION:
            (self.state / name).chmod(0o644)
        marker = self.state / "restore.json"
        identity = {
            "project": self.args.project,
            "worktree": str(ROOT),
            "status": "restoring",
        }
        marker.write_text(json.dumps(identity))
        self.command(
            "up", "--detach", "--no-deps", "--wait", "--wait-timeout", "90", "postgres"
        )
        for database in DATABASES:
            with (snapshot / f"{database}.dump").open("rb") as source:
                self.command(
                    "exec",
                    "-T",
                    "postgres",
                    "pg_restore",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-acl",
                    "--role",
                    f"openlet_{database}",
                    "-U",
                    "openlet_admin",
                    "-d",
                    f"openlet_{database}",
                    stdin=source,
                )
        self.command("create", "storage", "qdrant")
        for service, destination in (
            ("storage", "/data"),
            ("qdrant", "/qdrant/storage"),
        ):
            volume = self.volume(service, destination)
            native(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--mount",
                    f"type=volume,source={volume},target=/data",
                    "--mount",
                    f"type=bind,source={snapshot},target=/snapshot,readonly",
                    POSTGRES_IMAGE,
                    "tar",
                    "--extract",
                    "--gzip",
                    f"--file=/snapshot/{service}.tar.gz",
                    "--directory=/data",
                ]
            )
        if os.environ.get("OPENLET_E2E_RUN"):
            (self.state / "environment.json").write_text(
                json.dumps(
                    {
                        "project": self.args.project,
                        "root": str(ROOT),
                        "run": os.environ["OPENLET_E2E_RUN"],
                    }
                )
            )
        identity["status"] = "restored"
        marker.write_text(json.dumps(identity))
        print("Isolated restore verified. Application/workflow writers remain stopped.")

    def resume(self):
        self.verify_owner()
        marker = self.state / "restore.json"
        if (
            marker.exists()
            and json.loads(marker.read_text()).get("status") != "restored"
        ):
            raise ValueError("incomplete restore cannot resume")
        dependencies = [
            s
            for s in ("postgres", "storage", "qdrant", "boundary")
            if s in self.configuration["services"]
        ]
        self.command(
            "up",
            "--detach",
            "--no-deps",
            "--wait",
            "--wait-timeout",
            "90",
            *dependencies,
        )
        self.command("up", "--detach", "--no-deps", "temporal")
        self.command(
            "run",
            "--rm",
            "--no-deps",
            "--entrypoint",
            "/bin/sh",
            "temporal-init",
            "-ec",
            "for attempt in $(seq 1 60); do temporal operator cluster health >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1",
        )
        applications = [
            s
            for s in (
                "account",
                "workspace",
                "letfs",
                "processor-cpu",
                "processor-io",
                "envoy",
            )
            if s in self.configuration["services"]
        ]
        self.command(
            "up",
            "--detach",
            "--no-deps",
            "--build",
            "--wait",
            "--wait-timeout",
            "90",
            *applications,
        )
        print("Owned deployment resumed.")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "restore", "resume"))
    parser.add_argument("--compose", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", args.project):
        parser.error("invalid Compose project")
    if (
        args.action == "backup"
        and args.output is None
        or args.action == "restore"
        and args.snapshot is None
    ):
        parser.error("backup requires --output; restore requires --snapshot")
    with (Path(tempfile.gettempdir()) / f"openlet-recovery-{args.project}.lock").open(
        "a"
    ) as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            operation = Recovery(args)
            getattr(operation, args.action)()
        except (
            OSError,
            ValueError,
            RuntimeError,
            subprocess.TimeoutExpired,
            tarfile.TarError,
        ) as error:
            parser.exit(1, f"Recovery failed: {error}\n")


if __name__ == "__main__":
    main()
