"""Temporal ParseBlob activity orchestrating local conversion and Datalab export."""

from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import TYPE_CHECKING
from uuid import uuid4

from datalab_sdk import (  # pyright: ignore[reportMissingTypeStubs]
    ConvertOptions,
    DatalabAPIError,
    DatalabAuthenticationError,
    DatalabError,
    DatalabFileError,
    DatalabNotFoundError,
    DatalabPaymentRequiredError,
    DatalabRateLimitError,
    DatalabServerError,
    DatalabTimeoutError,
    DatalabValidationError,
)
from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as letfs
from temporalio import activity
from temporalio.exceptions import ApplicationError

from letfs_ingest.convert import (
    DOCX_MEDIA,
    PDF_MEDIA,
    PPTX_MEDIA,
    XLSX_MEDIA,
    InvalidDocumentError,
    preflight,
)
from letfs_ingest.datalab import export
from letfs_ingest.telemetry import (
    ProcessingIdentity,
    heartbeats,
    retry_transient,
    stage,
)

if TYPE_CHECKING:
    from openlet_sdk.config import Config

    from letfs_ingest.protocols import (
        BlobStore,
        DatalabClient,
        DatalabResult,
        LetFSParseStub,
    )

REMOTE_MEDIA = frozenset({PDF_MEDIA, DOCX_MEDIA})
MEDIA_SUFFIXES = MappingProxyType(
    {
        PDF_MEDIA: ".pdf",
        DOCX_MEDIA: ".docx",
        PPTX_MEDIA: ".pptx",
        XLSX_MEDIA: ".xlsx",
    }
)
MEDIA_TYPES = MappingProxyType(
    {
        ".md": "text/markdown",
        ".csv": "text/csv",
        ".html": "text/html",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
)

_NON_RETRYABLE_DATALAB_ERRORS = (
    DatalabAuthenticationError,
    DatalabPaymentRequiredError,
    DatalabNotFoundError,
    DatalabFileError,
    DatalabValidationError,
)


def _is_transient_datalab_error(exc: BaseException) -> bool:
    if isinstance(exc, _NON_RETRYABLE_DATALAB_ERRORS):
        return False
    if isinstance(
        exc,
        DatalabTimeoutError | DatalabServerError | DatalabRateLimitError | OSError,
    ):
        return True
    if isinstance(exc, DatalabAPIError):
        return (
            exc.status_code is None or exc.status_code == 429 or exc.status_code >= 500
        )
    return False


async def convert_with_retry(
    datalab: DatalabClient,
    *,
    file_url: str | None,
    file_path: Path | None,
    options: ConvertOptions,
    stream_response_to: Path,
    attempts: int = 3,
) -> DatalabResult:
    """Retry transient network/5xx Datalab failures with exponential backoff + jitter."""

    async def attempt() -> DatalabResult:
        await asyncio.to_thread(stream_response_to.unlink, missing_ok=True)
        return await datalab.convert(
            file_url=file_url,
            file_path=file_path,
            options=options,
            stream_response_to=stream_response_to,
        )

    return await retry_transient(
        attempt,
        should_retry=_is_transient_datalab_error,
        attempts=attempts,
        sleep=asyncio.sleep,
    )


async def run_child(arguments: list[str]) -> int:
    """Execute a Python module subprocess and return exit code 0 on success."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await process.communicate()
    finally:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
    if process.returncode:
        message = (
            stderr.decode("utf-8", "replace").strip() or "subprocess conversion failed"
        )
        raise ApplicationError(message, non_retryable=True)
    return process.returncode or 0


def _export_datalab_response(
    resp_path: Path,
    out_dir: Path,
    config: Config,
    *,
    max_response_bytes: int,
    success: bool,
) -> None:
    if resp_path.stat().st_size > max_response_bytes:
        raise InvalidDocumentError("Datalab response exceeds max_response_bytes")
    export(resp_path, out_dir, config, success=success)


def _collect_local_artifacts(
    out_dir: Path,
) -> tuple[bool, list[tuple[str, str, str, str | bytes]]]:
    files = sorted(p for p in out_dir.rglob("*") if p.is_file())
    rel_paths = [p.relative_to(out_dir).as_posix() for p in files]
    has_parts = any(rel.endswith(".md") and rel != "README.md" for rel in rel_paths)
    collected: list[tuple[str, str, str, str | bytes]] = []
    for file, rel in zip(files, rel_paths, strict=True):
        ext = file.suffix.lower()
        media = (
            MEDIA_TYPES.get(ext)
            or mimetypes.guess_type(file.name)[0]
            or "application/octet-stream"
        )
        payload: str | bytes = (
            file.read_text(encoding="utf-8")
            if ext in {".md", ".csv", ".html"}
            else file.read_bytes()
        )
        collected.append((rel, ext, media, payload))
    return has_parts, collected


class Parser:
    """Temporal activity host for parsing documents into LetFS artifacts."""

    def __init__(
        self,
        stub: LetFSParseStub,
        s3: BlobStore,
        config: Config,
        datalab: DatalabClient | None,
    ) -> None:
        self.stub = stub
        self.s3 = s3
        self.config = config
        self.datalab = datalab
        parser = config["services"]["letfs_ingest"]["cpu"]
        dl = parser.get("datalab")
        self.max_response_bytes = (
            int(dl["max_response_bytes"]) if dl is not None else 96 * 1024 * 1024
        )
        self.parse_timeout = float(
            config["services"]["letfs"]["processing"]["parse_timeout_seconds"]
        )
        self.max_blob_bytes = int(config["services"]["letfs"]["max_blob_bytes"])

    @activity.defn(name="ParseBlob")
    async def run(self, blob_id: str) -> None:
        """Download, preflight, convert, and persist parsed artifacts for ``blob_id``."""
        identity: ProcessingIdentity = {"blob_id": blob_id}
        async with heartbeats():
            with stage("parse", identity):
                info = await self.stub.GetBlobArtifacts(
                    internal.BlobRequest(blob_id=blob_id)
                )
                if info.outcome.obsolete or info.outcome.stage in {"enriched", "ready"}:
                    return
                suffix = MEDIA_SUFFIXES.get(info.media_type)
                if suffix is None:
                    raise ApplicationError(
                        f"unsupported document media type: {info.media_type}",
                        non_retryable=True,
                    )

                with TemporaryDirectory() as tmp:
                    workdir = Path(tmp)
                    src_file = workdir / f"input{suffix}"
                    out_dir = workdir / "out"
                    await asyncio.to_thread(out_dir.mkdir)
                    await self.s3.download_to_file(
                        info.object_key, src_file, self.max_blob_bytes
                    )

                    if info.media_type in REMOTE_MEDIA:
                        if self.datalab is None:
                            raise ApplicationError(
                                "Datalab client is not configured", non_retryable=True
                            )
                        try:
                            await asyncio.to_thread(
                                preflight, src_file, info.media_type, self.config
                            )
                            resp_path = workdir / "datalab-response.json"
                            result = await convert_with_retry(
                                self.datalab,
                                file_url=info.source_download_url or None,
                                file_path=None
                                if info.source_download_url
                                else src_file,
                                options=ConvertOptions(
                                    output_format="markdown",
                                    max_pages=self.config["services"]["letfs_ingest"][
                                        "cpu"
                                    ]["limits"]["max_pages"],
                                    paginate=False,
                                ),
                                stream_response_to=resp_path,
                            )
                            await asyncio.to_thread(
                                _export_datalab_response,
                                resp_path,
                                out_dir,
                                self.config,
                                max_response_bytes=self.max_response_bytes,
                                success=bool(result.success),
                            )
                        except (InvalidDocumentError, DatalabError) as exc:
                            raise ApplicationError(
                                str(exc), non_retryable=True
                            ) from exc
                    elif info.media_type in {PPTX_MEDIA, XLSX_MEDIA}:
                        async with asyncio.timeout(self.parse_timeout):
                            await run_child(
                                [
                                    "-m",
                                    "letfs_ingest.convert",
                                    str(src_file),
                                    info.media_type,
                                    str(out_dir),
                                ]
                            )

                    artifacts = await self._build_artifacts(
                        info.workspace_id, blob_id, out_dir
                    )
                    await self.stub.SaveParsedArtifacts(
                        internal.SaveParsedArtifactsRequest(
                            blob_id=blob_id, artifacts=artifacts
                        )
                    )

    async def _build_artifacts(
        self, workspace_id: str, blob_id: str, out_dir: Path
    ) -> list[internal.ParsedArtifactInput]:
        has_parts, collected = await asyncio.to_thread(
            _collect_local_artifacts, out_dir
        )
        items: list[internal.ParsedArtifactInput] = []
        for rel, ext, media, payload in collected:
            if isinstance(payload, str):
                indexable = (rel != "README.md") if has_parts else True
                items.append(
                    internal.ParsedArtifactInput(
                        path=rel,
                        kind=letfs.NODE_KIND_FILE,
                        media_type=media,
                        size_bytes=len(payload.encode("utf-8")),
                        text_content=payload,
                        indexable=indexable,
                    )
                )
            else:
                key = f"workspaces/{workspace_id}/blobs/{blob_id}/artifacts/{uuid4()}{ext}"
                digest = await self.s3.put_bytes(key, payload, media)
                items.append(
                    internal.ParsedArtifactInput(
                        path=rel,
                        kind=letfs.NODE_KIND_FILE,
                        media_type=media,
                        size_bytes=len(payload),
                        checksum=digest,
                        object_key=key,
                        indexable=True,
                    )
                )
        return items
