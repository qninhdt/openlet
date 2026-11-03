import asyncio

import grpc
import pytest

from openlet.clients.letfs import (
    ArchiveFrame,
    FilesystemClient,
    ProcessingClient,
    Storage,
    StorageAdministrationClient,
)
from openlet.errors import AppError
from openlet.rpc import RpcClient
from openlet_api.letfs.v1 import letfs_pb2 as pb
from openlet_api.letfs.v1 import letfs_pb2_grpc as letfs_rpc

TOKEN = "isolated-filesystem-service-credential-123"


class Filesystem(letfs_rpc.FilesystemServiceServicer):
    async def GetNode(self, request, context):
        assert [
            (item.path, item.filesystem_id) for item in request.path_context.mounts
        ] == [("/", request.filesystem_id)]
        return pb.GetNodeResponse(
            node=pb.Node(
                id=request.node_id,
                filesystem_id=(
                    "foreign" if request.node_id == "foreign" else request.filesystem_id
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
        assert request.path_context.mounts[0].filesystem_id == request.filesystem_id
        yield pb.StreamArchiveResponse(
            metadata=pb.ArchiveMetadata(filename="files.zip", mime="application/zip")
        )
        yield pb.StreamArchiveResponse(data=b"zip")


class Administration(letfs_rpc.StorageAdministrationServiceServicer):
    async def CreateStorage(self, request, context):
        return pb.CreateStorageResponse(
            bucket=pb.Bucket(
                id=request.bucket.bucket_id,
                limit_bytes=request.bucket.limit_bytes,
                state="active",
            ),
            filesystem=pb.Filesystem(
                id=request.filesystem.filesystem_id,
                bucket_id=request.filesystem.bucket_id,
                root_id="root",
                state="active",
            ),
        )


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


async def test_filesystem_client_supplies_default_mount_and_native_stream(letfs_server):
    async with RpcClient(letfs_server, TOKEN, allow_plaintext=True) as rpc:
        client = FilesystemClient(rpc)
        node = await client.get_node("drive", "file")
        assert node.id == "file"
        assert node.filesystem_id == "drive"
        assert node.media_type == "application/pdf"
        with pytest.raises(AppError) as captured:
            await client.get_node("drive", "foreign")
        assert captured.value.reason == "FILESYSTEM_SCOPE_CONFLICT"
        frames = [item async for item in client.stream_archive("drive", "root")]
        assert frames == [
            ArchiveFrame("files.zip", "application/zip"),
            ArchiveFrame(data=b"zip"),
        ]


async def test_storage_administration_client_uses_native_scope_validation(letfs_server):
    async with RpcClient(letfs_server, TOKEN, allow_plaintext=True) as rpc:
        result = await StorageAdministrationClient(rpc).create_storage(
            Storage(1024, "bucket", "drive")
        )
        assert result == Storage(1024, "bucket", "drive", "root")


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
            stream = FilesystemClient(rpc).stream_archive("drive", "root")
            assert await anext(stream) == ArchiveFrame(data=b"first")
            await stream.aclose()
            await asyncio.wait_for(stopped.wait(), timeout=2)
    finally:
        await server.stop(None)


def test_native_clients_cover_every_current_letfs_rpc():
    filesystem_methods = {
        "GetFilesystem": "get_filesystem",
        "GetBucketUsage": "get_bucket_usage",
        "CreateNode": "create_directory",
        "ListNodes": "list_nodes",
        "GetNode": "get_node",
        "ResolveNode": "resolve_node",
        "BatchStat": "batch_stat",
        "UpdateNode": "update_node",
        "ReplaceContent": "replace_content",
        "CreateCopy": "create_copy",
        "GetCopy": "get_copy",
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
        "CreateStorage": "create_storage",
        "DeleteFilesystem": "delete_filesystem",
        "CreateBucket": "create_bucket",
        "CreateFilesystem": "create_filesystem",
        "FreezeBucket": "freeze_bucket",
        "ListBucketFilesystems": "list_filesystems",
        "CompleteBucketDeletion": "complete_bucket_deletion",
        "ReleaseProvisioning": "release_provisioning",
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
