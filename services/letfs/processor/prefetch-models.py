import sys
from pathlib import Path

from docling.utils.model_downloader import download_models
from huggingface_hub import snapshot_download

from openlet_processor.models import (
    LAYOUT_REPO,
    LAYOUT_REVISION,
    TABLE_REPO,
    TABLE_REVISION,
)

output = Path(sys.argv[1])
for repo, revision, patterns in [
    (LAYOUT_REPO, LAYOUT_REVISION, ["*.json", "*.safetensors"]),
    (TABLE_REPO, TABLE_REVISION, ["model_artifacts/tableformer/accurate/*"]),
]:
    snapshot_download(
        repo,
        revision=revision,
        local_dir=output / repo.replace("/", "--"),
        allow_patterns=patterns,
    )
download_models(
    output,
    with_layout=False,
    with_tableformer=False,
    with_code_formula=False,
    with_picture_classifier=False,
    with_rapidocr=True,
    rapidocr_models=["onnxruntime:iso:en"],
)
