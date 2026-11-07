import asyncio

import grpc
import pytest

from openlet.clients.letfs import (
    ArchiveFrame,
    FilesystemClient,
    ProcessingClient,
    StorageAdministrationClient,
)
from openlet.errors import AppError
from openlet.rpc import RpcClient
from openlet_api.letfs.v1 import letfs_pb2 as pb
from openlet_api.letfs.v1 import letfs_pb2_grpc as letfs_rpc

TOKEN = "isolated-filesystem-service-credential-123"


class Filesystem(letfs_rpc.FilesystemServiceServicer):
    async def GetFilesystem(self, request, context):
        return pb.GetFilesystemResponse(
            filesystem=pb.Filesystem(
                id=request.filesystem_id,
                limit_bytes=1024,
                state="active",
            )
        )

    async def GetNode(self, request, context):
        assert request.scope_id == "shared"
        return pb.GetNodeResponse(
            node=pb.Node(
                id=request.node_id,
                scope_id=(
                    "foreign" if request.node_id == "foreign" else request.scope_id
                ),
                parent_id="root",
                name="report.pdf",
                kind="file",
                revision=7,
                size_bytes=42,
                media_type="application/pdf",
            )
        )

    async def StreamArchive(self, request, context):
        assert request.scope_id == "shared"
        yield pb.StreamArchiveResponse(
            metadata=pb.ArchiveMetadata(filename="files.zip", mime="application/zip")
        )
        yield pb.StreamArchiveResponse(data=b"zip")


class Administration(letfs_rpc.StorageAdministrationServiceServicer):
    async def CreateFilesystem(self, request, context):
        return pb.CreateFilesystemResponse(
            filesystem=pb.Filesystem(
                id=request.filesystem_id,
                limit_bytes=request.limit_bytes,
                state="active",
            )
        )

    async def CreateScopes(self, request, context):
        scopes = [
            pb.Scope(
                id=id,
                filesystem_id=request.filesystem_id,
                root_id="root-" + id,
                state="active",
                allow_blob_files=(
                    not request.allow_blob_files
                    if request.filesystem_id == "mismatch-blob"
                    else request.allow_blob_files
                ),
                allow_indexing=(
                    not request.allow_indexing
                    if request.filesystem_id == "mismatch-index"
                    else request.allow_indexing
                ),
            )
            for id in request.scope_ids
        ]
        match request.filesystem_id:
            case "missing":
                scopes.pop()
            case "duplicate":
                scopes[-1].id = scopes[0].id
            case "foreign":
                scopes[-1].filesystem_id = "other"
            case "empty-root":
                scopes[-1].root_id = ""
        return pb.CreateScopesResponse(scopes=scopes)


