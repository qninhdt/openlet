import asyncio
import base64
import contextlib
import hashlib
import logging
import os
import re
import signal
import sys
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from openlet_processor.convert_child import (
    MAX_INPUT_BYTES,
    MAX_SCRATCH_BYTES,
    ResourceLimit,
    check_outputs,
)

LOG = logging.getLogger(__name__)


async def conversion_diagnostic(stream):
    tail = b""
    while chunk := await stream.read(4096):
        tail = (tail + chunk)[-8192:]
    # Dependency stderr can contain document text; retain only our typed receipt.
    for line in reversed(tail.decode("utf-8", errors="replace").splitlines()):
        if re.fullmatch(
            r"OPENLET_CONVERSION_ERROR exit=[234] exception=\w{1,80} "
            r"cause=\w{1,80} peak_rss_kib=\d{1,20}",
            line,
        ):
            return line
    return "no converter diagnostic"


async def supervise(source, output, kind, models, max_outputs, max_bytes):
    environment = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "HOME": str(output.parent),
        "USER": "openlet",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "openlet_processor.convert_child",
        str(source),
        str(output),
        kind,
        str(models),
        str(max_outputs),
        str(max_bytes),
        env=environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )
    diagnostic = asyncio.create_task(conversion_diagnostic(process.stderr))
    waiter = asyncio.create_task(process.wait())
    try:
        async with asyncio.timeout(660):
            while process.returncode is None:
                try:
                    await asyncio.wait_for(asyncio.shield(waiter), 1)
                except TimeoutError:
                    check_outputs(
                        output, max_outputs, min(max_bytes, MAX_SCRATCH_BYTES)
                    )
            summary = await diagnostic
        if process.returncode != 0:
            LOG.warning(
                "converter exited with status %s: %s", process.returncode, summary
            )
            if process.returncode in (3, -9, -24, -25):
                code = "RESOURCE_LIMIT"
            elif process.returncode == 2:
                code = "DOCUMENT_INVALID"
            else:
                code = "PROCESSING_FAILED"
            raise ApplicationError(
                "document conversion failed", type=code, non_retryable=True
            )
    finally:
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(asyncio.shield(waiter), 5)
            except TimeoutError:
                os.killpg(process.pid, signal.SIGKILL)
                await waiter
        diagnostic.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await diagnostic


async def heartbeat():
    while True:
        activity.heartbeat()
        await asyncio.sleep(5)


