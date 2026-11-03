import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.integration
def test_independent_wheel_and_app_dependency(tmp_path):
    wheels = tmp_path / "wheels"
    for package in ["openlet-python", "letfs-ingest"]:
        subprocess.run(
            ["uv", "build", "--package", package, "--wheel", "--out-dir", str(wheels)],
            cwd=ROOT,
            check=True,
        )
    shared = next(wheels.glob("openlet_python-*.whl"))
    app = next(wheels.glob("letfs_ingest-*.whl"))
    with zipfile.ZipFile(shared) as archive:
        assert "openlet_api/letfs/v1/letfs_pb2_grpc.py" in archive.namelist()
        assert not any(p.startswith("letfs_ingest/") for p in archive.namelist())
    with zipfile.ZipFile(app) as archive:
        assert not any(p.startswith("openlet_api/") for p in archive.namelist())
        metadata = archive.read(
            next(p for p in archive.namelist() if p.endswith("/METADATA"))
        )
        assert b"Requires-Dist: openlet-python" in metadata
    environment = tmp_path / "environment"
    subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(environment)], check=True
    )
    python = environment / "bin/python"
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), str(shared)], check=True
    )
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), "--no-deps", str(app)],
        check=True,
    )
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "import importlib.metadata as m; "
            "import openlet_api, letfs_ingest; "
            "from openlet_api.letfs.v1.letfs_pb2_grpc import "
            "FilesystemServiceStub, FilesystemServiceServicer; "
            "assert m.packages_distributions()['openlet_api'] == ['openlet-python']",
        ],
        cwd=tmp_path,
        env=env,
        check=True,
    )
