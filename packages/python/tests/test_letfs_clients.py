import asyncio

import grpc
import pytest

from openlet.clients.letfs import (
    ArchiveFrame,
    ExistingText,
    FilesystemClient,
    Locator,
    ProcessingClient,
    ScopedLocator,
    StorageAdministrationClient,
    TextCreation,
    TextSelection,
)
from openlet.errors import AppError
from openlet.rpc import RpcClient
from openlet_api.letfs.v1 import letfs_pb2 as pb
from openlet_api.letfs.v1 import letfs_pb2_grpc as letfs_rpc

TOKEN = "isolated-filesystem-service-credential-123"


class Filesystem(letfs_rpc.FilesystemServiceServicer):
    async def TextSearch(self, request, context):
        assert request.locator.root_id == "mount"
        assert request.text == "needle" and request.ignore_case
        assert request.max_files == 5 and request.max_lines == 10
        assert request.max_bytes == 2048
        if request.scope_id == "incomplete":
            return pb.TextSearchResponse(complete=False)
        stat = self.read_stat(request.scope_id)
        if request.mode == "lines":
            return pb.TextSearchResponse(
                complete=True, stat=stat, content=b"needle\r\n"
            )
        path = "../secret" if request.scope_id == "bad-path" else "report.pdf/nested.md"
        result = pb.TextSearchResponse(
            complete=True, items=[pb.TreeEntry(path=path, stat=stat)]
        )
        if request.scope_id == "partial":
            result.complete = False
        if request.scope_id == "foreign-search":
            result.items[0].stat.node.scope_id = "another"
        return result

    async def CreateDirectories(self, request, context):
        assert request.parent.root_id == "mount"
        assert list(request.components) == ["a", "b"] and request.parents
        return pb.CreateDirectoriesResponse(
            node=pb.Node(
                id="nested", scope_id=request.scope_id, name="b", kind="directory"
            )
        )

    def mutation(self, request):
        target = request.target
        stat = self.read_stat(request.scope_id)
        stat.node.revision = 4
        before_revision, before_fingerprint = 3, "before"
        if target.WhichOneof("target") == "create":
            assert target.create.parent.root_id == "mount"
            assert target.create.name == "notes.txt"
            assert target.create.idempotency_key == "key"
            assert target.create.node_id == "stable-node"
            stat.node.id = "stable-node"
            before_revision, before_fingerprint = 0, ""
        else:
            assert target.existing.locator.root_id == "mount"
            assert target.existing.locator.expected_node_id == "file"
            assert target.existing.revision == 3
            assert target.existing.expected_fingerprint == "before"
        if request.scope_id == "bad-mutation":
            before_revision += 1
        return pb.TextMutation(
            stat=stat,
            before_revision=before_revision,
            before_fingerprint=before_fingerprint,
        )

    async def WriteText(self, request, context):
        assert request.content == b"new"
        return pb.WriteTextResponse(result=self.mutation(request))

    async def AppendText(self, request, context):
        assert request.content == b"more"
        return pb.AppendTextResponse(result=self.mutation(request))

    async def PatchText(self, request, context):
        if request.WhichOneof("patch") == "bytes":
            assert request.bytes.offset == 2 and request.bytes.content == b"new"
        else:
            assert (
                request.literal.old_text == "old"
                and request.literal.new_text == "new"
                and request.literal.replace_all
            )
        return pb.PatchTextResponse(result=self.mutation(request))

    async def TruncateText(self, request, context):
        assert request.length == 2 and request.no_create
        return pb.TruncateTextResponse(result=self.mutation(request))

    async def CreateNode(self, request, context):
        assert request.node_id == "stable-node"
        kind = request.WhichOneof("input")
        creation = getattr(request, kind)
        assert creation.parent.root_id == "mount"
        return pb.CreateNodeResponse(
            node=pb.Node(
                id="wrong" if request.scope_id == "bad-node" else request.node_id,
                scope_id=request.scope_id,
                name=creation.name,
                kind="file" if kind == "file" else "directory",
            )
        )

    @staticmethod
    def read_stat(scope_id="shared"):
        return pb.FileStat(
            node=pb.Node(id="file", scope_id=scope_id, kind="file"),
            storage_kind="text",
            representation_kind="text",
            readable_size=11,
            fingerprint="current",
            newline_count=2,
            sha256="text-digest",
        )

    async def Stat(self, request, context):
        assert request.locator.path.path == "/notes.txt"
        assert request.locator.root_id == "mount"
        assert request.content_check
        return pb.StatResponse(stat=self.read_stat(request.scope_id))

    async def ReadText(self, request, context):
        assert request.expected_fingerprint == "current"
        assert request.locator.root_id == "mount"
        selection = request.WhichOneof("selection")
        results = {
            "whole": (b"alpha\nbeta\n", 0),
            "bytes": (b"ph", 2),
            "lines": (b"beta\n", 6),
            "head": (b"alpha\n", 0),
            "tail": (b"beta\n", 6),
        }
        if selection == "bytes":
            assert (request.bytes.offset, request.bytes.length) == (2, 2)
        elif selection == "lines":
            assert (request.lines.start_line, request.lines.line_count) == (2, 1)
        elif selection in {"head", "tail"}:
            assert getattr(request, selection).line_count == 1
        body, offset = results[selection]
        stat = self.read_stat(
            "foreign" if request.scope_id == "foreign-response" else request.scope_id
        )
        return pb.ReadTextResponse(
            stat=stat,
            content=body,
            offset=offset,
            length=len(body) + (1 if request.scope_id == "bad-length" else 0),
        )

    async def TextMetrics(self, request, context):
        assert request.algorithm == "sha256"
        return pb.TextMetricsResponse(
            stat=self.read_stat(),
            algorithm="sha256",
            digest="text-digest",
            supported=True,
        )

    async def ReadTree(self, request, context):
        assert request.root.root_id == "mount"
        assert (request.depth, request.limit, request.max_bytes) == (2, 1, 4096)
        assert request.cursor == "before"
        return pb.ReadTreeResponse(
            items=[pb.TreeEntry(path="notes.txt", stat=self.read_stat())],
            next_cursor="after",
            complete=False,
        )

    async def ReadImage(self, request, context):
        assert request.expected_fingerprint == "current"
        return pb.ReadImageResponse(
            stat=self.read_stat(),
            content=b"preview",
            mime="image/png",
            width=2,
            height=1,
            sha256="preview-digest",
        )

    async def ListNodes(self, request, context):
        assert request.parent.path.path == "/report.pdf"
        assert request.parent.root_id == "mount"
        return pb.ListNodesResponse(
            items=[pb.Node(id="child", scope_id=request.scope_id, readonly=True)]
        )

    async def CreateCopy(self, request, context):
        assert request.scope_id == "shared"
        assert request.destination_scope_id == (
            "shared" if request.idempotency_key == "same-scope" else "personal"
        )
        if request.idempotency_key == "key":
            assert request.source_root_id == "source-mount"
            assert request.destination_root_id == "destination-mount"
        return pb.CreateCopyResponse(
            node=pb.Node(id="copy", scope_id=request.destination_scope_id)
        )

    async def UpdateNode(self, request, context):
        assert request.scope_id == "shared"
        assert request.destination_scope_id == "personal"
        assert request.parent.node_id == "root-personal"
        assert request.locator.root_id == "source-mount"
        assert request.parent.root_id == "destination-mount"
        return pb.UpdateNodeResponse(
            node=pb.Node(id=request.locator.node_id, scope_id="personal")
        )

    async def RestoreTrash(self, request, context):
        assert request.scope_id == "shared"
        assert request.destination_scope_id == "personal"
        assert request.parent.node_id == "root-personal"
        assert request.name == "restored"
        assert request.root_id == "source-mount"
        assert request.parent.root_id == "destination-mount"
        return pb.RestoreTrashResponse(node=pb.Node(id="restored", scope_id="personal"))

    async def BatchStat(self, request, context):
        assert [item.scope_id for item in request.locators] == ["shared", "personal"]
        return pb.BatchStatResponse(
            items=[
                pb.Node(id=item.locator.node_id, scope_id=item.scope_id)
                for item in request.locators
            ]
        )

    async def PurgeTrash(self, request, context):
        return pb.PurgeTrashResponse()

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
                readonly=True,
            )
        )

    async def SearchFiles(self, request, context):
        assert request.scope_id == "shared"
        assert request.query == "report"
        assert request.cursor == "next"
        return pb.SearchFilesResponse(
            items=[
                pb.SearchResult(
                    node=pb.Node(id="file", scope_id="shared"), path="/report.txt"
                )
            ],
            next_cursor="later",
        )

    async def SemanticSearch(self, request, context):
        assert request.filesystem_id == "filesystem"
        assert request.scope_id == "shared"
        assert request.query == "report"
        assert request.limit == 1
        assert "cursor" not in request.DESCRIPTOR.fields_by_name
        return pb.SemanticSearchResponse(
            items=[
                pb.SearchResult(
                    node=pb.Node(id="file", scope_id="shared"), path="/report.txt"
                )
            ],
            degraded=True,
            degraded_reason="RERANK_UNAVAILABLE",
        )

    async def StreamArchive(self, request, context):
        assert request.scope_id == "shared"
        yield pb.StreamArchiveResponse(
            metadata=pb.ArchiveMetadata(filename="files.zip", mime="application/zip")
        )
        yield pb.StreamArchiveResponse(data=b"zip")


