import argparse
import os
from pathlib import Path

from openlet_sdk.config import Config, load


def prepare(config: Config) -> None:
    from docling.utils.model_downloader import download_models

    destination = Path(config["services"]["letfs_ingest"]["cpu"]["docling_models_path"])
    destination.mkdir(parents=True, exist_ok=True)
    download_models(
        destination, with_code_formula=False, with_picture_classifier=False,
        rapidocr_models=["onnxruntime:iso:en"],
    )


def check(config: Config) -> None:
    from docling.datamodel.base_models import InputFormat

    from .convert import converter

    os.environ["HF_HUB_OFFLINE"] = "1"
    converter(config).initialize_pipeline(InputFormat.PDF)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare or verify Docling assets before worker startup.")
    parser.add_argument("action", choices=("prepare", "check"))
    action = parser.parse_args().action
    (prepare if action == "prepare" else check)(load())
