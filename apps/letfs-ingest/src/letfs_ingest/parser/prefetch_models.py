"""Install the pinned parser model assets for offline worker startup."""

import argparse
from pathlib import Path

from docling.utils.model_downloader import download_models
from huggingface_hub import snapshot_download

from letfs_ingest.parser import models


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    destination = parser.parse_args().destination
    destination.mkdir(parents=True, exist_ok=True)
    assets = (
        (models.LAYOUT_REPO, models.LAYOUT_REVISION, ["*.json", "*.safetensors"]),
        (
            models.TABLE_REPO,
            models.TABLE_REVISION,
            ["model_artifacts/tableformer/accurate/*"],
        ),
    )
    for repository, revision, patterns in assets:
        snapshot_download(
            repo_id=repository,
            revision=revision,
            local_dir=destination / repository.replace("/", "--"),
            allow_patterns=patterns,
        )
    download_models(
        destination,
        with_layout=False,
        with_tableformer=False,
        with_code_formula=False,
        with_picture_classifier=False,
        with_rapidocr=True,
        rapidocr_models=["onnxruntime:iso:en"],
    )


if __name__ == "__main__":
    main()
