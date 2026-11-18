from __future__ import annotations

import base64
import hashlib
import io
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PIL import Image

from .convert import InvalidDocument, validate_output
from .layout import write_markdown
from .naming import rewrite_artifact_links
from .tables import externalize_tables

if TYPE_CHECKING:
    from openlet_sdk.config import Config

IMAGE_TYPES = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}


def response_object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise InvalidDocument("invalid Datalab response")
    return cast("dict[str, object]", value)


def export(source: Path, success: bool, output: Path, config: Config) -> None:
    with source.open("rb") as stream:
        result = response_object(json.load(stream))
    result.setdefault("success", success)
    parser = config["services"]["letfs_ingest"]["cpu"]
    limits = parser["limits"]
    storage = config["services"]["letfs"]
    count, body = result.get("page_count"), result.get("markdown")
    if (
        result.get("success") is not True
        or type(count) is not int
        or not 0 < count <= limits["max_pages"]
        or not isinstance(body, str)
        or not body.strip()
        or response_object(result.get("metadata") or {}).get("failed_pages")
    ):
        raise InvalidDocument(
            "Datalab returned incomplete content or exceeded the page limit"
        )

    paths = {"README.md": "README.md"}
    names: dict[bytes, str] = {}
    images = response_object(result.get("images") or {})
    total = 0
    for key, encoded in images.items():
        if not re.fullmatch(r"[\w.-]+", key) or not re.search(
            r'(?:\]\(<?|\bsrc=["\'])' + re.escape(key) + r'(?=[)>\s"\'])', body
        ):
            continue
        limit = storage["processing"]["max_artifact_blob_bytes"]
        if not isinstance(encoded, str) or len(encoded) > 4 * ((limit + 2) // 3):
            raise InvalidDocument("Datalab image exceeds byte limit")
        data = base64.b64decode(encoded, validate=True)
        digest = hashlib.sha256(data).digest()
        if digest not in names:
            total += len(data)
            if total > limits["max_output_bytes"] or len(data) > limit:
                raise InvalidDocument("Datalab images exceed byte budget")
            with Image.open(io.BytesIO(data)) as image:
                suffix = IMAGE_TYPES.get(image.format or "")
                if not suffix or image.width * image.height > limits["max_page_pixels"]:
                    raise InvalidDocument("unsupported or oversized Datalab image")
                image.verify()
            if len(names) >= storage["processing"]["max_artifacts"]:
                raise InvalidDocument("Datalab images exceed artifact count")
            name = f"image-{len(names) + 1}.{suffix}"
            (output / name).write_bytes(data)
            names[digest] = name
        paths[key] = names[digest]
    body = rewrite_artifact_links(body, "README.md", paths)
    max_text = storage["max_text_bytes"]
    body = externalize_tables(body, output, parser["split_tokens"], max_text)
    write_markdown(body, output, parser["split_tokens"], max_text)
    validate_output(output, config)
