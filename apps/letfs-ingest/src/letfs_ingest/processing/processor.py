import base64
import hashlib
import tempfile
from pathlib import Path

import httpx
from openlet.clients.letfs import (
    EnrichmentInput,
    EnrichmentUpdate,
    Generation,
    IndexInput,
    InventoryNode,
    OutputDescription,
    OutputScope,
    ParseInput,
    PartReceipt,
    SemanticMetadata,
)
from openlet.errors import AppError

from letfs_ingest.clients.qdrant import IndexSettings, Qdrant
from letfs_ingest.parser.convert_child import MAX_INPUT_BYTES, ResourceLimit
from letfs_ingest.parser.supervisor import supervise
from letfs_ingest.processing.indexing import index_tree
from letfs_ingest.processing.semantic import enrich_tree


def tree_nodes(nodes):
    return [
        {
            name: getattr(node, name)
            for name in (
                "id",
                "parent_id",
                "path",
                "name",
                "kind",
                "media_type",
                "title",
                "description",
                "context",
            )
        }
        for node in nodes
    ]


class Processor:
    def __init__(
        self, models: Path | None, ai=None, index_settings: IndexSettings | None = None
    ):
        self.models = models
        self.ai = ai
        self.index_settings = index_settings

    async def content_bytes(self, storage, node: InventoryNode) -> bytes:
        size = node.size_bytes
        if not 0 <= size <= MAX_INPUT_BYTES:
            raise ResourceLimit("evidence bytes")
        if node.inline_content is not None:
            data = node.inline_content
        elif node.signed_url is not None:
            data = bytearray()
            async with storage.stream("GET", node.signed_url) as response:
                if not response.is_success:
                    raise AppError(
                        "evidence unavailable", reason="DEPENDENCY_UNAVAILABLE"
                    )
                async for chunk in response.aiter_raw(1048576):
                    data.extend(chunk)
                    if len(data) > size:
                        raise ResourceLimit("evidence bytes")
            data = bytes(data)
        else:
            raise AppError("evidence unavailable", reason="DEPENDENCY_UNAVAILABLE")
        if len(data) != size:
            raise AppError("evidence incomplete", reason="DEPENDENCY_UNAVAILABLE")
        return data

    async def enrich(self, api, storage, generation: Generation):

        prepared = await api.prepare_enrichment(generation)
        if prepared is None:
            return
        nodes = tree_nodes(prepared.nodes)
        contents = {}
        total = 0
        for node in prepared.nodes:
            if node.inline_content is not None or node.signed_url is not None:
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
                    EnrichmentUpdate(
                        id=node.id,
                        path=paths[node.id],
                        metadata=SemanticMetadata(
                            metadata[node.id].title,
                            metadata[node.id].description,
                            metadata[node.id].semantic_type,
                            metadata[node.id].context,
                        )
                        if node.kind == "file"
                        else None,
                        upload_id=upload,
                    )
                )
            await api.complete_enrichment(generation, updates)

    async def index(self, api, storage, generation: Generation, prepared: IndexInput):

        contents = {}
        total = 0
        for node in prepared.nodes:
            mime = node.media_type
            if (
                node.inline_content is None
                and node.signed_url is None
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
        if space is None:
            raise AppError("missing vector space", reason="DEPENDENCY_UNAVAILABLE")
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
                space,
                prepared.filesystem_id,
                prepared.source_id,
                prepared.generation,
                batch_size=settings.batch_size,
                chunk_tokens=settings.chunk_tokens,
                overlap=settings.overlap,
            )
        await api.complete_index(generation)

    async def process(self, api, storage, generation: Generation):
        prepared = await api.prepare_parse(generation)
        if prepared is None:
            return
        size = prepared.size_bytes
        if not 0 <= size <= MAX_INPUT_BYTES:
            raise ResourceLimit("input bytes")
        kind = prepared.format
        if kind not in {"pdf", "docx", "xlsx", "pptx"}:
            raise AppError(
                "unsupported input format", reason="DOCUMENT_INVALID", retryable=False
            )
        with tempfile.TemporaryDirectory(prefix="openlet-process-") as scratch:
            source = Path(scratch) / f"source.{kind}"
            output = Path(scratch) / "output"
            output.mkdir()
            if prepared.inline_content is not None:
                data = prepared.inline_content
                if len(data) != size:
                    raise AppError(
                        "source size mismatch",
                        reason="DOCUMENT_INVALID",
                        retryable=False,
                    )
                source.write_bytes(data)
            elif prepared.signed_url is not None:
                async with storage.stream("GET", prepared.signed_url) as response:
                    if not response.is_success:
                        raise AppError(
                            "source download failed", reason="DEPENDENCY_UNAVAILABLE"
                        )
                    count = 0
                    with source.open("wb") as file:
                        async for data in response.aiter_raw(1048576):
                            count += len(data)
                            if count > size:
                                raise ResourceLimit("source size")
                            file.write(data)
                    if count != size:
                        raise AppError(
                            "source download incomplete",
                            reason="DEPENDENCY_UNAVAILABLE",
                        )
            else:
                raise AppError("missing source", reason="DEPENDENCY_UNAVAILABLE")
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
            await api.complete_parse(generation, uploads, directories)

    async def upload(
        self,
        api,
        storage,
        generation: Generation,
        stage: str,
        file: Path,
        name: str,
        limits: ParseInput | EnrichmentInput,
    ) -> str:
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
        output = OutputDescription(
            path=name,
            storage="inline" if inline else "object",
            size_bytes=size,
            content_md5=checksum,
        )
        if stage == "parse":
            prepared = await api.prepare_parse_output(generation, output)
        else:
            prepared = await api.prepare_enrichment_output(generation, output)
        scope = OutputScope(source=generation, stage=stage, upload_id=prepared.id)
        if prepared.status in {"completing", "finalized"}:
            await api.complete_output_upload(scope, ())
            return prepared.id
        if prepared.status != "open":
            raise AppError(
                "output upload is no longer active",
                reason="UPLOAD_NOT_ACTIVE",
                retryable=False,
            )
        receipts = []
        if inline:
            await api.write_output_bytes(scope, file.read_bytes())
        elif multipart:
            with file.open("rb") as body:
                for number in range(1, prepared.part_count + 1):
                    data = body.read(prepared.part_size_bytes)
                    signed = await api.get_output_upload_parts(scope, [number])
                    response = await storage.put(
                        signed[0].transfer.url,
                        content=data,
                        headers=dict(signed[0].transfer.headers),
                    )
                    if not response.is_success:
                        raise AppError(
                            "part transfer failed", reason="DEPENDENCY_UNAVAILABLE"
                        )
                    receipts.append(
                        PartReceipt(part_number=number, etag=response.headers["etag"])
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
                raise AppError(
                    "object transfer failed", reason="DEPENDENCY_UNAVAILABLE"
                )
        await api.complete_output_upload(scope, receipts)
        return prepared.id