class Administration(letfs_rpc.StorageAdministrationServiceServicer):
    async def ListScopes(self, request, context):
        return pb.ListScopesResponse(
            scopes=[
                pb.Scope(
                    id="scope",
                    filesystem_id="foreign"
                    if request.filesystem_id == "bad"
                    else request.filesystem_id,
                    root_id="root",
                    state="active",
                    allow_blob_files=True,
                    allow_indexing=True,
                )
            ],
            next_cursor="next",
        )

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
        assert (
            await FilesystemClient(rpc).get_node("drive", "shared", "file")
        ).readonly


async def test_direct_operations_and_scoped_batch_use_destination_identity(
    letfs_server,
):
    async with RpcClient(letfs_server, TOKEN, allow_plaintext=True) as rpc:
        client = FilesystemClient(rpc)
        copied = await client.create_copy(
            "drive",
            "shared",
            "source",
            "root-personal",
            "key",
            destination_scope_id="personal",
            name="copied",
            revision=1,
            source_root_id="source-mount",
            destination_root_id="destination-mount",
        )
        assert (copied.id, copied.scope_id) == ("copy", "personal")
        same_scope = await client.create_copy(
            "drive", "shared", "source", "root-shared", "same-scope"
        )
        assert same_scope.scope_id == "shared"
        moved = await client.update_node(
            "drive",
            "shared",
            Locator(node_id="source", root_id="source-mount"),
            destination_scope_id="personal",
            parent=Locator(node_id="root-personal", root_id="destination-mount"),
            revision=1,
        )
        assert (moved.id, moved.scope_id) == ("source", "personal")
        restored = await client.restore_trash(
            "drive",
            "shared",
            "entry",
            root_id="source-mount",
            destination_scope_id="personal",
            parent=Locator(node_id="root-personal", root_id="destination-mount"),
            name="restored",
        )
        assert restored.scope_id == "personal"
        nodes = await client.batch_stat(
            "drive",
            [
                ScopedLocator("shared", Locator(node_id="a")),
                ScopedLocator("personal", Locator(node_id="b")),
            ],
        )
        assert [(node.id, node.scope_id) for node in nodes] == [
            ("a", "shared"),
            ("b", "personal"),
        ]
        assert await client.purge_trash("drive", "personal", "entry") is None


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
        "CreateDirectories": "create_directories",
        "ListNodes": "list_nodes",
        "GetNode": "get_node",
        "ResolveNode": "resolve_node",
        "BatchStat": "batch_stat",
        "Stat": "stat",
        "ReadText": "read_text",
        "TextMetrics": "text_metrics",
        "ReadTree": "read_tree",
        "TextSearch": "text_search",
        "ReadImage": "read_image",
        "WriteText": "write_text",
        "AppendText": "append_text",
        "PatchText": "patch_text",
        "TruncateText": "truncate_text",
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
        "ListScopes": "list_scopes",
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


