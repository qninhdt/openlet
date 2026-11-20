from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openlet_api.letfs.v1.internal_pb2_grpc import LetFSInternalServiceAsyncStub


import asyncio
import base64
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import google_crc32c
import httpx
from google.protobuf.empty_pb2 import Empty
from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as pb
from openlet_sdk.config import LetFSSettings
from openlet_sdk.file_types import classify_file
from temporalio import activity
from temporalio.exceptions import ApplicationError

from .telemetry import ProcessingIdentity


@asynccontextmanager
async def heartbeats() -> AsyncGenerator[None]:
    async def send() -> None:
        while True:
            activity.heartbeat()
            await asyncio.sleep(10)

    task = asyncio.create_task(send())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def checksum(data: bytes) -> str:
    return base64.b64encode(google_crc32c.Checksum(data).digest()).decode("ascii")


def check_transfer(response: httpx.Response) -> None:
    if not response.is_success:
        raise ApplicationError(
            f"object transfer failed (HTTP {response.status_code})",
            type="ObjectTransferFailed",
        )


async def download(http: httpx.AsyncClient, url: str, target: Path, limit: int) -> None:
    size = 0
    async with http.stream("GET", url) as response:
        check_transfer(response)
        with target.open("wb") as stream:
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > limit:
                    raise ApplicationError(
                        "source exceeds blob limit", non_retryable=True
                    )
                stream.write(chunk)


async def publish(
    stub: LetFSInternalServiceAsyncStub,
    http: httpx.AsyncClient,
    identity: ProcessingIdentity,
    output: Path,
    settings: LetFSSettings,
) -> None:
    artifacts: list[internal.Artifact] = []
    specs: list[internal.ArtifactUploadSpec] = []
    blobs: dict[str, Path] = {}
    total = 0
    for path in sorted(output.rglob("*")):
        relative = path.relative_to(output).as_posix()
        if path.is_symlink():
            raise ApplicationError(
                "parser output contains a symlink", non_retryable=True
            )
        if len(artifacts) + len(specs) >= settings["processing"]["max_artifacts"]:
            raise ApplicationError("artifact count exceeds limit", non_retryable=True)
        if path.is_dir():
            artifacts.append(internal.Artifact(path=relative, directory=Empty()))
            continue

        kind, media = classify_file(path.name)
        if kind == "unsupported":
            raise ApplicationError(
                "unsupported artifact file extension", non_retryable=True
            )
        if kind == "text":
            data = path.read_bytes()
            if len(data) > settings["max_text_bytes"]:
                raise ApplicationError(
                    "artifact text exceeds limit", non_retryable=True
                )
            content = data.decode("utf-8")
            if "\0" in content:
                raise ApplicationError("artifact text contains NUL", non_retryable=True)
            total += len(data)
            artifacts.append(
                internal.Artifact(
                    path=relative,
                    text=pb.TextContent(content=content, media_type=media),
                )
            )
        else:
            data = path.read_bytes()
            if len(data) > settings["processing"]["max_artifact_blob_bytes"]:
                raise ApplicationError(
                    "artifact blob exceeds limit", non_retryable=True
                )
            specs.append(
                internal.ArtifactUploadSpec(
                    path=relative,
                    size_bytes=len(data),
                    media_type=media,
                    checksum=checksum(data),
                )
            )
            blobs[relative] = path
    if total > settings["processing"]["max_manifest_text_bytes"]:
        raise ApplicationError("artifact manifest exceeds limit", non_retryable=True)
    if specs:
        prepared = await stub.PrepareArtifactUploads(
            internal.PrepareArtifactUploadsRequest(
                **identity,
                outputs=specs,
            ),
            timeout=30,
        )
        if prepared.outcome.obsolete or prepared.outcome.stage != "pending":
            return
        for upload in prepared.uploads:
            response = await http.put(
                upload.put_url,
                headers=dict(upload.headers),
                content=blobs[upload.path].read_bytes(),
            )
            check_transfer(response)
            artifacts.append(
                internal.Artifact(path=upload.path, upload_id=upload.upload_id)
            )
    await stub.CommitParse(
        internal.CommitParseRequest(**identity, artifacts=artifacts), timeout=60
    )
