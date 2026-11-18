from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openlet_api.letfs.v1.internal_pb2_grpc import LetFSInternalServiceAsyncStub


import asyncio
import math
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from datalab_sdk import AsyncDatalabClient, ConvertOptions, DatalabError, FileResult  # pyright: ignore[reportMissingTypeStubs]
from openlet_api.letfs.v1 import internal_pb2 as pb
from openlet_sdk.config import Config, DatalabSettings
from temporalio import activity
from temporalio.exceptions import ApplicationError

from .artifacts import download, heartbeats, publish
from .convert import MEDIA_SUFFIXES, REMOTE_MEDIA, InvalidDocument, preflight
from .datalab import export
from .telemetry import ProcessingIdentity, stage


async def run_child(arguments: list[str], timeout: float) -> int:
    env = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TMPDIR", "OPENLET_CONFIG")
        if key in os.environ
    }
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        *arguments,
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
    )
    try:
        return await asyncio.wait_for(child.wait(), timeout=timeout)
    finally:
        if child.returncode is None:
            child.terminate()
            try:
                await asyncio.wait_for(child.wait(), timeout=5)
            except TimeoutError:
                child.kill()
                await child.wait()


class Parser:
    def __init__(
        self,
        stub: LetFSInternalServiceAsyncStub,
        http: httpx.AsyncClient,
        config: Config,
        datalab: AsyncDatalabClient | None,
    ) -> None:
        self.stub, self.http, self.config = stub, http, config
        self.settings = config["services"]["letfs"]
        parser = config["services"]["letfs_ingest"]["cpu"]
        self.office = asyncio.Semaphore(parser.get("office_concurrency", 2))
        defaults: DatalabSettings = {
            "concurrency": 2,
            "result_concurrency": 2,
            "requests_per_minute": 10,
            "max_response_bytes": 96 * 1024 * 1024,
        }
        settings = parser.get("datalab", defaults)
        if (
            self.office.locked()
            or min(
                settings["concurrency"],
                settings["result_concurrency"],
                settings["requests_per_minute"],
                settings["max_response_bytes"],
            )
            < 1
        ):
            raise ValueError("invalid parser concurrency or Datalab response limits")
        self.datalab = datalab
        self.remote_slots = asyncio.Semaphore(settings["concurrency"])
        self.result_slots = asyncio.Semaphore(settings["result_concurrency"])
        self.poll_interval = math.ceil(
            60 * settings["concurrency"] / settings["requests_per_minute"]
        )
        self.max_result_bytes = settings["max_response_bytes"]

    @activity.defn(name="ParseBlob")
    async def run(self, request: ProcessingIdentity) -> None:
        async with heartbeats():
            identity: ProcessingIdentity = {
                "file_id": request["file_id"],
                "version": request["version"],
            }
            query = pb.ProcessingRequest(**identity)
            source = await self.stub.GetProcessingInput(query, timeout=30)
            if source.outcome.obsolete or source.outcome.stage != "pending":
                return
            remote = source.media_type in REMOTE_MEDIA
            slots = self.remote_slots if remote else self.office
            queued = slots.locked()
            with TemporaryDirectory(prefix="openlet-parse-") as temporary:
                directory = Path(temporary)
                output = directory / "output"
                output.mkdir()
                try:
                    async with slots:
                        if queued:
                            source = await self.stub.GetProcessingInput(
                                query, timeout=30
                            )
                            if (
                                source.outcome.obsolete
                                or source.outcome.stage != "pending"
                            ):
                                return
                        name = directory / ("input" + MEDIA_SUFFIXES[source.media_type])
                        with stage("parse", identity):
                            await (self.remote if remote else self.local)(
                                source, name, output
                            )
                except ValueError as error:
                    raise ApplicationError(
                        str(error),
                        type="InvalidDocument",
                        non_retryable=True,
                    ) from None
                with stage("export", identity):
                    await publish(self.stub, self.http, identity, output, self.settings)

    async def remote(
        self,
        source: pb.ProcessingInput,
        name: Path,
        output: Path,
    ) -> None:
        if self.datalab is None:
            raise InvalidDocument("DATALAB_API_KEY is required for PDF and DOCX ingest")
        direct = self.config["dependencies"]["s3"].get("processing_download_endpoint")
        if not direct:
            await download(
                self.http,
                source.download_url,
                name,
                self.settings["max_blob_bytes"],
            )
            await asyncio.to_thread(preflight, name, source.media_type, self.config)
        limit = self.config["services"]["letfs_ingest"]["cpu"]["limits"]["max_pages"]
        try:
            result = await self.datalab.convert(
                file_path=None if direct else name,
                file_url=source.download_url if direct else None,
                options=ConvertOptions(
                    output_format="markdown",
                    mode="balanced",
                    max_pages=limit + 1,
                    disable_image_captions=True,
                ),
                stream_response_to=name.parent / "datalab-response.json",
                poll_interval=self.poll_interval,
            )
        except DatalabError as error:
            raise InvalidDocument(
                f"Datalab conversion failed ({type(error).__name__})"
            ) from None
        if not isinstance(result, FileResult) or not result.success:
            raise InvalidDocument("Datalab conversion failed")
        if result.output_path.stat().st_size > self.max_result_bytes:
            raise InvalidDocument("Datalab response exceeds byte limit")
        async with self.result_slots:
            task = asyncio.create_task(
                asyncio.to_thread(
                    export,
                    result.output_path,
                    result.success,
                    output,
                    self.config,
                )
            )
            try:
                await asyncio.shield(task)
            finally:
                if not task.done():
                    await asyncio.gather(task, return_exceptions=True)

    async def local(self, source: pb.ProcessingInput, name: Path, output: Path) -> None:
        await download(
            self.http,
            source.download_url,
            name,
            self.settings["max_blob_bytes"],
        )
        code = await run_child(
            [
                "letfs_ingest.convert",
                str(name),
                str(output),
                source.media_type,
                f"--source-name={source.source_name}",
            ],
            self.settings["processing"]["parse_timeout_seconds"],
        )
        if code:
            raise ApplicationError(
                "document conversion failed",
                type="ConversionFailed",
                non_retryable=code == os.EX_DATAERR,
            )
