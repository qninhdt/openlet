"""Download the dataset revision used by the seed harness."""

import fcntl
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from .seed import read_seeds

REPO_ID = "qninhdt/openlet-datasets"
REVISION = "main"
MARKER = ".openlet-dataset-revision"


def download_dataset(directory: Path) -> Path:
    stamp = f"{REPO_ID}@{REVISION}\n"
    marker = directory / MARKER
    scratch = directory.parent / ".local"
    scratch.mkdir(exist_ok=True)
    with (scratch / "dataset.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if marker.is_file() and marker.read_text() == stamp:
            return directory
        if directory.exists() and not marker.is_file() and any(directory.iterdir()):
            raise ValueError(
                f"{directory} contains local data; pass --seeds {directory}"
            )
        with TemporaryDirectory(dir=scratch, prefix="dataset-") as temporary:
            staging = Path(temporary) / "snapshot"
            subprocess.run(
                [
                    "hf",
                    "download",
                    REPO_ID,
                    "--repo-type",
                    "dataset",
                    "--revision",
                    REVISION,
                    "--local-dir",
                    str(staging),
                    "--quiet",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            read_seeds(staging, [])
            (staging / MARKER).write_text(stamp)
            previous = Path(temporary) / "previous"
            if directory.exists():
                directory.rename(previous)
            try:
                staging.rename(directory)
            except BaseException:
                if previous.exists():
                    previous.rename(directory)
                raise
    return directory
