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
    for key in ("MIN_LEAF_TOKENS", "SPLIT_TOKENS"):
        if key in os.environ:
            environment[key] = os.environ[key]
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
    def __init__(
        self, base_url: str, token: str, models: Path, ai=None, index_settings=None
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.models = models
        self.ai = ai
        self.index_settings = index_settings

    @activity.defn(name="enrich_file")
    async def enrich_file(self, source: dict) -> dict:
        file_id = str(UUID(source["file_id"]))
        path = (
            f"/internal/v1/processing/{file_id}/{source['generation']}/enrichment/"
            f"{activity.info().attempt}/{uuid4()}"
        )
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
                        await self.enrich(api, storage, path)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    code = (
                        error.type
                        if isinstance(error, ApplicationError)
                        else "RESOURCE_LIMIT"
                        if isinstance(error, ResourceLimit)
                        else "PROCESSING_FAILED"
                    )
                    terminal = isinstance(error, ResourceLimit) or (
                        isinstance(error, ApplicationError) and error.non_retryable
                    )
                    if terminal or activity.info().attempt >= 3:
                        try:
                            await self.request(api, path + "/fail", {"code": code})
                        except Exception:
                            LOG.warning("enrichment failure reconciliation deferred")
                    raise ApplicationError(
                        "semantic enrichment failed",
                        type=code,
                        non_retryable=isinstance(error, ResourceLimit)
                        or (
                            isinstance(error, ApplicationError) and error.non_retryable
                        ),
                    ) from None
            return source
        finally:
            pulse.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pulse

    async def content_bytes(self, storage, node):
        size = int(node["size_bytes"])
        if not 0 <= size <= MAX_INPUT_BYTES:
            raise ResourceLimit("evidence bytes")
        descriptor = node["content"]
        if descriptor["transport"] == "inline":
            data = base64.b64decode(descriptor["bytes_base64"], validate=True)
        else:
            data = bytearray()
            async with storage.stream("GET", descriptor["url"]) as response:
                if not response.is_success:
                    raise ApplicationError(
                        "evidence unavailable", type="DEPENDENCY_UNAVAILABLE"
                    )
                async for chunk in response.aiter_raw(1048576):
                    data.extend(chunk)
                    if len(data) > size:
                        raise ResourceLimit("evidence bytes")
            data = bytes(data)
        if len(data) != size:
            raise ApplicationError("evidence incomplete", type="DEPENDENCY_UNAVAILABLE")
        return data

    async def enrich(self, api, storage, path):
        from openlet_processor.semantic import enrich_tree

        prepared = await self.request(api, path + "/prepare", {})
        if prepared["state"] == "succeeded":
            return
        nodes = prepared["nodes"]
        contents = {}
        total = 0
        for node in nodes:
            if "content" in node:
                total += int(node["size_bytes"])
                if total > prepared["max_output_bytes"] + MAX_INPUT_BYTES:
                    raise ResourceLimit("evidence tree bytes")
                contents[node["id"]] = await self.content_bytes(storage, node)
        paths, metadata, rewritten = await enrich_tree(nodes, contents, self.ai)
        with tempfile.TemporaryDirectory(prefix="openlet-enrich-") as scratch:
            updates = []
            for node in nodes:
                upload = None
                if node["id"] in rewritten:
                    file = Path(scratch) / "README.md"
                    file.write_bytes(rewritten[node["id"]])
                    upload = await self.upload(
                        api,
                        storage,
                        path,
                        file,
                        paths[node["id"]],
                        prepared,
                    )
                updates.append(
                    {
                        "id": node["id"],
                        "path": paths[node["id"]],
                        "metadata": metadata[node["id"]].model_dump(by_alias=True)
                        if node["kind"] == "file"
                        else None,
                        "upload_id": upload,
                    }
                )
            await self.request(api, path + "/complete", {"nodes": updates})

    @activity.defn(name="index_file")
    async def index_file(self, source: dict) -> dict:
        file_id = str(UUID(source["file_id"]))
        path = f"/internal/v1/processing/{file_id}/{source['generation']}/index"
        prepared = None
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
                        prepared = await self.request(api, path + "/prepare", {})
                        if prepared["state"] != "succeeded":
                            await self.index(api, storage, path, prepared)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    code = (
                        error.type
                        if isinstance(error, ApplicationError)
                        else "RESOURCE_LIMIT"
                        if isinstance(error, ResourceLimit)
                        else "DEPENDENCY_UNAVAILABLE"
                    )
                    terminal = isinstance(error, ResourceLimit) or (
                        isinstance(error, ApplicationError) and error.non_retryable
                    )
                    if (
                        (terminal or activity.info().attempt >= 3)
                        and prepared is not None
                        and "vector_space" in prepared
                    ):
                        try:
                            await self.request(
                                api,
                                path + "/fail",
                                {
                                    "code": code,
                                    "vector_space": prepared["vector_space"],
                                },
                            )
                        except Exception:
                            LOG.warning("index failure reconciliation deferred")
                    raise ApplicationError(
                        "search indexing failed",
                        type=code,
                        non_retryable=isinstance(error, ResourceLimit)
                        or (
                            isinstance(error, ApplicationError) and error.non_retryable
                        ),
                    ) from None
            return source
        finally:
            pulse.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pulse

    async def index(self, api, storage, path, prepared):
        from openlet_processor.indexing import Qdrant, VectorSpace, index_tree

        contents = {}
        total = 0
        for node in prepared["nodes"]:
            mime = node["media_type"] or ""
            if "content" not in node or mime == "text/csv" or mime.startswith("image/"):
                continue
            total += int(node["size_bytes"])
            if total > prepared["max_output_bytes"] + MAX_INPUT_BYTES:
                raise ResourceLimit("index tree bytes")
            contents[node["id"]] = await self.content_bytes(storage, node)
        settings = self.index_settings
        if settings is None:
            raise ValueError("index settings are missing")
        async with httpx.AsyncClient(
            base_url=settings.url,
            headers={"api-key": settings.api_key},
            timeout=120,
            follow_redirects=False,
        ) as client:
            await index_tree(
                prepared["nodes"],
                contents,
                self.ai,
                Qdrant(client),
                VectorSpace(**prepared["vector_space"]),
                prepared["filesystem_id"],
                prepared["source_id"],
                prepared["generation"],
                batch_size=settings.batch_size,
                chunk_tokens=settings.chunk_tokens,
                overlap=settings.overlap,
            )
        await self.request(
            api, path + "/complete", {"vector_space": prepared["vector_space"]}
        )

    @activity.defn(name="process_file")
    async def process_file(self, source: dict) -> dict:
        file_id = str(UUID(source["file_id"]))
        path = (
            f"/internal/v1/processing/{file_id}/{source['generation']}/parse/"
            f"{activity.info().attempt}/{uuid4()}"
        )
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
            return source
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
                code = data.get("code", "PROCESSING_FAILED")
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
        if prepared["status"] in {"completing", "finalized"}:
            await self.request(api, upload_path + "/complete", {"parts": None})
            return prepared["id"]
        if prepared["status"] != "open":
            raise ApplicationError(
                "output upload is no longer active",
                type="UPLOAD_NOT_ACTIVE",
                non_retryable=True,
            )
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
                    signed = await self.request(
                        api,
                        upload_path + "/parts",
                        {
                            "parts": [number],
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