@pytest.fixture
async def letfs_server():
    server = grpc.aio.server()
    letfs_rpc.add_FilesystemServiceServicer_to_server(Filesystem(), server)
    letfs_rpc.add_StorageAdministrationServiceServicer_to_server(
        Administration(), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        yield f"127.0.0.1:{port}"
    finally:
        await server.stop(None)


async def test_filesystem_client_supplies_scope_and_native_stream(letfs_server):
    async with RpcClient(letfs_server, TOKEN, allow_plaintext=True) as rpc:
        client = FilesystemClient(rpc)
        node = await client.get_node("drive", "shared", "file")
        assert node.id == "file"
        assert node.scope_id == "shared"
        assert node.media_type == "application/pdf"
        with pytest.raises(AppError) as captured:
            await client.get_node("drive", "shared", "foreign")
        assert captured.value.reason == "FILESYSTEM_SCOPE_CONFLICT"
        frames = [
            item async for item in client.stream_archive("drive", "shared", "root")
        ]
        assert frames == [
            ArchiveFrame("files.zip", "application/zip"),
            ArchiveFrame(data=b"zip"),
        ]


@pytest.mark.parametrize("allow_blob_files", [False, True])
@pytest.mark.parametrize("allow_indexing", [False, True])
async def test_storage_administration_scope_options(
    letfs_server, allow_blob_files, allow_indexing
):
    async with RpcClient(letfs_server, TOKEN, allow_plaintext=True) as rpc:
        client = StorageAdministrationClient(rpc)
        filesystem = await client.create_filesystem("notes", 1024, "key")
        assert filesystem.id == "notes"
        scopes = await client.create_scopes(
            "notes",
            ["scope"],
            "key",
            allow_blob_files=allow_blob_files,
            allow_indexing=allow_indexing,
        )
        assert scopes[0].allow_blob_files is allow_blob_files
        assert scopes[0].allow_indexing is allow_indexing
        for mismatch in ("mismatch-blob", "mismatch-index"):
            with pytest.raises(AppError, match="invalid scope result"):
                await client.create_scopes(
                    mismatch,
                    ["scope"],
                    "key",
                    allow_blob_files=allow_blob_files,
                    allow_indexing=allow_indexing,
                )
        defaults = await client.create_scopes("notes", ["defaults"], "default-key")
        assert defaults[0].allow_blob_files and defaults[0].allow_indexing


async def test_filesystem_client_reads_metadata(letfs_server):
    async with RpcClient(letfs_server, TOKEN, allow_plaintext=True) as rpc:
        assert (await FilesystemClient(rpc).get_filesystem("notes")).limit_bytes == 1024


async def test_closing_archive_cancels_rpc_before_channel_closes():
    stopped = asyncio.Event()

    class BlockingFilesystem(letfs_rpc.FilesystemServiceServicer):
        async def StreamArchive(self, request, context):
            try:
                yield pb.StreamArchiveResponse(data=b"first")
                await asyncio.Event().wait()
            finally:
                stopped.set()

    server = grpc.aio.server()
    letfs_rpc.add_FilesystemServiceServicer_to_server(BlockingFilesystem(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with RpcClient(f"127.0.0.1:{port}", TOKEN, allow_plaintext=True) as rpc:
            stream = FilesystemClient(rpc).stream_archive("drive", "shared", "root")
            assert await anext(stream) == ArchiveFrame(data=b"first")
            await stream.aclose()
            await asyncio.wait_for(stopped.wait(), timeout=2)
    finally:
        await server.stop(None)


def test_native_clients_cover_every_current_letfs_rpc():
    filesystem_methods = {
        "GetFilesystem": "get_filesystem",
        "CreateNode": "create_directory",
        "ListNodes": "list_nodes",
        "GetNode": "get_node",
        "ResolveNode": "resolve_node",
        "BatchStat": "batch_stat",
        "UpdateNode": "update_node",
        "ReplaceContent": "replace_content",
        "CreateCopy": "create_copy",
        "GetProcessing": "get_processing",
        "ReprocessNode": "reprocess_node",
        "TrashNode": "trash_node",
        "ListTrash": "list_trash",
        "GetTrash": "get_trash",
        "RestoreTrash": "restore_trash",
        "PurgeTrash": "purge_trash",
        "CreateUpload": "create_upload",
        "GetUpload": "get_upload",
        "GetUploadParts": "get_upload_parts",
        "CompleteUpload": "complete_upload",
        "AbortUpload": "abort_upload",
        "SearchFiles": "search_files",
        "SemanticSearch": "semantic_search",
        "GetDownload": "get_download",
        "StreamArchive": "stream_archive",
    }
    administration_methods = {
        "DeleteFilesystem": "delete_filesystem",
        "CreateFilesystem": "create_filesystem",
        "CreateScopes": "create_scopes",
    }
    processing_methods = {
        "PrepareParse": "prepare_parse",
        "PrepareParseOutput": "prepare_parse_output",
        "CompleteParse": "complete_parse",
        "AbortParse": "abort_parse",
        "PrepareEnrichment": "prepare_enrichment",
        "PrepareEnrichmentOutput": "prepare_enrichment_output",
        "CompleteEnrichment": "complete_enrichment",
        "FailEnrichment": "fail_enrichment",
        "PrepareIndex": "prepare_index",
        "CompleteIndex": "complete_index",
        "FailIndex": "fail_index",
        "GetOutputUpload": "get_output_upload",
        "GetOutputUploadParts": "get_output_upload_parts",
        "CompleteOutputUpload": "complete_output_upload",
        "WriteOutputBytes": "write_output_bytes",
    }
    descriptor = pb.DESCRIPTOR.services_by_name
    assert set(filesystem_methods) == {
        method.name for method in descriptor["FilesystemService"].methods
    }
    assert set(administration_methods) == {
        method.name for method in descriptor["StorageAdministrationService"].methods
    }
    assert set(processing_methods) == {
        method.name for method in descriptor["IngestService"].methods
    }
    assert all(hasattr(FilesystemClient, name) for name in filesystem_methods.values())
    assert all(
        hasattr(StorageAdministrationClient, name)
        for name in administration_methods.values()
    )
    assert all(hasattr(ProcessingClient, name) for name in processing_methods.values())


@pytest.mark.parametrize(
    "filesystem", ["missing", "duplicate", "foreign", "empty-root"]
)
async def test_scope_creation_rejects_malformed_response(letfs_server, filesystem):
    async with RpcClient(letfs_server, TOKEN, allow_plaintext=True) as rpc:
        with pytest.raises(AppError, match="invalid scope result"):
            await StorageAdministrationClient(rpc).create_scopes(
                filesystem, ["a", "b"], "key"
            )
