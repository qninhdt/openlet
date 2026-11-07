"""Exercise the actual development graph startup with disposable Compose resources."""

import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import pytest
from configure import ROOT, configure
from test_configure import settings


@pytest.fixture
def graph(tmp_path: Path):
    configure(tmp_path, settings())
    project = f"openlet-graph-test-{uuid4().hex}"
    environment = {**os.environ, "OPENLET_STATE_DIR": str(tmp_path)}
    credentials = sorted(
        (path.read_text().strip() for path in (tmp_path / "secrets").iterdir()),
        key=len,
        reverse=True,
    )

    prefix = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--file",
        str(ROOT / "infra/compose/dev.yaml"),
    ]

    def compose(*arguments: str, expected: int = 0, timeout: int = 180) -> str:
        result = subprocess.run(
            [*prefix, *arguments],
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        diagnostic = result.stdout + result.stderr
        for credential in credentials:
            diagnostic = diagnostic.replace(credential, "[REDACTED]")
        assert result.returncode == expected, diagnostic[-6000:]
        return diagnostic

    try:
        yield compose, prefix, environment, project
    finally:
        compose("down", "--volumes", "--remove-orphans", "--timeout", "20")


def test_native_graph_startup_and_schema_admission(tmp_path: Path, graph):
    compose, _, _, _ = graph
    compose("config", "--quiet")
    compose("build", "authz-schema", timeout=600)
    compose("up", "--detach", "--wait", "--wait-timeout", "120", "spicedb")
    for arguments in [(), ("--check",), ()]:
        assert "Authorization schema verified." in compose(
            "run",
            "--rm",
            "--no-deps",
            "authz-schema",
            *arguments,
        )
    actual = compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-XAt",
        "-U",
        "openlet_admin",
        "-d",
        "postgres",
        "-c",
        "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='openlet_spicedb'",
    )
    assert actual.strip() == "openlet_spicedb"
    (tmp_path / "secrets/spicedb_key").write_text(
        "incorrect-isolated-schema-key-for-check"
    )
    assert "PermissionDenied" in compose(
        "run",
        "--rm",
        "--no-deps",
        "authz-schema",
        "--check",
        expected=1,
    )
    compose("stop", "spicedb")
    compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "--set",
        "ON_ERROR_STOP=1",
        "-U",
        "openlet_admin",
        "-d",
        "postgres",
        "-c",
        "ALTER ROLE openlet_spicedb NOLOGIN",
    )
    compose(
        "up",
        "--detach",
        "--wait",
        "--wait-timeout",
        "30",
        "--force-recreate",
        "--always-recreate-deps",
        "spicedb",
        expected=1,
    )
    assert compose("ps", "--status", "running", "--services").strip() == "postgres"


def test_canceled_graph_readiness_wait_cleans_owned_resources(tmp_path: Path, graph):
    compose, prefix, environment, project = graph
    override = tmp_path / "unready-graph.json"
    override.write_text(
        json.dumps(
            {
                "services": {
                    "spicedb": {
                        "healthcheck": {
                            "test": [
                                "CMD",
                                "/usr/local/bin/grpc_health_probe",
                                "-addr=localhost:59999",
                                "-rpc-timeout=1s",
                            ]
                        }
                    }
                }
            }
        )
    )
    process = subprocess.Popen(
        [
            *prefix,
            "--file",
            str(override),
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            "120",
            "spicedb",
        ],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            assert process.poll() is None, (
                "startup exited before cancellation injection"
            )
            if "spicedb" in compose("ps", "--status", "running", "--services").split():
                break
            time.sleep(0.1)
        else:
            pytest.fail("graph never reached the readiness wait")
        process.terminate()
        assert process.wait(timeout=15) != 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
        compose("down", "--volumes", "--remove-orphans", "--timeout", "20")
    for kind in ("container", "volume", "network"):
        result = subprocess.run(
            [
                "docker",
                kind,
                "ls",
                "--quiet",
                *(["--all"] if kind == "container" else []),
                "--filter",
                f"label=com.docker.compose.project={project}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        assert not result.stdout.strip(), f"owned {kind} survived cancellation cleanup"
