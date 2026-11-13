from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openlet_api.letfs.v1.internal_pb2_grpc import LetFSInternalServiceAsyncStub


import asyncio
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
from openlet_api.letfs.v1 import internal_pb2 as pb
from openlet_sdk.config import LetFSSettings
from temporalio import activity
from temporalio.exceptions import ApplicationError

from .artifacts import download, heartbeats, publish
from .convert import MEDIA_SUFFIXES
from .telemetry import ProcessingIdentity, stage


async def run_child(arguments: list[str], timeout: float) -> int:
    env = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TMPDIR", "OPENLET_CONFIG")
        if key in os.environ
    }
    env["HF_HUB_OFFLINE"] = "1"
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
        settings: LetFSSettings,
    ) -> None:
        self.stub, self.http, self.settings = stub, http, settings

    @activity.defn(name="ParseBlob")
    async def run(self, request: ProcessingIdentity) -> None:
        async with heartbeats():
            identity: ProcessingIdentity = {
                "file_id": request["file_id"],
                "version": request["version"],
            }
            source = await self.stub.GetProcessingInput(
                pb.ProcessingRequest(**identity), timeout=30
            )
            if source.outcome.obsolete or source.outcome.stage != "pending":
                return
            with TemporaryDirectory(prefix="openlet-parse-") as temporary:
                directory = Path(temporary)
                name = directory / ("input" + MEDIA_SUFFIXES[source.media_type])
                output = directory / "output"
                output.mkdir()
                await download(
                    self.http,
                    source.download_url,
                    name,
                    self.settings["max_blob_bytes"],
                )
                with stage("parse", identity):
                    code = await run_child(
                        [
                            "letfs_ingest.convert",
                            str(name),
                            str(output),
                            source.media_type,
                        ],
                        self.settings["processing"]["parse_timeout_seconds"],
                    )
                    if code:
                        raise ApplicationError(
                            "document conversion failed",
                            type="ConversionFailed",
                            non_retryable=code == os.EX_DATAERR,
                        )
                with stage("export", identity):
                    await publish(self.stub, self.http, identity, output, self.settings)