async def test_private_scope_listing_validates_response(letfs_server):
    async with RpcClient(letfs_server, TOKEN, allow_plaintext=True) as rpc:
        client = StorageAdministrationClient(rpc)
        page = await client.list_scopes("drive", limit=1)
        assert page.items[0].filesystem_id == "drive"
        assert page.next_cursor == "next"
        with pytest.raises(AppError, match="invalid scope result"):
            await client.list_scopes("bad")
        with pytest.raises(ValueError, match="invalid scope page"):
            await client.list_scopes("drive", limit=0)


@pytest.mark.asyncio
async def test_search_clients_preserve_scope_and_distinct_contracts(letfs_server):
    async with RpcClient(letfs_server, TOKEN, allow_plaintext=True) as rpc:
        client = FilesystemClient(rpc)
        results = await client.semantic_search(
            "filesystem", "shared", "report", limit=1
        )
        assert results.items[0].node.scope_id == "shared"
        assert results.items[0].path == "/report.txt"
        assert results.degraded_reason == "RERANK_UNAVAILABLE"
        assert not hasattr(results, "next_cursor")
        page = await client.search_files(
            "filesystem", "shared", "report", cursor="next"
        )
        assert page.items[0].node.scope_id == "shared"
        assert page.next_cursor == "later"


