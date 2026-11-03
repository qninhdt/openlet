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
from uuid import UUID

import httpx
from openlet_api.letfs.v1 import letfs_pb2 as pb
from temporalio import activity
from temporalio.exceptions import ApplicationError

from letfs_ingest.convert_child import (
    MAX_INPUT_BYTES,
    MAX_SCRATCH_BYTES,
    ResourceLimit,
    check_outputs,
)
from letfs_ingest.ingest_rpc import IngestRPC

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
        "letfs_ingest.convert_child",
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


def processing_generation(source):
    return pb.ProcessingGeneration(
        file_id=str(UUID(source["file_id"])),
        generation=source["generation"],
    )


def tree_nodes(nodes):
    # The semantic/indexing functions consume tree metadata, independent of transport.
    return [
        {
            "id": node.id,
            "parent_id": node.parent_id or None,
            "path": node.path,
            "name": node.name,
            "kind": node.kind,
            "media_type": node.media_type,
            "title": node.title,
            "description": node.description,
            "context": node.context,
        }
        for node in nodes
    ]


class Processor:
    def __init__(
        self,
        address: str,
        token: str,
        models: Path,
        ai=None,
        index_settings=None,
        *,
        allow_plaintext=False,
    ):
        self.address = address
        self.token = token
        self.models = models
        self.ai = ai
        self.index_settings = index_settings
        self.allow_plaintext = allow_plaintext

    def connect(self):
        return IngestRPC(self.address, self.token, allow_plaintext=self.allow_plaintext)

    @activity.defn(name="enrich_file")
    async def enrich_file(self, source: dict) -> dict:
        generation = processing_generation(source)
        pulse = asyncio.create_task(heartbeat())
        try:
            async with (
                self.connect() as api,
                httpx.AsyncClient(timeout=120, follow_redirects=False) as storage,
            ):
                try:
                    async with asyncio.timeout(1700):
                        await self.enrich(api, storage, generation)
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
                            await api.call(
                                "FailEnrichment",
                                pb.FailEnrichmentRequest(
                                    source=generation, error_code=code
                                ),
                            )
                        except Exception:
                            LOG.warning("enrichment failure reconciliation deferred")
                    raise ApplicationError(
                        "semantic enrichment failed",
                        type=code,
                        non_retryable=terminal,
                    ) from None
            return source
        finally:
            pulse.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pulse

    async def content_bytes(self, storage, node):
        size = node.size_bytes
        if not 0 <= size <= MAX_INPUT_BYTES:
            raise ResourceLimit("evidence bytes")
        if node.WhichOneof("content") == "inline_content":
            data = node.inline_content
        elif node.WhichOneof("content") == "signed_url":
            data = bytearray()
            async with storage.stream("GET", node.signed_url) as response:
                if not response.is_success:
                    raise ApplicationError(
                        "evidence unavailable", type="DEPENDENCY_UNAVAILABLE"
                    )
                async for chunk in response.aiter_raw(1048576):
                    data.extend(chunk)
                    if len(data) > size:
                        raise ResourceLimit("evidence bytes")
            data = bytes(data)
        else:
            raise ApplicationError(
                "evidence unavailable", type="DEPENDENCY_UNAVAILABLE"
            )
        if len(data) != size:
            raise ApplicationError("evidence incomplete", type="DEPENDENCY_UNAVAILABLE")
        return data

    async def enrich(self, api, storage, generation):
        from letfs_ingest.semantic import enrich_tree

        response = await api.call(
            "PrepareEnrichment", pb.PrepareEnrichmentRequest(source=generation)
        )
        if response.WhichOneof("result") == "complete":
            return
        if response.WhichOneof("result") != "input":
            raise ApplicationError(
                "missing enrichment input", type="DEPENDENCY_UNAVAILABLE"
            )
        prepared = response.input
        nodes = tree_nodes(prepared.nodes)
        contents = {}
        total = 0
        for node in prepared.nodes:
            if node.WhichOneof("content") is not None:
                total += node.size_bytes
                if total > prepared.max_output_bytes + MAX_INPUT_BYTES:
                    raise ResourceLimit("evidence tree bytes")
                contents[node.id] = await self.content_bytes(storage, node)
        paths, metadata, rewritten = await enrich_tree(nodes, contents, self.ai)
        with tempfile.TemporaryDirectory(prefix="openlet-enrich-") as scratch:
            updates = []
            for node in prepared.nodes:
                upload = None
                if node.id in rewritten:
                    file = Path(scratch) / "README.md"
                    file.write_bytes(rewritten[node.id])
                    upload = await self.upload(
                        api,
                        storage,
                        generation,
                        "enrichment",
                        file,
                        paths[node.id],
                        prepared,
                    )
                updates.append(
                    pb.EnrichmentUpdate(
                        id=node.id,
                        path=paths[node.id],
                        metadata=pb.SemanticMetadata(**metadata[node.id].model_dump())
                        if node.kind == "file"
                        else None,
                        upload_id=upload,
                    )
                )
            await api.call(
                "CompleteEnrichment",
                pb.CompleteEnrichmentRequest(source=generation, nodes=updates),
            )

    @activity.defn(name="index_file")
    async def index_file(self, source: dict) -> dict:
        generation = pb.ProcessingGeneration(
            file_id=str(UUID(source["file_id"])), generation=source["generation"]
        )
        prepared = None
        pulse = asyncio.create_task(heartbeat())
        try:
            async with (
                self.connect() as api,
                httpx.AsyncClient(timeout=120, follow_redirects=False) as storage,
            ):
                try:
                    async with asyncio.timeout(1700):
                        response = await api.call(
                            "PrepareIndex", pb.PrepareIndexRequest(source=generation)
                        )
                        if response.WhichOneof("result") == "input":
                            prepared = response.input
                            await self.index(api, storage, generation, prepared)
                        elif response.WhichOneof("result") != "complete":
                            raise ApplicationError(
                                "missing index input", type="DEPENDENCY_UNAVAILABLE"
                            )
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
                        and prepared.HasField("vector_space")
                    ):
                        try:
                            await api.call(
                                "FailIndex",
                                pb.FailIndexRequest(
                                    source=generation,
                                    error_code=code,
                                ),
                            )
                        except Exception:
                            LOG.warning("index failure reconciliation deferred")
                    raise ApplicationError(
                        "search indexing failed", type=code, non_retryable=terminal
                    ) from None
            return source
        finally:
            pulse.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pulse

    async def index(self, api, storage, generation, prepared):
        from letfs_ingest.indexing import Qdrant, VectorSpace, index_tree

        contents = {}
        total = 0
        for node in prepared.nodes:
            mime = node.media_type
            if (
                node.WhichOneof("content") is None
                or mime == "text/csv"
                or mime.startswith("image/")
            ):
                continue
            total += node.size_bytes
            if total > prepared.max_output_bytes + MAX_INPUT_BYTES:
                raise ResourceLimit("index tree bytes")
            contents[node.id] = await self.content_bytes(storage, node)
        settings = self.index_settings
        if settings is None:
            raise ValueError("index settings are missing")
        space = prepared.vector_space
        async with httpx.AsyncClient(
            base_url=settings.url,
            headers={"api-key": settings.api_key},
            timeout=120,
            follow_redirects=False,
        ) as client:
            await index_tree(
                tree_nodes(prepared.nodes),
                contents,
                self.ai,
                Qdrant(client),
                VectorSpace(space.model, space.collection, space.dimension),
                prepared.filesystem_id,
                prepared.source_id,
                prepared.generation,
                batch_size=settings.batch_size,
                chunk_tokens=settings.chunk_tokens,
                overlap=settings.overlap,
            )
        await api.call(
            "CompleteIndex",
            pb.CompleteIndexRequest(source=generation),
        )

    @activity.defn(name="process_file")
    async def process_file(self, source: dict) -> dict:
        generation = processing_generation(source)
        pulse = asyncio.create_task(heartbeat())
        try:
            async with (
                self.connect() as api,
                httpx.AsyncClient(timeout=120, follow_redirects=False) as storage,
            ):
                try:
                    async with asyncio.timeout(1700):
                        await self.process(api, storage, generation)
                except asyncio.CancelledError:
                    details = activity.cancellation_details()
                    if details and details.cancel_requested:
                        await self.abort(api, generation, "PROCESSING_CANCELLED")
                    raise
                except ResourceLimit:
                    await self.abort(api, generation, "RESOURCE_LIMIT")
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
                            in {"RESOURCE_LIMIT", "QUOTA_EXCEEDED", "DOCUMENT_INVALID"}
                            else "PROCESSING_FAILED"
                        )
                        await self.abort(api, generation, code)
                    raise
                except Exception:
                    raise ApplicationError(
                        "processing dependency failed", type="DEPENDENCY_UNAVAILABLE"
                    ) from None
            return source
        finally:
            pulse.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pulse

    async def abort(self, api, generation, code):
        try:
            async with asyncio.timeout(5):
                await api.call(
                    "AbortParse",
                    pb.AbortParseRequest(source=generation, error_code=code),
                )
        except (Exception, asyncio.CancelledError):
            LOG.warning("generation cleanup deferred to letfs maintenance")

    async def process(self, api, storage, generation):
        response = await api.call(
            "PrepareParse",
            pb.PrepareParseRequest(
                file_id=generation.file_id,
                generation=generation.generation,
            ),
        )
        if response.WhichOneof("result") == "complete":
            return
        if response.WhichOneof("result") != "input":
            raise ApplicationError("missing parse input", type="DEPENDENCY_UNAVAILABLE")
        prepared = response.input
        size = prepared.size_bytes
        if not 0 <= size <= MAX_INPUT_BYTES:
            raise ResourceLimit("input bytes")
        kind = prepared.format
        if kind not in {"pdf", "docx", "xlsx", "pptx"}:
            raise ApplicationError(
                "unsupported input format", type="DOCUMENT_INVALID", non_retryable=True
            )
        with tempfile.TemporaryDirectory(prefix="openlet-process-") as scratch:
            source = Path(scratch) / f"source.{kind}"
            output = Path(scratch) / "output"
            output.mkdir()
            if prepared.WhichOneof("source") == "inline_content":
                data = prepared.inline_content
                if len(data) != size:
                    raise ApplicationError(
                        "source size mismatch",
                        type="DOCUMENT_INVALID",
                        non_retryable=True,
                    )
                source.write_bytes(data)
            elif prepared.WhichOneof("source") == "signed_url":
                async with storage.stream("GET", prepared.signed_url) as response:
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
            else:
                raise ApplicationError("missing source", type="DEPENDENCY_UNAVAILABLE")
            await supervise(
                source,
                output,
                kind,
                self.models,
                prepared.max_outputs,
                prepared.max_output_bytes,
            )
            uploads = []
            directories = []
            for file in sorted(output.rglob("*")):
                name = file.relative_to(output).as_posix()
                if file.is_dir():
                    directories.append(name)
                else:
                    uploads.append(
                        await self.upload(
                            api, storage, generation, "parse", file, name, prepared
                        )
                    )
            await api.call(
                "CompleteParse",
                pb.CompleteParseRequest(
                    source=generation, uploads=uploads, directories=directories
                ),
            )

    async def upload(self, api, storage, generation, stage, file, name, limits):
        size = file.stat().st_size
        inline = (
            file.suffix in {".md", ".csv", ".json", ".txt"}
            and size <= limits.inline_limit_bytes
        )
        multipart = not inline and size >= limits.multipart_threshold_bytes
        checksum = None
        if not inline and not multipart:
            with file.open("rb") as body:
                checksum = base64.b64encode(
                    hashlib.file_digest(body, "md5").digest()
                ).decode()
        output = pb.OutputDescription(
            path=name,
            storage="inline" if inline else "object",
            size_bytes=size,
            content_md5=checksum,
        )
        if stage == "parse":
            response = await api.call(
                "PrepareParseOutput",
                pb.PrepareParseOutputRequest(source=generation, output=output),
            )
        else:
            response = await api.call(
                "PrepareEnrichmentOutput",
                pb.PrepareEnrichmentOutputRequest(source=generation, output=output),
            )
        prepared = response.upload
        scope = pb.OutputUploadScope(
            source=generation, stage=stage, upload_id=prepared.id
        )
        if prepared.status in {"completing", "finalized"}:
            await api.call(
                "CompleteOutputUpload", pb.CompleteOutputUploadRequest(scope=scope)
            )
            return prepared.id
        if prepared.status != "open":
            raise ApplicationError(
                "output upload is no longer active",
                type="UPLOAD_NOT_ACTIVE",
                non_retryable=True,
            )
        receipts = []
        if inline:
            await api.call(
                "WriteOutputBytes",
                pb.WriteOutputBytesRequest(scope=scope, content=file.read_bytes()),
            )
        elif multipart:
            with file.open("rb") as body:
                for number in range(1, prepared.part_count + 1):
                    data = body.read(prepared.part_size_bytes)
                    signed = await api.call(
                        "GetOutputUploadParts",
                        pb.GetOutputUploadPartsRequest(scope=scope, numbers=[number]),
                    )
                    response = await storage.put(
                        signed.items[0].transfer.url,
                        content=data,
                        headers=dict(signed.items[0].transfer.headers),
                    )
                    if not response.is_success:
                        raise ApplicationError(
                            "part transfer failed", type="DEPENDENCY_UNAVAILABLE"
                        )
                    receipts.append(
                        pb.PartReceipt(
                            part_number=number, etag=response.headers["etag"]
                        )
                    )
        else:

            async def chunks():
                with file.open("rb") as body:
                    while data := body.read(1048576):
                        yield data

            response = await storage.put(
                prepared.transfer.url,
                content=chunks(),
                headers={**prepared.transfer.headers, "content-length": str(size)},
            )
            if not response.is_success and response.status_code != 412:
                raise ApplicationError(
                    "object transfer failed", type="DEPENDENCY_UNAVAILABLE"
                )
        await api.call(
            "CompleteOutputUpload",
            pb.CompleteOutputUploadRequest(scope=scope, parts=receipts),
        )
        return prepared.id