class Processor:
    def __init__(self, base_url: str, token: str, models: Path):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.models = models

    @activity.defn(name="process_file")
    async def process_file(self, operation_id: str) -> str:
        operation_id = str(UUID(operation_id))
        attempt_id = str(uuid4())
        generation = activity.info().attempt
        path = f"/internal/v1/processing/{operation_id}/{generation}/{attempt_id}"
        pulse = asyncio.create_task(heartbeat())
        try:
            async with (
                httpx.AsyncClient(
                    base_url=self.base_url,
                    headers={"authorization": f"Bearer {self.token}"},
                    timeout=30,
                    follow_redirects=False,
                ) as api,
                httpx.AsyncClient(timeout=120, follow_redirects=False) as storage,
            ):
                try:
                    async with asyncio.timeout(1700):
                        await self.process(api, storage, path)
                except asyncio.CancelledError:
                    details = activity.cancellation_details()
                    if details and details.cancel_requested:
                        await self.abort(api, path, "PROCESSING_CANCELLED")
                    raise
                except ResourceLimit:
                    await self.abort(api, path, "RESOURCE_LIMIT")
                    raise ApplicationError(
                        "processing resource limit",
                        type="RESOURCE_LIMIT",
                        non_retryable=True,
                    ) from None
                except ApplicationError as error:
                    if error.non_retryable:
                        code = (
                            error.type
                            if error.type
                            in {
                                "RESOURCE_LIMIT",
                                "QUOTA_EXCEEDED",
                                "DOCUMENT_INVALID",
                            }
                            else "PROCESSING_FAILED"
                        )
                        await self.abort(api, path, code)
                    raise
                except Exception:
                    raise ApplicationError(
                        "processing dependency failed",
                        type="DEPENDENCY_UNAVAILABLE",
                    ) from None
            return operation_id
        finally:
            pulse.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pulse

    async def request(self, api, path, body):
        for attempt in range(3):
            try:
                response = await api.post(path, json=body)
            except httpx.TransportError:
                response = None
            if response is not None and response.is_success:
                return response.json()
            if (
                response is not None
                and response.status_code < 500
                and response.status_code != 429
            ):
                data = response.json()
                code = data.get("error", {}).get("code", "PROCESSING_FAILED")
                raise ApplicationError(
                    "processing request refused",
                    type=code,
                    non_retryable=True,
                )
            if attempt < 2:
                await asyncio.sleep(0.25 * (attempt + 1))
        raise ApplicationError("letfs unavailable", type="DEPENDENCY_UNAVAILABLE")

    async def abort(self, api, path, code):
        try:
            async with asyncio.timeout(5):
                await self.request(api, path + "/abort", {"code": code})
        except (Exception, asyncio.CancelledError):
            LOG.warning("attempt cleanup deferred to letfs maintenance")

    async def process(self, api, storage, path):
        prepared = await self.request(api, path + "/prepare", {})
        if prepared["state"] == "succeeded":
            return
        size = int(prepared["size_bytes"])
        if size > MAX_INPUT_BYTES:
            raise ResourceLimit("input bytes")
        kind = prepared["format"]
        if kind not in {"pdf", "docx", "xlsx", "pptx"}:
            raise ApplicationError(
                "unsupported input format", type="DOCUMENT_INVALID", non_retryable=True
            )
        with tempfile.TemporaryDirectory(prefix="openlet-process-") as scratch:
            source = Path(scratch) / f"source.{kind}"
            output = Path(scratch) / "output"
            output.mkdir()
            if prepared["source"]["transport"] == "inline":
                data = base64.b64decode(
                    prepared["source"]["bytes_base64"], validate=True
                )
                if len(data) != size:
                    raise ApplicationError(
                        "source size mismatch",
                        type="DOCUMENT_INVALID",
                        non_retryable=True,
                    )
                source.write_bytes(data)
            else:
                async with storage.stream("GET", prepared["source"]["url"]) as response:
                    if not response.is_success:
                        raise ApplicationError(
                            "source download failed", type="DEPENDENCY_UNAVAILABLE"
                        )
                    count = 0
                    with source.open("wb") as file:
                        async for data in response.aiter_raw(1048576):
                            count += len(data)
                            if count > size:
                                raise ResourceLimit("source size")
                            file.write(data)
                    if count != size:
                        raise ApplicationError(
                            "source download incomplete", type="DEPENDENCY_UNAVAILABLE"
                        )
            await supervise(
                source,
                output,
                kind,
                self.models,
                prepared["max_outputs"],
                prepared["max_output_bytes"],
            )
            entries = sorted(output.rglob("*"))
            uploads = []
            directories = []
            for file in entries:
                name = file.relative_to(output).as_posix()
                if file.is_dir():
                    directories.append(name)
                else:
                    uploads.append(
                        await self.upload(api, storage, path, file, name, prepared)
                    )
            await self.request(
                api,
                path + "/complete",
                {"uploads": uploads, "directories": directories},
            )

    async def upload(self, api, storage, path, file, name, limits):
        size = file.stat().st_size
        inline = (
            file.suffix in {".md", ".csv", ".json", ".txt"}
            and size <= limits["inline_limit_bytes"]
        )
        multipart = not inline and size >= limits["multipart_threshold_bytes"]
        checksum = None
        if not inline and not multipart:
            with file.open("rb") as body:
                checksum = base64.b64encode(
                    hashlib.file_digest(body, "md5").digest()
                ).decode()
        prepared = await self.request(
            api,
            path + "/outputs",
            {
                "path": name,
                "storage": "inline" if inline else "object",
                "size_bytes": str(size),
                "content_md5": checksum,
            },
        )
        upload_path = path + "/uploads/" + prepared["id"]
        receipts = None
        if inline:
            response = await api.put(upload_path + "/bytes", content=file.read_bytes())
            if not response.is_success:
                raise ApplicationError(
                    "inline transfer failed", type="DEPENDENCY_UNAVAILABLE"
                )
        elif multipart:
            receipts = []
            with file.open("rb") as body:
                for number in range(1, prepared["part_count"] + 1):
                    data = body.read(int(prepared["part_size_bytes"]))
                    md5 = base64.b64encode(hashlib.md5(data).digest()).decode()
                    signed = await self.request(
                        api,
                        upload_path + "/parts",
                        {
                            "parts": [{"part_number": number, "content_md5": md5}],
                        },
                    )
                    response = await storage.put(
                        signed["items"][0]["transfer"]["url"],
                        content=data,
                        headers=signed["items"][0]["transfer"]["headers"],
                    )
                    if not response.is_success:
                        raise ApplicationError(
                            "part transfer failed", type="DEPENDENCY_UNAVAILABLE"
                        )
                    receipts.append(
                        {"part_number": number, "etag": response.headers["etag"]}
                    )
        else:

            async def chunks():
                with file.open("rb") as body:
                    while data := body.read(1048576):
                        yield data

            response = await storage.put(
                prepared["transfer"]["url"],
                content=chunks(),
                headers={
                    **prepared["transfer"]["headers"],
                    "content-length": str(size),
                },
            )
            if not response.is_success and response.status_code != 412:
                raise ApplicationError(
                    "object transfer failed", type="DEPENDENCY_UNAVAILABLE"
                )
        await self.request(api, upload_path + "/complete", {"parts": receipts})
        return prepared["id"]