async def test_native_reads_preserve_wire_selections_and_mounts(letfs_server):
    async with RpcClient(letfs_server, TOKEN, allow_plaintext=True) as rpc:
        client = FilesystemClient(rpc)
        locator = Locator(path="/notes.txt", root_id="mount", expected_node_id="file")
        stat = await client.stat("drive", "shared", locator, content_check=True)
        assert stat.fingerprint == "current"
        assert stat.readable_size == 11
        assert stat.newline_count == 2
        for selection, body, offset in [
            (TextSelection(), b"alpha\nbeta\n", 0),
            (TextSelection("bytes", offset=2, length=2), b"ph", 2),
            (TextSelection("lines", start_line=2, line_count=1), b"beta\n", 6),
            (TextSelection("head", line_count=1), b"alpha\n", 0),
            (TextSelection("tail", line_count=1), b"beta\n", 6),
        ]:
            read = await client.read_text(
                "drive", "shared", locator, selection, expected_fingerprint="current"
            )
            assert (read.content, read.offset, read.length) == (body, offset, len(body))
            assert read.stat == stat
        metric = await client.text_metrics("drive", "shared", locator, "sha256")
        assert metric.supported and metric.digest == stat.sha256
        page = await client.read_tree(
            "drive",
            "shared",
            Locator(path="/", root_id="mount"),
            depth=2,
            limit=1,
            max_bytes=4096,
            cursor="before",
        )
        assert page.items[0].path == "notes.txt"
        assert page.items[0].stat == stat
        assert page.next_cursor == "after" and not page.complete
        preview = await client.read_image(
            "drive", "shared", locator, expected_fingerprint="current"
        )
        assert (preview.width, preview.height, preview.content) == (2, 1, b"preview")
        assert preview.sha256 == "preview-digest"
        children, cursor = await client.list_nodes(
            "drive", "shared", Locator(path="/report.pdf", root_id="mount")
        )
        assert children[0].readonly and cursor is None
        for scope in ("foreign-response", "bad-length"):
            with pytest.raises(AppError):
                await client.read_text(
                    "drive", scope, locator, expected_fingerprint="current"
                )


async def test_literal_search_preserves_modes_and_rejects_partial_payload(letfs_server):
    async with RpcClient(letfs_server, TOKEN, allow_plaintext=True) as rpc:
        client = FilesystemClient(rpc)
        locator = Locator(node_id="file", root_id="mount")

        async def search(scope, mode="files"):
            return await client.text_search(
                "drive",
                scope,
                locator,
                "needle",
                mode=mode,
                ignore_case=True,
                max_files=5,
                max_lines=10,
                max_bytes=2048,
            )

        files = await search("shared")
        assert files.complete and files.items[0].path == "report.pdf/nested.md"
        lines = await search("shared", "lines")
        assert lines.content == b"needle\r\n" and lines.stat.node.id == "file"
        declined = await search("incomplete")
        assert not declined.complete and not declined.items and declined.stat is None
        for scope in ("partial", "foreign-search", "bad-path"):
            with pytest.raises(AppError):
                await search(scope)


async def test_creation_keeps_stable_node_and_mount_identity(letfs_server):
    async with RpcClient(letfs_server, TOKEN, allow_plaintext=True) as rpc:
        client = FilesystemClient(rpc)
        parent = Locator(node_id="parent", root_id="mount")
        directory = await client.create_directory(
            "drive", "shared", parent, "home", "key", node_id="stable-node"
        )
        assert directory.id == "stable-node" and directory.kind == "directory"
        file = await client.create_inline_file(
            "drive",
            "shared",
            parent,
            "notes.txt",
            b"",
            "text/plain",
            "file-key",
            node_id="stable-node",
        )
        assert file.id == "stable-node" and file.kind == "file"
        with pytest.raises(AppError):
            await client.create_directory(
                "drive", "bad-node", parent, "home", "key", node_id="stable-node"
            )


async def test_text_mutations_preserve_observations_and_creation(letfs_server):
    async with RpcClient(letfs_server, TOKEN, allow_plaintext=True) as rpc:
        client = FilesystemClient(rpc)
        observed = ExistingText(
            Locator(path="/notes.txt", root_id="mount", expected_node_id="file"),
            3,
            "before",
        )
        result = await client.write_text("drive", "shared", observed, b"new")
        assert result.before_revision == 3 and result.before_fingerprint == "before"
        assert result.stat.node.revision == 4
        await client.append_text("drive", "shared", observed, b"more")
        await client.patch_text("drive", "shared", observed, b"new", offset=2)
        await client.patch_text(
            "drive", "shared", observed, b"new", old_text="old", replace_all=True
        )
        await client.truncate_text("drive", "shared", observed, 2, no_create=True)
        created = await client.write_text(
            "drive",
            "shared",
            TextCreation(
                Locator(node_id="parent", root_id="mount"),
                "notes.txt",
                "key",
                node_id="stable-node",
            ),
            b"new",
        )
        assert created.stat.node.id == "stable-node" and created.before_revision == 0
        directory = await client.create_directories(
            "drive",
            "shared",
            Locator(node_id="parent", root_id="mount"),
            ["a", "b"],
            parents=True,
        )
        assert directory.id == "nested"
        with pytest.raises(ValueError):
            await client.patch_text("drive", "shared", observed, b"new")
        with pytest.raises(ValueError):
            await client.patch_text(
                "drive", "shared", observed, b"new", offset=0, old_text="old"
            )
        with pytest.raises(AppError):
            await client.write_text("drive", "bad-mutation", observed, b"new")
