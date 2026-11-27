from __future__ import annotations

import base64
import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .convert import InvalidDocument, page_limit, validate_output
from .filters import ImageArtifactWriter, ignored_repeated_digests, image_digest
from .layout import write_markdown
from .tables import externalize_tables

if TYPE_CHECKING:
    from openlet_sdk.config import Config


class _DatalabBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    block_type: str | None = None
    images: dict[str, object] | None = None


class _DatalabChunks(BaseModel):
    model_config = ConfigDict(extra="ignore")

    blocks: list[_DatalabBlock] = Field(default_factory=list[_DatalabBlock])


class _DatalabMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    failed_pages: object = None


class _DatalabPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    success: bool | None = None
    page_count: int | None = None
    markdown: str | None = None
    metadata: _DatalabMetadata | None = None
    chunks: _DatalabChunks | None = None
    images: dict[str, object] | None = None


def _block_types(payload: _DatalabPayload) -> dict[str, str]:
    types: dict[str, str] = {}
    if payload.chunks is None:
        return types
    for block in payload.chunks.blocks:
        if block.block_type is None or block.images is None:
            continue
        for key in block.images:
            types[key] = block.block_type
    return types


def _strip_dropped_image(body: str, key: str, dropped_alts: set[str]) -> str:
    for match in re.finditer(r"!\[([^\]]*)\]\(<?" + re.escape(key) + r">?\)", body):
        alt = match.group(1).strip()
        if len(alt) >= 8:
            dropped_alts.add(alt)
    body = re.sub(
        r"!\[[^\]]*\]\(<?" + re.escape(key) + r">?\)",
        "",
        body,
    )
    return re.sub(
        r"""<img\b[^>]*\bsrc=["']<?""" + re.escape(key) + r""">?["'][^>]*>""",
        "",
        body,
        flags=re.I,
    )


def _strip_echoed_captions(body: str, dropped_alts: set[str]) -> str:
    """Remove redundant paragraphs that verbatim repeat an adjacent image alt caption."""
    paras = re.split(r"\n{2,}", body)
    out: list[str] = []
    recent_alts: dict[str, int] = {}
    img_only = re.compile(r"^!\[([^\]]*)\]\([^)]+\)$")
    for para in paras:
        stripped = para.strip()
        if not stripped:
            continue
        if stripped in dropped_alts:
            continue
        m = img_only.match(stripped)
        if m:
            alt = m.group(1).strip()
            recent_alts = {alt: 2} if len(alt) >= 8 else {}
            out.append(para)
            continue
        if stripped in recent_alts:
            recent_alts.pop(stripped)
            continue
        recent_alts = {k: ttl - 1 for k, ttl in recent_alts.items() if ttl > 1}
        out.append(para)
    return "\n\n".join(out) + ("\n" if body.endswith("\n") else "")


def _rewrite_image_links(body: str, renames: dict[str, str]) -> str:
    for old_key, new_path in renames.items():
        body = re.sub(
            r"(\]\(<?)" + re.escape(old_key) + r"(?=[)>\s])",
            rf"\g<1>{new_path}",
            body,
        )
        body = re.sub(
            r'(\bsrc=["\'])' + re.escape(old_key) + r'(?=["\'])',
            rf"\g<1>{new_path}",
            body,
            flags=re.I,
        )
    return body


def export(source: Path, success: bool, output: Path, config: Config) -> None:
    try:
        payload = _DatalabPayload.model_validate_json(source.read_bytes())
    except ValidationError as exc:
        raise InvalidDocument(f"Datalab returned invalid JSON payload: {exc}") from exc

    effective_success = success if payload.success is None else payload.success
    parser = config["services"]["letfs_ingest"]["cpu"]
    limits = parser["limits"]
    storage = config["services"]["letfs"]
    count = payload.page_count
    body = payload.markdown
    limit = page_limit(config)
    if count is not None and count > limit:
        raise InvalidDocument(f"Document exceeds the {limit}-page limit")
    if (
        effective_success is not True
        or count is None
        or count <= 0
        or body is None
        or not body.strip()
        or (payload.metadata is not None and payload.metadata.failed_pages)
    ):
        raise InvalidDocument("Datalab returned incomplete content")

    block_map = _block_types(payload)
    images = payload.images or {}
    max_blob = storage["processing"]["max_artifact_blob_bytes"]
    max_artifacts = storage["processing"]["max_artifacts"]

    decoded_by_key: dict[str, bytes] = {}
    digest_counts: Counter[bytes] = Counter()
    for key, encoded in images.items():
        if not re.fullmatch(r"[\w.-]+", key):
            continue
        occurrences = len(
            re.findall(
                r'(?:\]\(<?|\bsrc=["\'])' + re.escape(key) + r'(?=[)>\s"\'])', body
            )
        )
        if not occurrences:
            continue
        if not isinstance(encoded, str) or len(encoded) > 4 * ((max_blob + 2) // 3):
            raise InvalidDocument("Datalab image exceeds byte limit")
        raw_bytes = base64.b64decode(encoded, validate=True)
        decoded_by_key[key] = raw_bytes
        digest_counts[image_digest(raw_bytes)] += occurrences

    writer = ImageArtifactWriter(
        output,
        max_blob=max_blob,
        max_output=limits["max_output_bytes"],
        max_artifacts=max_artifacts,
        ignored_digests=ignored_repeated_digests(digest_counts),
    )
    renames: dict[str, str] = {}
    dropped_alts: set[str] = set()

    for key, raw_bytes in decoded_by_key.items():
        try:
            keep, rel_path = writer.save(raw_bytes, block_type=block_map.get(key))
        except ValueError as exc:
            raise InvalidDocument(f"Datalab {exc}") from exc
        if not keep:
            body = _strip_dropped_image(body, key, dropped_alts)
        elif rel_path is not None:
            renames[key] = rel_path

    if renames:
        body = _rewrite_image_links(body, renames)
    body = _strip_echoed_captions(body, dropped_alts)
    body = re.sub(
        r"^<!-- BEGIN IMAGE CAPTION -->[ \t]*\n.*?^<!-- END IMAGE CAPTION -->[ \t]*(?:\n|$)",
        "",
        body,
        flags=re.M | re.S,
    )
    # Compact oversized GFM separator rulers and padded table-cell spaces so tables stay concise.
    body = re.sub(
        r"^(\|(?:[ \t]*:?-{3,}:?[ \t]*\|)+)[ \t]*$",
        lambda m: re.sub(r"-{4,}", "---", m.group(1)),
        body,
        flags=re.M,
    )
    body = re.sub(
        r"^\|.*\|[ \t]*$",
        lambda m: (
            "| "
            + " | ".join(
                cell.strip() for cell in m.group(0).strip().strip("|").split("|")
            )
            + " |"
        ),
        body,
        flags=re.M,
    )
    max_text = storage["max_text_bytes"]
    body = externalize_tables(body, output, parser["split_tokens"], max_text)
    write_markdown(body, output, parser["split_tokens"], max_text)
    validate_output(output, config)
